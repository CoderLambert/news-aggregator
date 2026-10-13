"""Bounded, evidence-led repairs; preserve historical text and every row ID.

Prepared audit records are durable before a database write. They can be used for
CAS undo even if a process exits between commit and recording its final outcome.
No operation contacts publishers, merges rows, creates Sources or changes flags.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F
from django.utils import timezone

from api.models import News, NewsSourceItem, Source
from api.services.article_identity import normalize_article_url
from api.services.full_content_status import _known_cooldown, fetch_eligibility
from api.services.source_dates import parse_source_datetime
from api.services.source_policy import POLICIES


MAX_OPERATIONS = 1000
MAX_INPUT_BYTES = 2 * 1024 * 1024
NEWS_FIELDS = (
    'source_id', 'url', 'full_content_revision', 'full_content_state',
    'full_content_fetch_status', 'full_content_error_code', 'full_content_retry_count',
    'full_content_next_attempt_at', 'full_content_task_created_at', 'last_full_content_attempt',
    'suggested_questions', 'suggested_questions_generated_at',
)
DATE_FIELDS = {'full_content_task_created_at', 'full_content_next_attempt_at', 'last_full_content_attempt', 'suggested_questions_generated_at'}
NEWS_GUARDS = ('source_id', 'url', 'full_content_revision')


class RepairInputError(ValueError):
    pass


class RepairConflict(ValueError):
    pass


def _digest(text):
    return hashlib.sha256((text or '').encode()).hexdigest()


def database_fingerprint():
    # Prevent accidentally replaying an audit against a different database path.
    return _digest(os.path.abspath(str(settings.DATABASES['default']['NAME'])))


def _plain(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _news_snapshot(news):
    return {**{field: _plain(getattr(news, field)) for field in NEWS_FIELDS},
            'body_sha256': _digest(news.full_content), 'translation_sha256': _digest(news.full_content_zh)}


def _decode(snapshot):
    fields = {field: snapshot[field] for field in NEWS_FIELDS}
    for field in DATE_FIELDS:
        value = fields[field]
        if value is not None:
            value = parse_source_datetime(value)
            if value is None:
                raise RepairInputError('invalid_audit_timestamp')
        fields[field] = value
    return fields


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise RepairInputError('input_must_be_bounded_regular_json_file')
    try:
        return json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError):
        raise RepairInputError('invalid_json_input') from None


def _positive(value):
    return type(value) is int and value > 0


def _evidence(value, kinds):
    if not isinstance(value, dict) or value.get('kind') not in kinds:
        raise RepairInputError('explicit_evidence_kind_required')
    fields = {'kind', 'source_key', 'reference'}
    if value['kind'] in {'verified_article_url', 'equivalent_article_url'}:
        fields.add('verified_url')
    if value['kind'] == 'equivalent_article_url':
        fields.add('body_sha256')
    if set(value) != fields:
        raise RepairInputError('evidence_fields_are_incomplete_or_unknown')
    if not isinstance(value.get('reference'), str) or not value['reference'].strip() or len(value['reference']) > 2000:
        raise RepairInputError('explicit_evidence_reference_required')
    if value.get('source_key') not in POLICIES:
        raise RepairInputError('reviewed_source_key_required')


def validate_mapping(value, *, limit=100):
    if not isinstance(value, dict) or set(value) != {'schema_version', 'operations'} or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise RepairInputError('invalid_mapping_schema')
    operations = value['operations']
    if not isinstance(operations, list) or not 1 <= len(operations) <= min(limit, MAX_OPERATIONS):
        raise RepairInputError('explicit_bounded_operations_required')
    seen = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise RepairInputError('invalid_operation')
        action = operation.get('action')
        if action == 'rename_leiphone_source':
            if set(operation) != {'action', 'source_id', 'expected', 'news_ids', 'evidence'} or not _positive(operation['source_id']):
                raise RepairInputError('invalid_source_rename')
            expected = operation['expected']
            if not isinstance(expected, dict) or set(expected) != {'name', 'url'} or not all(isinstance(value, str) for value in expected.values()):
                raise RepairInputError('explicit_source_old_values_required')
            ids = operation['news_ids']
            if not isinstance(ids, list) or not ids or len(ids) > MAX_OPERATIONS or any(not _positive(pk) for pk in ids) or len(set(ids)) != len(ids):
                raise RepairInputError('explicit_complete_news_ids_required')
            _evidence(operation['evidence'], {'publisher_source_identity'})
            if operation['evidence']['source_key'] != 'leiphone':
                raise RepairInputError('only_reviewed_leiphone_rename_supported')
            identity = ('source', operation['source_id'])
        elif action in {'repair_news_identity', 'quarantine_unverified_identity'}:
            fields = {'action', 'news_id', 'expected', 'evidence'} | ({'new'} if action == 'repair_news_identity' else set())
            if set(operation) != fields or not _positive(operation['news_id']):
                raise RepairInputError('invalid_news_operation')
            expected = operation['expected']
            if (not isinstance(expected, dict) or set(expected) != set(NEWS_GUARDS) or
                    not _positive(expected['source_id']) or not isinstance(expected['url'], str) or
                    type(expected['full_content_revision']) is not int or expected['full_content_revision'] < 0):
                raise RepairInputError('explicit_news_old_identity_revision_required')
            if action == 'repair_news_identity':
                new = operation['new']
                if not isinstance(new, dict) or not new or not set(new) <= {'source_id', 'url'}:
                    raise RepairInputError('only_source_fk_and_url_changes_supported')
                if 'source_id' in new and not _positive(new['source_id']):
                    raise RepairInputError('existing_target_source_id_required')
                if 'url' in new and not isinstance(new['url'], str):
                    raise RepairInputError('explicit_target_url_required')
                _evidence(operation['evidence'], {'verified_article_url', 'equivalent_article_url'})
            else:
                _evidence(operation['evidence'], {'unverified_identity'})
                if operation['evidence']['source_key'] not in {'reuters', 'jiqizhixin'}:
                    raise RepairInputError('only_quarantined_unverified_sources_supported')
            identity = ('news', operation['news_id'])
        else:
            raise RepairInputError('unsupported_repair_action')
        if identity in seen:
            raise RepairInputError('duplicate_repair_target')
        seen.add(identity)
    return operations


def _source_snapshot(source):
    return {'name': source.name, 'url': source.url}


def _source_for_policy(source, policy):
    from urllib.parse import urlsplit
    try:
        normalize_article_url(source.url, max_length=255, require_article=False)
    except ValueError:
        return False
    return source.name == policy.name and urlsplit(source.url).hostname in policy.domains


def _rename_guards(source, ids):
    from urllib.parse import urlsplit
    policy = POLICIES['leiphone']
    if urlsplit(source.url).hostname not in policy.domains:
        raise RepairConflict('source_url_not_leiphone')
    try:
        normalize_article_url(source.url, max_length=255, require_article=False)
    except ValueError:
        raise RepairConflict('source_url_not_leiphone') from None
    news = list(News.objects.filter(source_id=source.pk).order_by('pk'))
    if {row.pk for row in news} != set(ids):
        raise RepairConflict('source_news_scope_changed_or_incomplete')
    if any(urlsplit(row.url).hostname not in policy.domains for row in news):
        raise RepairConflict('mixed_publisher_source')
    if NewsSourceItem.objects.filter(news_id__in=ids).exclude(source_key='leiphone').exists():
        raise RepairConflict('mixed_upstream_source_identity')
    return [{'news_id': row.pk, **{field: getattr(row, field) for field in NEWS_GUARDS}} for row in news]


def _identity_target(operation, news):
    from urllib.parse import urlsplit
    policy = POLICIES[operation['evidence']['source_key']]
    new = operation['new']
    url = normalize_article_url(new.get('url', news.url))
    if url != new.get('url', news.url):
        raise RepairConflict('target_url_must_already_be_normalized')
    if urlsplit(url).hostname not in policy.domains or operation['evidence'].get('verified_url') != url:
        raise RepairConflict('target_publisher_url_not_explicitly_verified')
    source = Source.objects.get(pk=new.get('source_id', news.source_id))
    if not _source_for_policy(source, policy):
        raise RepairConflict('target_source_does_not_match_reviewed_publisher')
    return source, url


def _already_satisfied(operation, news):
    expected = operation['expected']
    if news.full_content_revision != expected['full_content_revision'] + 1:
        return False
    if operation['action'] == 'quarantine_unverified_identity':
        return (news.source_id == expected['source_id'] and news.url == expected['url'] and
                news.full_content_state == 'missing' and news.full_content_fetch_status == 'unsupported' and
                news.full_content_error_code == 'invalid_identity')
    new = operation['new']
    return news.source_id == new.get('source_id', expected['source_id']) and news.url == new.get('url', expected['url'])


def plan_operation(operation):
    plan = dict(action=operation['action'], evidence=operation['evidence'], outcome='proposed')
    plan['source_id' if operation['action'] == 'rename_leiphone_source' else 'news_id'] = operation.get('source_id', operation.get('news_id'))
    try:
        if operation['action'] == 'rename_leiphone_source':
            source = Source.objects.get(pk=operation['source_id'])
            plan['source_id'] = source.pk
            plan['before'] = _source_snapshot(source)
            if source.name == '雷峰网' and source.url == operation['expected']['url']:
                plan.update(outcome='already_satisfied', after=plan['before'])
                return plan
            if _source_snapshot(source) != operation['expected']:
                raise RepairConflict('expected_source_values_changed')
            if source.name != '量子位':
                raise RepairConflict('only_historical_leiphone_mislabel_supported')
            if Source.objects.filter(name='雷峰网').exclude(pk=source.pk).exists():
                raise RepairConflict('target_source_exists_no_automatic_merge')
            plan['news_guards'] = _rename_guards(source, operation['news_ids'])
            plan['after'] = {**plan['before'], 'name': '雷峰网'}
        else:
            news = News.objects.get(pk=operation['news_id'])
            plan['news_id'] = news.pk
            plan['before'] = _news_snapshot(news)
            plan['original_source'] = {'source_id': news.source_id, **_source_snapshot(news.source)}
            if any(getattr(news, field) != operation['expected'][field] for field in NEWS_GUARDS):
                if _already_satisfied(operation, news):
                    plan.update(outcome='already_satisfied', after=plan['before'])
                    return plan
                raise RepairConflict('expected_news_identity_revision_changed')
            after = {**plan['before'], 'full_content_revision': news.full_content_revision + 1}
            if operation['action'] == 'quarantine_unverified_identity':
                policy = POLICIES[operation['evidence']['source_key']]
                if news.source.name != policy.name:
                    raise RepairConflict('quarantine_source_evidence_mismatch')
                after.update(full_content_state='missing', full_content_fetch_status='unsupported',
                             full_content_error_code='invalid_identity', full_content_next_attempt_at=None, full_content_task_created_at=None,
                             last_full_content_attempt=None)
            else:
                source, url = _identity_target(operation, news)
                plan['target_source'] = {'source_id': source.pk, **_source_snapshot(source)}
                if source.pk == news.source_id and url == news.url:
                    plan.update(outcome='already_satisfied', after=plan['before'])
                    return plan
                if News.objects.filter(url=url).exclude(pk=news.pk).exists():
                    raise RepairConflict('target_url_exists_no_automatic_merge')
                equivalent = operation['evidence']['kind'] == 'equivalent_article_url'
                if equivalent and operation['evidence'].get('body_sha256') != plan['before']['body_sha256']:
                    raise RepairConflict('equivalent_body_digest_evidence_required')
                after.update(source_id=source.pk, url=url, last_full_content_attempt=None)
                if url != news.url:
                    # A reviewed identity correction starts a different article
                    # attempt generation; this is never the ordinary force path.
                    after['full_content_retry_count'] = 0
                    after.update(suggested_questions=[], suggested_questions_generated_at=None)
                    if not equivalent:
                        after['full_content_state'] = 'missing'
                prospective = News(content_kind=news.content_kind, url=url)
                rejection = fetch_eligibility(prospective)
                if not rejection and after['full_content_retry_count'] >= 5:
                    rejection = 'retry_exhausted'
                after.update(full_content_fetch_status='unsupported' if rejection else 'queued',
                             full_content_error_code=rejection or 'identity_changed',
                             full_content_next_attempt_at=None if rejection else _known_cooldown(url).isoformat(),
                             full_content_task_created_at=None if rejection else timezone.now().isoformat())
            plan['after'] = after
    except (Source.DoesNotExist, News.DoesNotExist):
        plan.update(outcome='conflict', reason='explicit_target_not_found')
    except (RepairConflict, ValueError) as error:
        plan.update(outcome='conflict', reason=str(error))
    return plan


def _assert_source_guard(plan):
    for name in ('target_source', 'original_source'):
        if name not in plan:
            continue
        guard = plan[name]
        if not Source.objects.filter(pk=guard['source_id'], name=guard['name'], url=guard['url']).exists():
            raise RepairConflict('target_source_values_changed')


def _assert_news_guards(plan):
    guards = plan['news_guards']
    if set(News.objects.filter(source_id=plan['source_id']).values_list('pk', flat=True)) != {guard['news_id'] for guard in guards}:
        raise RepairConflict('source_news_scope_changed_or_incomplete')
    for guard in guards:
        if not News.objects.filter(pk=guard['news_id'], **{field: guard[field] for field in NEWS_GUARDS}).exists():
            raise RepairConflict('related_news_body_version_or_identity_changed')
    if NewsSourceItem.objects.filter(news_id__in=[guard['news_id'] for guard in guards]).exclude(source_key='leiphone').exists():
        raise RepairConflict('mixed_upstream_source_identity')


def _assert_cooldown_not_earlier(after):
    if after['full_content_fetch_status'] not in {'queued', 'fetching', 'rate_limited', 'network_error', 'failed'}:
        return
    from api.models import RequestBudget
    from api.services.request_budget import scope_intervals
    deadlines = list(RequestBudget.objects.filter(key__in=scope_intervals(after['url']), cooldown_until__isnull=False).values_list('cooldown_until', flat=True))
    next_attempt = _decode(after)['full_content_next_attempt_at']
    if deadlines and (next_attempt is None or next_attempt < max(deadlines)):
        raise RepairConflict('persistent_cooldown_changed_review_again')


def apply_plan(plan, *, undo=False):
    if plan['outcome'] != 'proposed':
        return plan
    result = {**plan}
    try:
        with transaction.atomic():
            if 'source_id' in plan:
                # Reserve SQLite's writer before rechecking the guarded scope.
                if Source.objects.filter(pk=plan['source_id'], **plan['before']).update(name=plan['before']['name']) != 1:
                    raise RepairConflict('expected_source_values_changed')
                _assert_news_guards(plan)
                if Source.objects.filter(name=plan['after']['name']).exclude(pk=plan['source_id']).exists():
                    raise RepairConflict('target_source_exists_no_automatic_merge')
                if Source.objects.filter(pk=plan['source_id'], **plan['before']).update(**plan['after']) != 1:
                    raise RepairConflict('source_compare_and_swap_lost')
            else:
                before = plan['before']
                query = News.objects.filter(pk=plan['news_id'], **_decode(before))
                if query.update(full_content_revision=F('full_content_revision')) != 1:
                    raise RepairConflict('news_values_or_body_version_changed')
                news = News.objects.get(pk=plan['news_id'])
                if _news_snapshot(news) != before:
                    raise RepairConflict('body_or_translation_evidence_changed')
                _assert_source_guard(plan)
                _assert_cooldown_not_earlier(plan['after'])
                if News.objects.filter(url=plan['after']['url']).exclude(pk=news.pk).exists():
                    raise RepairConflict('target_url_exists_no_automatic_merge')
                if query.update(**_decode(plan['after'])) != 1:
                    raise RepairConflict('news_compare_and_swap_lost')
            result['outcome'] = 'undone' if undo else 'applied'
    except (RepairConflict, IntegrityError, OperationalError) as error:
        result.update(outcome='conflict', reason=str(error) if isinstance(error, RepairConflict) else 'database_write_conflict')
    return result


def new_audit(plans, *, mode):
    return dict(schema_version=1, kind='repair_news_sources', database=database_fingerprint(),
                mode=mode, operations=[{**plan, 'outcome': 'prepared' if plan['outcome'] == 'proposed' else plan['outcome']} for plan in plans])


def write_audit(path, audit, *, new=False):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise RepairInputError('audit_output_must_be_absolute_regular_path')
    if new and path.exists():
        raise RepairInputError('audit_output_already_exists')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.news-repair-', delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(audit, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if new:
            os.link(temporary, path)
            temporary.unlink()
        else:
            os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise RepairInputError('audit_write_failed') from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def plan_undo(value, *, limit=100):
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'kind', 'database', 'mode', 'operations'} or
            type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != 'repair_news_sources' or
            value['database'] != database_fingerprint() or value['mode'] not in {'apply', 'undo'} or
            not isinstance(value['operations'], list) or not 1 <= len(value['operations']) <= min(limit, MAX_OPERATIONS)):
        raise RepairInputError('invalid_or_foreign_repair_audit')
    plans = []
    for entry in value['operations']:
        if not isinstance(entry, dict) or entry.get('action') not in {'rename_leiphone_source', 'repair_news_identity', 'quarantine_unverified_identity'}:
            raise RepairInputError('invalid_audit_operation')
        if entry.get('outcome') not in {'applied', 'prepared', 'undone'}:
            plans.append({**entry, 'outcome': 'skipped', 'reason': 'original_operation_was_not_applied'})
            continue
        if not isinstance(entry.get('before'), dict) or not isinstance(entry.get('after'), dict):
            raise RepairInputError('audit_snapshots_required')
        plan = {**entry, 'before': entry['after'], 'after': entry['before'], 'outcome': 'proposed'}
        try:
            if entry['action'] == 'rename_leiphone_source':
                if set(plan['before']) != {'name', 'url'} or set(plan['after']) != {'name', 'url'} or not _positive(plan.get('source_id')) or not isinstance(plan.get('news_guards'), list):
                    raise RepairInputError('invalid_source_audit_snapshot')
                source = Source.objects.get(pk=plan['source_id'])
                if _source_snapshot(source) == plan['after']:
                    plan.update(outcome='already_satisfied')
                elif _source_snapshot(source) != plan['before']:
                    raise RepairConflict('undo_source_written_values_changed')
                else:
                    _assert_news_guards(plan)
                    if Source.objects.filter(name=plan['after']['name']).exclude(pk=source.pk).exists():
                        raise RepairConflict('undo_source_name_conflict')
            else:
                required = {*NEWS_FIELDS, 'body_sha256', 'translation_sha256'}
                if set(plan['before']) != required or set(plan['after']) != required or not _positive(plan.get('news_id')):
                    raise RepairInputError('invalid_news_audit_snapshot')
                _decode(plan['before'])
                _decode(plan['after'])
                news = News.objects.get(pk=plan['news_id'])
                if _news_snapshot(news) != plan['before']:
                    # An undo rerun may observe exactly the earlier restoration,
                    # except its monotonically increased revision.
                    restored = {**plan['after'], 'full_content_revision': plan['before']['full_content_revision'] + 1}
                    if _news_snapshot(news) == restored:
                        plan.update(outcome='already_satisfied')
                    else:
                        raise RepairConflict('undo_written_values_or_body_version_changed')
                else:
                    plan['after'] = {**plan['after'], 'full_content_revision': news.full_content_revision + 1}
                    # Undo changes the URL/source back. It must not compare the
                    # forward target Source as though it were the reverse target.
                    source = Source.objects.get(pk=plan['after']['source_id'])
                    plan['target_source'] = entry.get('original_source', {'source_id': source.pk, **_source_snapshot(source)})
                    if 'target_source' in entry:
                        plan['original_source'] = entry['target_source']
                    if News.objects.filter(url=plan['after']['url']).exclude(pk=news.pk).exists():
                        raise RepairConflict('undo_target_url_conflict')
        except (News.DoesNotExist, Source.DoesNotExist):
            plan.update(outcome='conflict', reason='undo_target_not_found')
        except RepairConflict as error:
            plan.update(outcome='conflict', reason=str(error))
        plans.append(plan)
    return plans
