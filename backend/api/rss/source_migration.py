"""Resumable source-group cutover. Local DB writes never encompass engine I/O.

An executable manifest is an explicit operational mapping, not the T24 inventory
(which remains production_ready=false). This module never terminates processes,
restores a database, changes publication, or rewrites retained article text.
"""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
from pathlib import Path
import uuid

from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import F
from django.utils import timezone

from api.models import FeedBinding, FeedOperation, News, Source, SourceConfig, SourceFeedLink, SourcePublication
from api.rss.engine import EngineError, PolicyBinding
from api.rss.migration_inventory import canonical_feed
from api.services.source_policy import policy_for_key, policy_for_name


class MigrationBlocked(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise MigrationBlocked(reason)


def _binding_ids(row):
    values = row.get('binding_ids', [row['binding_id']] if row.get('binding_id') else [])
    _require(isinstance(values, list), 'invalid_binding_ids')
    try:
        ids = [uuid.UUID(str(value)) for value in values]
    except (ValueError, TypeError):
        raise MigrationBlocked('invalid_binding_ids') from None
    _require(len(ids) == len(set(ids)), 'duplicate_binding_ids')
    return ids


def _affected_binding_ids(rows):
    # Removed links also need engine reconciliation; leaving an orphaned old
    # binding enabled would keep physical collection running after a switch.
    ids = {pk for row in rows for pk in _binding_ids(row)}
    ids.update(SourceFeedLink.objects.filter(source_id__in=[row['source_id'] for row in rows])
        .values_list('binding_id', flat=True))
    return ids


def _target_check(manifest, environment):
    _require(environment in {'isolated', 'production'} and manifest.get('environment') == environment, 'environment_mismatch')
    _require(manifest.get('schema_version') == 1 and manifest.get('kind') == 'rss_source_migration', 'not_executable_migration_manifest')
    uuid.UUID(manifest['id'])
    configured = str(connection.settings_dict['NAME'])
    path = configured if configured.startswith('file:memorydb_') else str(Path(configured).resolve())
    target = manifest.get('target', {})
    _require(target.get('database') == path and path in manifest.get('allowlist', {}).get('databases', []), 'database_not_allowlisted')
    _require(not (getattr(settings, 'DJANGO_ENV', '') == 'production' and environment != 'production'), 'production_requires_production_mode')
    if not configured.startswith('file:memorydb_'):
        _require(Path(path).is_file() and not Path(configured).is_symlink(), 'database_target_not_regular')
        stat = Path(path).stat()
        _require(target.get('device') == stat.st_dev and target.get('inode') == stat.st_ino, 'database_target_replaced')
    uuid.UUID(target['engine_instance_uuid'])
    _require(type(target.get('account_id')) is int and target['account_id'] > 0, 'invalid_engine_account')
    _require(target.get('engine_base_url') in manifest.get('allowlist', {}).get('engine_base_urls', []), 'engine_not_allowlisted')
    return target


def _rows(manifest, source_ids):
    ids = set(source_ids)
    _require(ids and all(type(pk) is int and pk > 0 for pk in ids), 'invalid_source_ids')
    rows = manifest.get('sources')
    _require(isinstance(rows, list), 'invalid_sources')
    indexed = {row['source_id']: row for row in rows}
    _require(len(indexed) == len(rows) and ids <= indexed.keys(), 'source_scope_mismatch')
    selected = [indexed[pk] for pk in sorted(ids)]
    for row in selected:
        _require(row.get('expected_owner') in {'legacy', 'miniflux', 'paused'} and
                 row.get('target_owner') in {'legacy', 'miniflux', 'paused'} and
                 type(row.get('expected_epoch')) is int and row['expected_epoch'] > 0 and
                 type(row.get('expected_policy_version')) is int and row['expected_policy_version'] > 0, 'invalid_source_transition')
        _require(row.get('association_policy', {'version': 1, 'mode': 'all'}) == {'version': 1, 'mode': 'all'}, 'association_filter_requires_supported_validator')
        if row['target_owner'] == 'miniflux':
            _require(_binding_ids(row), 'miniflux_binding_required')
        if row['target_owner'] == 'legacy':
            keys = row.get('legacy_source_keys', [])
            _require(keys, 'new_feed_cannot_return_to_legacy')
            source = Source.objects.get(pk=row['source_id'])
            for key in keys:
                policy = policy_for_key(key)
                _require(policy and not policy.unsupported_reason and (
                    policy.name == source.name or SourceConfig.objects.filter(source_id=source.pk, source_key=key).exists()),
                    'legacy_source_not_supported')
    return selected, indexed


def _production_gate(manifest, ids):
    authorization = manifest.get('authorization', {})
    now = timezone.now()
    try:
        start = datetime.fromisoformat(authorization['window_start'])
        end = datetime.fromisoformat(authorization['window_end'])
        _require(start.tzinfo and end.tzinfo and start <= now <= end, 'outside_approved_window')
    except (KeyError, ValueError, TypeError):
        raise MigrationBlocked('approved_window_missing') from None
    _require(authorization.get('environment') == 'production' and authorization.get('manifest_id') == manifest['id']
        and set(ids) <= set(authorization.get('source_ids', [])) and authorization.get('change_reference'), 'production_scope_not_approved')
    compatibility = manifest.get('compatibility', {})
    current_schema = sorted(f'{app}.{name}' for app, name in MigrationRecorder(connection).applied_migrations())
    _require(compatibility.get('status') == 'sealed' and compatibility.get('app_sha') == manifest.get('app_sha')
        and compatibility.get('image_digest', '').startswith('sha256:') and compatibility.get('schema_set') == current_schema,
        'sealed_compatibility_mismatch')
    backup = manifest.get('backup', {})
    _require(backup.get('engine_instance_uuid') == manifest['target']['engine_instance_uuid']
        and backup.get('account_id') == manifest['target']['account_id'] and backup.get('paired_snapshot_id'), 'paired_backup_missing')
    for key in ('sqlite', 'postgres'):
        row = backup.get(key, {})
        path = row.get('path')
        _require(path and path in manifest.get('allowlist', {}).get('backups', []), 'backup_not_allowlisted')
        file = Path(path)
        _require(file.is_file() and not file.is_symlink(), 'backup_missing')
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        _require(digest.hexdigest() == row.get('sha256'), 'backup_hash_mismatch')
    roles = {row.get('role') for row in manifest.get('drain', {}).get('old_processes', [])}
    _require({'app', 'legacy'} <= roles, 'old_process_snapshot_incomplete')


def _drained(manifest):
    drain = manifest.get('drain', {})
    _require(drain.get('fenced_version') == manifest.get('app_sha') and bool(drain.get('fenced_version')), 'fenced_binary_not_declared')
    _require(isinstance(drain.get('old_processes'), list), 'old_process_snapshot_missing')
    for old in drain['old_processes']:
        _require(type(old.get('pid')) is int and old['pid'] > 0 and str(old.get('start_ticks', '')).isdigit(), 'invalid_old_process_identity')
        proc = Path('/proc') / str(old['pid']) / 'stat'
        try:
            # comm can contain spaces/parens; fields after the final ')' begin at state (3).
            current_start = proc.read_text().rsplit(')', 1)[1].split()[19]
        except FileNotFoundError:
            continue
        _require(current_start != str(old['start_ticks']), 'old_unfenced_process_still_running')


def _shared_group_check(rows, indexed):
    selected = {row['source_id'] for row in rows}
    binding_ids = _affected_binding_ids(rows)
    for pk in binding_ids:
        required = set(SourceFeedLink.objects.filter(binding_id=pk, source__publication__owner='legacy').values_list('source_id', flat=True))
        required.update(row['source_id'] for row in indexed.values() if pk in _binding_ids(row))
        binding = FeedBinding.objects.get(pk=pk)
        # Include old configured/static feeds even before a SourceFeedLink exists.
        for source in Source.objects.filter(publication__owner='legacy'):
            policy = policy_for_name(source.name)
            urls = [policy.feed_url] if policy and policy.feed_url else []
            config = SourceConfig.objects.filter(source=source).first()
            if config:
                urls += list(config.endpoints.filter(enabled=True, kind__in=['rss', 'atom']).values_list('url', flat=True))
            for url in urls:
                try:
                    if canonical_feed(url) == binding.canonical_feed_url:
                        required.add(source.pk)
                except ValueError:
                    continue
        _require(required <= selected, 'shared_feed_group_incomplete')


def _check_phase(manifest, rows):
    marker = 'rss_migration:' + manifest['id']
    phases = []
    for row in rows:
        publication = SourcePublication.objects.get(source_id=row['source_id'])
        _require(publication.policy_version == row['expected_policy_version'], 'source_policy_changed')
        if publication.owner == row['expected_owner'] and publication.epoch == row['expected_epoch']:
            phases.append('initial')
        elif publication.owner == 'paused' and publication.epoch == row['expected_epoch'] + 1 and publication.pause_reason == marker:
            phases.append('paused')
        elif publication.owner == row['target_owner'] and publication.epoch == row['expected_epoch'] + 2:
            phases.append('complete')
        else:
            raise MigrationBlocked('source_owner_or_epoch_changed')
    _require(len(set(phases)) == 1, 'source_group_phase_mismatch')
    return phases[0]


def _active_operations(binding_ids):
    return FeedOperation.objects.filter(binding_id__in=binding_ids, state__in=[
        'pending', 'running', 'retry_wait', 'unknown', 'manual_blocked']).exists()


def plan(manifest, *, source_ids, environment):
    target = _target_check(manifest, environment)
    rows, indexed = _rows(manifest, source_ids)
    _shared_group_check(rows, indexed)
    bindings = list(FeedBinding.objects.filter(pk__in=_affected_binding_ids(rows)))
    _require(len(bindings) == len(_affected_binding_ids(rows)), 'binding_missing')
    for binding in bindings:
        _require(str(binding.engine_instance_uuid) == target['engine_instance_uuid'] and binding.account_id == target['account_id']
            and binding.engine_feed_id is not None, 'engine_identity_mismatch')
    phase = _check_phase(manifest, rows)
    _takeover(rows, mutate=False)
    _check_collection_policy(rows)
    return {'manifest_id': manifest['id'], 'environment': environment, 'source_ids': sorted(source_ids),
            'phase': phase, 'binding_ids': [str(binding.pk) for binding in bindings], 'writes': False,
            'body_takeovers': sum(len(row.get('body_takeover', [])) for row in rows)}


def _takeover(rows, *, mutate=True):
    seen = set()
    for row in rows:
        for takeover in row.get('body_takeover', []):
            news_id = takeover['news_id']
            _require(news_id not in seen, 'duplicate_body_takeover')
            seen.add(news_id)
            news = News.objects.get(pk=news_id)
            _require(news.url == takeover.get('expected_url'), 'article_identity_changed')
            version = takeover['expected_body_owner_version']
            old_source = takeover.get('expected_owner_source_id')
            old_binding = uuid.UUID(takeover['expected_owner_binding_id']) if takeover.get('expected_owner_binding_id') else None
            _require((old_source is None) != (old_binding is None), 'explicit_old_body_owner_required')
            if old_source is not None:
                _require(old_source in {source['source_id'] for source in rows}, 'body_owner_outside_switch_group')
            if row['target_owner'] == 'miniflux':
                new_binding = uuid.UUID(takeover['target_binding_id'])
                _require(new_binding in _binding_ids(row), 'body_target_binding_not_in_source')
                new_source = None
            elif row['target_owner'] == 'legacy':
                new_binding, new_source = None, row['source_id']
            else:
                raise MigrationBlocked('paused_source_cannot_take_over_body')
            current = (news.body_owner_source_id, news.body_owner_binding_id, news.body_owner_version)
            if current == (new_source, new_binding, version + 1):
                continue  # resume after a successful takeover and later engine failure
            _require(current == (old_source, old_binding, version), 'body_owner_version_changed')
            if mutate:
                News.objects.filter(pk=news.pk, body_owner_version=version).update(body_owner_source_id=new_source,
                    body_owner_binding_id=new_binding, body_owner_version=F('body_owner_version') + 1)


def _check_collection_policy(rows):
    for row in rows:
        if row['target_owner'] != 'miniflux':
            continue
        publication = SourcePublication.objects.select_related('source').get(source_id=row['source_id'])
        config = SourceConfig.objects.filter(source_id=row['source_id']).first()
        policy = policy_for_key(config.source_key) if config else policy_for_name(publication.source.name)
        _require(not policy or not policy.unsupported_reason, 'source_collection_not_permitted')
        _require(not policy or not policy.keyword_filter, 'association_filter_requires_supported_validator')
        for binding in FeedBinding.objects.filter(pk__in=_binding_ids(row)):
            link = SourceFeedLink.objects.filter(source_id=row['source_id'], binding=binding).first()
            _require(link is None or link.association_policy == {'version': 1, 'mode': 'all'}, 'association_filter_requires_supported_validator')
            if binding.desired_mode == 'full_content':
                _require(publication.reading_policy in {'standard', 'official_html'} and
                    (not policy or (policy.html_allowed and policy.reading_policy in {'standard', 'official_html'})),
                    'full_content_policy_not_permitted')


def _prepare_bindings(manifest, rows):
    marker = 'rss_migration:' + manifest['id']
    bindings = []
    for pk in _affected_binding_ids(rows):
        binding = FeedBinding.objects.get(pk=pk)
        target_enabled = (any(row['target_owner'] == 'miniflux' and pk in _binding_ids(row) for row in rows)
            or SourceFeedLink.objects.filter(binding=binding, editorial_pin=True, source__publication__owner='miniflux').exists()
            or SourceFeedLink.objects.filter(binding=binding, enabled=True, source__publication__owner='miniflux',
                source__channel_subscriptions__isnull=False).exists())
        if binding.last_error != marker:
            FeedBinding.objects.filter(pk=pk).update(desired_enabled=target_enabled, policy_version=F('policy_version') + 1,
                connection_state='paused', last_error=marker)
            binding.refresh_from_db()
        else:
            _require(binding.desired_enabled == target_enabled, 'shared_references_changed')
        bindings.append(binding)
    return bindings


def verify(manifest, *, source_ids, environment):
    result = plan(manifest, source_ids=source_ids, environment=environment)
    rows, _ = _rows(manifest, source_ids)
    valid = result['phase'] == 'complete'
    for row in rows:
        for takeover in row.get('body_takeover', []):
            news = News.objects.get(pk=takeover['news_id'])
            target_binding = uuid.UUID(takeover['target_binding_id']) if row['target_owner'] == 'miniflux' else None
            target_source = row['source_id'] if row['target_owner'] == 'legacy' else None
            valid &= ((news.body_owner_source_id, news.body_owner_binding_id, news.body_owner_version, news.url) ==
                      (target_source, target_binding, takeover['expected_body_owner_version'] + 1, takeover['expected_url']))
        for pk in _binding_ids(row):
            link = SourceFeedLink.objects.filter(source_id=row['source_id'], binding_id=pk).first()
            valid &= link is not None and link.enabled == (row['target_owner'] == 'miniflux')
    for binding in FeedBinding.objects.filter(pk__in=result['binding_ids']):
        valid &= binding.applied_policy_version == binding.policy_version
        valid &= binding.connection_state == ('ready' if binding.desired_enabled else 'paused')
    return {**result, 'verified': bool(valid)}


@contextmanager
def _command_lock():
    name = str(connection.settings_dict['NAME'])
    # Only a local serialization lock; not a deployment approval or DB backup.
    directory = Path('/tmp') if name.startswith('file:memorydb_') else Path(name).resolve().parent
    path = directory / ('.rss-migration-' + hashlib.sha256(name.encode()).hexdigest()[:16] + '.lock')
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MigrationBlocked('migration_already_running') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def apply(manifest, *, source_ids, environment, adapter, execute=False):
    result = plan(manifest, source_ids=source_ids, environment=environment)
    if not execute:
        return {**result, 'dry_run': True}
    if environment == 'production':
        _production_gate(manifest, source_ids)
    _require(str(adapter.config.engine_instance_uuid) == manifest['target']['engine_instance_uuid']
        and adapter.config.account_id == manifest['target']['account_id']
        and adapter.config.base_url == manifest['target']['engine_base_url'], 'adapter_identity_mismatch')
    with _command_lock():
        rows, indexed = _rows(manifest, source_ids)
        if _check_phase(manifest, rows) == 'complete':
            return verify(manifest, source_ids=source_ids, environment=environment)
        marker = 'rss_migration:' + manifest['id']
        with transaction.atomic():
            SourcePublication.objects.filter(source_id__in=source_ids).update(epoch=F('epoch'))
            _shared_group_check(rows, indexed)
            phase = _check_phase(manifest, rows)
            _require(not _active_operations(result['binding_ids']), 'binding_operations_not_drained')
            if phase == 'initial':
                SourcePublication.objects.filter(source_id__in=source_ids).update(owner='paused', epoch=F('epoch') + 1, pause_reason=marker)
                SourceFeedLink.objects.filter(source_id__in=source_ids).update(enabled=False)
                for row in rows:
                    for pk in _binding_ids(row):
                        SourceFeedLink.objects.get_or_create(source_id=row['source_id'], binding_id=pk,
                            defaults={'enabled': False, 'association_policy': row.get('association_policy', {'version': 1, 'mode': 'all'})})
        try:
            _drained(manifest)
            with transaction.atomic():
                SourcePublication.objects.filter(source_id__in=source_ids).update(epoch=F('epoch'))
                _require(_check_phase(manifest, rows) == 'paused', 'migration_phase_changed')
                _shared_group_check(rows, indexed)
                _check_collection_policy(rows)
                _require(not _active_operations(result['binding_ids']), 'binding_operations_not_drained')
                _takeover(rows)
                bindings = _prepare_bindings(manifest, rows)
            receipts = []
            for binding in bindings:
                receipt = adapter.update_feed_policy(PolicyBinding(str(binding.engine_instance_uuid), binding.account_id,
                    binding.engine_feed_id, binding.policy_version, binding.desired_mode, binding.desired_enabled), binding.policy_version)
                receipts.append((binding, receipt))
            with transaction.atomic():
                SourcePublication.objects.filter(source_id__in=source_ids).update(epoch=F('epoch'))
                _require(_check_phase(manifest, rows) == 'paused', 'migration_phase_changed')
                _shared_group_check(rows, indexed)
                _check_collection_policy(rows)
                _require(not _active_operations(result['binding_ids']), 'binding_operations_not_drained')
                _drained(manifest)
                for binding, receipt in receipts:
                    feed = receipt.feed
                    _require((str(feed.engine_instance_uuid), feed.account_id, feed.id, canonical_feed(feed.feed_url), feed.disabled, feed.crawler,
                              receipt.applied_policy_version) == (str(binding.engine_instance_uuid), binding.account_id, binding.engine_feed_id,
                              binding.canonical_feed_url, not binding.desired_enabled, binding.desired_mode == 'full_content', binding.policy_version),
                             'engine_policy_unconfirmed')
                    saved = FeedBinding.objects.filter(pk=binding.pk, policy_version=binding.policy_version,
                        desired_enabled=binding.desired_enabled, last_error=marker).update(applied_policy_version=binding.policy_version,
                            connection_state='ready' if binding.desired_enabled else 'paused', last_error='')
                    _require(saved == 1, 'binding_policy_changed_during_confirmation')
                _takeover(rows)  # Recheck every explicit owner after engine I/O.
                for row in rows:
                    SourcePublication.objects.filter(source_id=row['source_id']).update(owner=row['target_owner'], epoch=F('epoch') + 1,
                        pause_reason='unsupported' if row['target_owner'] == 'paused' else '')
                    SourceFeedLink.objects.filter(source_id=row['source_id'], binding_id__in=_binding_ids(row)).update(enabled=row['target_owner'] == 'miniflux')
            return {**verify(manifest, source_ids=source_ids, environment=environment), 'writes': True}
        except (MigrationBlocked, EngineError) as error:
            return {**result, 'phase': 'paused', 'writes': True, 'verified': False,
                    'reason': str(error) if isinstance(error, MigrationBlocked) else error.code}
