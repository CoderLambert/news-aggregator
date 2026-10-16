"""Source-scoped dry-run/apply/undo with atomic per-mapping audit records."""
import hashlib
import json
import uuid
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from api.models import Category, News, NewsSourceItem
from api.rss.legacy_fencing import legacy_admin_guard, assert_legacy_admin_guard
from api.services.source_policy import POLICIES


class CorrectionConflict(ValueError):
    pass


def fingerprint(news):
    values = [news.pk, news.source_id, news.url, news.title, news.content, news.publish_time.isoformat()]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def build_plan(source_key, *, limit=100, after_id=0):
    from news_crawler.category_map import classify, RULE_VERSION
    if source_key not in POLICIES or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('source and limit 1..500 are required')
    policy = POLICIES[source_key]
    if policy.unsupported_reason:
        raise ValueError('source is not admitted')
    rows = []
    articles = News.objects.filter(source__name=policy.name, pk__gt=after_id).select_related('category').order_by('pk')[:limit]
    for news in articles:
        mapping = NewsSourceItem.objects.filter(news=news, source_key=source_key).order_by('pk').first()
        if mapping is None:
            continue
        target = policy.default_category or classify(news.title, news.content)
        if target == news.category.name:
            continue
        rows.append({'news_id': news.pk, 'source_item_id': mapping.pk, 'old_category_id': news.category_id,
                     'target_category': target, 'fingerprint': fingerprint(news),
                     'rss_guard': legacy_admin_guard(news.source_id, [news.pk])})
    return {'schema': 1, 'batch_id': str(uuid.uuid4()), 'rule_version': RULE_VERSION,
            'source_key': source_key, 'created_at': timezone.now().isoformat(), 'rows': rows}


@transaction.atomic
def execute_plan(plan, *, undo=False):
    from news_crawler.category_map import classify, RULE_VERSION, ALL_CATEGORIES
    if not isinstance(plan, dict) or plan.get('schema') != 1 or not isinstance(plan.get('rows'), list) or len(plan['rows']) > 500:
        raise ValueError('invalid correction plan')
    batch_id = str(uuid.UUID(plan['batch_id']))
    policy = POLICIES.get(plan.get('source_key'))
    if not policy or policy.unsupported_reason or (not undo and plan.get('rule_version') != RULE_VERSION):
        raise CorrectionConflict('source or rule version changed')
    ids = [row.get('source_item_id') for row in plan['rows'] if isinstance(row, dict)]
    if len(ids) != len(plan['rows']) or len(set(ids)) != len(ids) or any(type(pk) is not int or pk <= 0 for pk in ids):
        raise ValueError('invalid mapping identities')
    # First write reserves SQLite writer ownership before validating the plan.
    NewsSourceItem.objects.filter(pk__in=ids).update(last_seen_at=F('last_seen_at'))
    actions = []
    for row in plan['rows']:
        mapping = NewsSourceItem.objects.select_related('news__source', 'news__category').filter(
            pk=row['source_item_id'], news_id=row.get('news_id'), source_key=policy.key).first()
        if mapping is None or mapping.news.source.name != policy.name:
            raise CorrectionConflict('primary publisher changed')
        news = mapping.news
        assert_legacy_admin_guard(row.get('rss_guard'))
        history = list((mapping.metadata or {}).get('category_corrections') or [])
        prior = next((event for event in history if event.get('batch_id') == batch_id), None)
        if prior and ((undo and prior.get('undone_at')) or not undo):
            continue
        if fingerprint(news) != row.get('fingerprint'):
            raise CorrectionConflict('article metadata changed')
        if undo:
            if not prior or news.category_id != prior['new_category_id']:
                raise CorrectionConflict('a later category change prevents undo')
            target_id = prior['old_category_id']
            if not Category.objects.filter(pk=target_id).exists():
                raise CorrectionConflict('original category unavailable')
            actions.append((mapping, history, target_id, prior))
        else:
            expected = policy.default_category or classify(news.title, news.content)
            if (expected != row.get('target_category') or expected not in ALL_CATEGORIES
                    or news.category_id != row.get('old_category_id') or len(history) >= 16):
                raise CorrectionConflict('category or audit history changed')
            category, _ = Category.objects.get_or_create(name=expected, defaults={'slug': ALL_CATEGORIES[expected]['slug']})
            actions.append((mapping, history, category.pk, None))
    now = timezone.now().isoformat()
    for mapping, history, target_id, prior in actions:
        news = mapping.news
        old_id = news.category_id
        if News.objects.filter(pk=news.pk, category_id=old_id, source_id=news.source_id).update(category_id=target_id) != 1:
            raise CorrectionConflict('category changed concurrently')
        if undo:
            prior['undone_at'] = now
        else:
            history.append({'batch_id': batch_id, 'at': now, 'old_category_id': old_id,
                            'new_category_id': target_id, 'rule_version': RULE_VERSION})
        metadata = dict(mapping.metadata or {})
        metadata['category_corrections'] = history
        NewsSourceItem.objects.filter(pk=mapping.pk).update(metadata=metadata)
    return {'batch_id': batch_id, 'operation': 'undo' if undo else 'apply', 'changed': len(actions)}
