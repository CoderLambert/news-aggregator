"""Bounded dry-run/apply/undo for category and publisher-country corrections.

Never opens a URL, calls an AI provider, rewrites an article identity, or
modifies full text, translations, user subscriptions, bookmarks or history.
"""
import hashlib
import json
import uuid
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from api.models import News, Source, Category
from api.metadata_models import MetadataCorrectionAudit
from api.services.source_policy import POLICIES, policy_for_name
from api.services.source_metadata import publisher_country
from news_crawler.category_map import classify, ALL_CATEGORIES, CLASSIFIER_VERSION

PLAN_VERSION = 'metadata-correction-1'
MAX_ROWS = 500


class CorrectionConflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def fingerprint(obj, entity):
    if entity == 'news_category':
        return digest([obj.pk, obj.source_id, obj.url, obj.title, obj.content])
    return digest([obj.pk, obj.name, obj.url, obj.region, obj.language])


def expected_category(news, policy):
    return policy.default_category or classify(news.title, news.content)


def preview(source_key, entity, *, after_id=0, limit=100):
    if source_key not in POLICIES or POLICIES[source_key].unsupported_reason:
        raise ValueError('A reviewed active source key is required')
    if entity not in {'news_category', 'source_country'} or type(limit) is not int or not 1 <= limit <= MAX_ROWS or type(after_id) is not int or after_id < 0:
        raise ValueError('Invalid correction selection')
    policy = POLICIES[source_key]
    rows, inspected = [], []
    if entity == 'news_category':
        objects = list(News.objects.filter(source__name=policy.name, pk__gt=after_id)
                       .select_related('source', 'category').prefetch_related('source_items').order_by('pk')[:limit])
        for obj in objects:
            inspected.append(obj.pk)
            receipts = [m for m in obj.source_items.all() if m.source_key == source_key]
            # A manually edited category is not automatically overwritten by
            # a bulk correction whose original source classification differs.
            if not any(m.metadata.get('category_name') == obj.category.name for m in receipts):
                continue
            target = expected_category(obj, policy)
            if target not in ALL_CATEGORIES or obj.category.name == target:
                continue
            rows.append({'id': obj.pk, 'input_hash': fingerprint(obj, entity),
                         'before': {'id': obj.category_id, 'name': obj.category.name},
                         'after': {'name': target}})
    else:
        # Unknown publisher locations require human research, not an automatic
        # guess or automatic deletion of existing administrator metadata.
        target = publisher_country(source_key)
        objects = list(Source.objects.filter(name=policy.name, pk__gt=after_id).order_by('pk')[:limit])
        for obj in objects:
            inspected.append(obj.pk)
            if not target or obj.country == target:
                continue
            rows.append({'id': obj.pk, 'input_hash': fingerprint(obj, entity),
                         'before': {'country': obj.country}, 'after': {'country': target}})
    return {'version': PLAN_VERSION, 'classifier_version': CLASSIFIER_VERSION,
            'run_id': str(uuid.uuid4()), 'source_key': source_key, 'entity': entity,
            'inspected': len(inspected), 'next_after_id': inspected[-1] if inspected else after_id,
            'rows': rows}


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('version') != PLAN_VERSION or plan.get('classifier_version') != CLASSIFIER_VERSION:
        raise ValueError('Unknown or outdated correction plan')
    run_id = uuid.UUID(plan.get('run_id', ''))
    source_key, entity, rows = plan.get('source_key'), plan.get('entity'), plan.get('rows')
    if (source_key not in POLICIES or POLICIES[source_key].unsupported_reason
            or entity not in {'news_category', 'source_country'}
            or not isinstance(rows, list) or len(rows) > MAX_ROWS):
        raise ValueError('Invalid correction plan scope')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0
                or row['id'] in seen or not isinstance(row.get('before'), dict)
                or not isinstance(row.get('after'), dict) or not isinstance(row.get('input_hash'), str)
                or len(row['input_hash']) != 64):
            raise ValueError('Invalid correction row')
        seen.add(row['id'])
    return run_id, source_key, entity, rows


@transaction.atomic
def _apply_row(run_id, source_key, entity, row, operator):
    model = News if entity == 'news_category' else Source
    query = model.objects.filter(pk=row['id'])
    # First SQL write reserves the SQLite writer, including missing row paths.
    if not query.update(id=F('id')):
        raise CorrectionConflict('object_missing')
    existing = MetadataCorrectionAudit.objects.filter(run_id=run_id, entity=entity, object_pk=row['id']).first()
    if existing is not None:
        if existing.source_key == source_key and existing.input_hash == row['input_hash'] and existing.before == row['before'] and existing.after == row['after']:
            return 'already_applied' if existing.undone_at is None else 'already_undone'
        raise CorrectionConflict('run_id_reused')
    obj = model.objects.get(pk=row['id'])
    policy = POLICIES[source_key]
    source_name = obj.source.name if entity == 'news_category' else obj.name
    if source_name != policy.name or fingerprint(obj, entity) != row['input_hash']:
        raise CorrectionConflict('evidence_changed')
    if entity == 'news_category':
        if row['before'] != {'id': obj.category_id, 'name': obj.category.name}:
            raise CorrectionConflict('category_changed')
        if not obj.source_items.filter(source_key=source_key, metadata__category_name=obj.category.name).exists():
            raise CorrectionConflict('manual_category_changed')
        target = expected_category(obj, policy)
        if target not in ALL_CATEGORIES or row['after'] != {'name': target}:
            raise CorrectionConflict('rule_changed')
        category, _ = Category.objects.get_or_create(name=target, defaults={'slug': ALL_CATEGORIES[target]['slug']})
        query.update(category_id=category.pk)
    else:
        target = publisher_country(source_key)
        if row['before'] != {'country': obj.country} or not target or row['after'] != {'country': target}:
            raise CorrectionConflict('country_changed')
        query.update(country=target)
    MetadataCorrectionAudit.objects.create(run_id=run_id, entity=entity, object_pk=obj.pk,
        source_key=source_key, input_hash=row['input_hash'], before=row['before'], after=row['after'], operator=operator)
    return 'applied'


def apply(plan, *, operator):
    if not isinstance(operator, str) or not 1 <= len(operator.strip()) <= 80:
        raise ValueError('An operator label is required')
    run_id, source_key, entity, rows = validate_plan(plan)
    results = []
    for row in rows:
        try:
            state = _apply_row(run_id, source_key, entity, row, operator.strip())
        except CorrectionConflict as exc:
            state = str(exc)
        results.append({'id': row['id'], 'result': state})
    return {'run_id': str(run_id), 'results': results}


@transaction.atomic
def _undo_one(audit_id):
    audit = MetadataCorrectionAudit.objects.get(pk=audit_id)
    model = News if audit.entity == 'news_category' else Source
    query = model.objects.filter(pk=audit.object_pk)
    if not query.update(id=F('id')):
        raise CorrectionConflict('object_missing')
    audit.refresh_from_db()
    if audit.undone_at is not None:
        return 'already_undone'
    obj = model.objects.get(pk=audit.object_pk)
    if fingerprint(obj, audit.entity) != audit.input_hash:
        raise CorrectionConflict('evidence_changed')
    if audit.entity == 'news_category':
        if obj.category.name != audit.after['name'] or not Category.objects.filter(pk=audit.before['id'], name=audit.before['name']).exists():
            raise CorrectionConflict('category_changed')
        query.update(category_id=audit.before['id'])
    else:
        if obj.country != audit.after['country']:
            raise CorrectionConflict('country_changed')
        query.update(country=audit.before['country'])
    audit.undone_at = timezone.now(); audit.save(update_fields=['undone_at'])
    return 'undone'


def undo(run_id):
    run_id = uuid.UUID(str(run_id))
    ids = list(MetadataCorrectionAudit.objects.filter(run_id=run_id).order_by('pk').values_list('id', flat=True)[:MAX_ROWS])
    results = []
    for pk in ids:
        try:
            state = _undo_one(pk)
        except CorrectionConflict as exc:
            state = str(exc)
        results.append({'audit_id': pk, 'result': state})
    return {'run_id': str(run_id), 'results': results}
