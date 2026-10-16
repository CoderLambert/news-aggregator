"""Durable, fixed engine intents. Callers own HTTP authorization and quotas.

No network here. T19 may compose these functions with subscription writes in one
short transaction; acquire the binding before reading/modifying other rows on
SQLite. Per-actor operation views never double as a physical-feed ownership grant.
"""
from functools import wraps
from hashlib import sha256
import json
import time
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import UUID

from django.db import OperationalError, connection, transaction
from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils import timezone

from api.models import ChannelSubscription
from api.rss.engine import EngineError, MAX_ID, _url
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation, SourceFeedLink, SourcePublication

KINDS = {'register', 'set_enabled', 'update_feed_policy', 'discover', 'refresh_feed', 'refetch_entry'}
PENDING = ('pending', 'retry_wait')


class OperationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def sqlite_retry(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        outer = connection.in_atomic_block
        for attempt in range(20):
            try:
                return fn(*args, **kwargs)
            except OperationalError as exc:
                if outer or connection.vendor != 'sqlite' or 'locked' not in str(exc).lower() or attempt == 19:
                    raise
                time.sleep(0.01 * min(attempt + 1, 10))
    return wrapped


def canonicalize_feed_url(value):
    try:
        _url(value)  # public HTTPS syntax; DNS/redirect safety remains engine/deployment.
    except EngineError:
        raise OperationError('invalid_public_url') from None
    parts = urlsplit(value)
    sensitive = {'token', 'access_token', 'api_key', 'apikey', 'password', 'secret',
                 'auth', 'authorization', 'cookie', 'signature', 'access-token', 'api-key'}
    if any(key.lower() in sensitive for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise OperationError('credential_feed_not_supported')
    try:
        host = parts.hostname.rstrip('.').encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise OperationError('invalid_public_url') from None
    if ':' in host:
        host = '[' + host + ']'
    netloc = host + (f':{parts.port}' if parts.port and parts.port != 443 else '')
    return urlunsplit(('https', netloc, parts.path, parts.query, ''))


@sqlite_retry
def get_or_create_binding(engine_instance_uuid, account_id, feed_url, desired_mode='feed'):
    if desired_mode not in {'feed', 'full_content'} or type(account_id) is not int or not 0 < account_id <= MAX_ID:
        raise OperationError('invalid_binding')
    identity = dict(engine_instance_uuid=UUID(str(engine_instance_uuid)), account_id=account_id,
                    canonical_feed_url=canonicalize_feed_url(feed_url))
    with transaction.atomic():
        # Write first: SQLite ignores select_for_update and read→write upgrades race.
        FeedBinding.objects.filter(**identity).update(updated_at=F('updated_at'))
        binding, _ = FeedBinding.objects.get_or_create(**identity, defaults={'desired_mode': desired_mode})
        if binding.desired_mode != desired_mode:
            raise OperationError('policy_conflict')
        return binding


def effective_references(binding_id):
    links = SourceFeedLink.objects.filter(binding_id=binding_id)
    if links.filter(editorial_pin=True).exists():
        return True
    return links.filter(enabled=True, source__publication__owner='miniflux',
                        source__channel_subscriptions__isnull=False).exists()


def refetch_fence(entry, source_id, actor_id):
    from api.models import News
    binding = FeedBinding.objects.get(pk=entry.binding_id)
    try:
        publication = SourcePublication.objects.get(source_id=source_id)
        news = News.objects.get(pk=entry.news_id)
    except (SourcePublication.DoesNotExist, News.DoesNotExist):
        raise OperationError('refetch_not_allowed') from None
    link = SourceFeedLink.objects.filter(binding=binding, source_id=source_id, enabled=True).exists()
    subscribed = actor_id is None or ChannelSubscription.objects.filter(user_id=actor_id, source_id=source_id).exists()
    if (not link or not subscribed or publication.owner != 'miniflux'
            or publication.reading_policy in {'summary_only', 'rss_summary_only', 'external_link', 'metadata_only', 'unsupported'}
            or binding.desired_mode != 'full_content' or not binding.desired_enabled
            or binding.connection_state != 'ready' or binding.applied_policy_version != binding.policy_version
            or news.body_owner_binding_id != binding.id or news.url != entry.source_url):
        raise OperationError('refetch_not_allowed')
    return {'source_id': source_id, 'source_epoch': publication.epoch,
            'source_policy_version': publication.policy_version,
            'body_owner_version': news.body_owner_version,
            'news_id': news.pk, 'news_url': news.url, 'expected_revision': news.full_content_revision}


@sqlite_retry
def enqueue_operation(kind, *, actor, dedupe_key, binding=None, entry=None, source_id=None, url=None):
    if kind not in KINDS or not isinstance(dedupe_key, str) or not 1 <= len(dedupe_key) <= 128:
        raise OperationError('invalid_intent')
    if actor is not None and (not actor.pk or not actor.is_active):
        raise OperationError('invalid_actor')
    if kind == 'discover':
        if binding is not None or entry is not None or source_id is not None:
            raise OperationError('invalid_intent')
        inputs = {'url': canonicalize_feed_url(url)}
    else:
        if binding is None or url is not None:
            raise OperationError('invalid_intent')
        inputs = {}
        if kind == 'refetch_entry':
            if entry is None or entry.binding_id != binding.pk or source_id is None:
                raise OperationError('invalid_intent')
        elif entry is not None or source_id is not None:
            raise OperationError('invalid_intent')
    request = {'kind': kind, 'binding': str(binding.pk) if binding else None,
               'entry': str(entry.pk) if entry else None, 'source_id': source_id, **inputs}
    request_hash = sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with transaction.atomic():
        scope = dict(actor=actor, dedupe_key=dedupe_key)
        FeedOperation.objects.filter(**scope).update(updated_at=F('updated_at'))
        old = FeedOperation.objects.filter(**scope).first()
        if old:
            if old.request_hash != request_hash:
                raise OperationError('idempotency_conflict')
            return old
        version = 1
        if binding:
            binding = FeedBinding.objects.get(pk=binding.pk)
            version = binding.policy_version
        if kind == 'refetch_entry':
            entry = EngineEntryMap.objects.get(pk=entry.pk)
            inputs = {'fence': refetch_fence(entry, source_id, actor.pk if actor else None)}
        return FeedOperation.objects.create(**scope, kind=kind, binding=binding, entry=entry,
            safe_input=inputs, intent_version=version, request_hash=request_hash)


def get_operation_for_actor(actor, operation_id):
    if actor is None or not actor.pk or not actor.is_active:
        raise OperationError('not_found')
    try:
        operation = FeedOperation.objects.get(pk=operation_id, actor=actor)
    except (FeedOperation.DoesNotExist, ValueError, ValidationError):
        raise OperationError('not_found') from None
    return {'id': str(operation.pk), 'kind': operation.kind,
            'state': 'cancelled' if operation.safe_result.get('cancelled') else operation.state,
            'result': operation.safe_result, 'attempts': operation.attempts}


@sqlite_retry
def cancel_operation(actor, operation_id):
    if actor is None or not actor.pk or not actor.is_active:
        raise OperationError('not_found')
    with transaction.atomic():
        scope = FeedOperation.objects.filter(pk=operation_id, actor=actor)
        scope.update(updated_at=F('updated_at'))
        try:
            operation = scope.get()
        except FeedOperation.DoesNotExist:
            raise OperationError('not_found') from None
        if operation.state in {'succeeded', 'failed', 'cancelled'}:
            return operation
        uncertain = operation.state in {'running', 'unknown'} or operation.safe_result.get('outcome_unknown', False)
        scope.update(state='cancelled', lease_epoch=F('lease_epoch') + 1, lease_token=None,
            lease_until=None, next_attempt=timezone.now() if uncertain else None,
            safe_result={'cancelled': True, 'outcome_unknown': bool(uncertain)})
        return scope.get()


def _cancel_old_refetches(binding):
    FeedOperation.objects.filter(binding=binding, kind='refetch_entry', state__in=PENDING).exclude(
        intent_version=binding.policy_version).update(state='cancelled', lease_epoch=F('lease_epoch') + 1,
            safe_result={'code': 'stale_policy'}, updated_at=timezone.now())


@sqlite_retry
def reconcile_binding(binding_id):
    """Call after relation changes, within the same short transaction when possible."""
    with transaction.atomic():
        query = FeedBinding.objects.filter(pk=binding_id)
        query.update(updated_at=F('updated_at'))
        binding = query.get()
        enabled = effective_references(binding_id)
        if enabled != binding.desired_enabled:
            query.update(desired_enabled=enabled, policy_version=F('policy_version') + 1,
                         connection_state='paused', updated_at=timezone.now())
            binding = query.get()
            _cancel_old_refetches(binding)
        if binding.applied_policy_version == binding.policy_version and binding.connection_state == ('ready' if enabled else 'paused'):
            return None
        return enqueue_operation('register' if binding.engine_feed_id is None and enabled else 'set_enabled',
            actor=None, binding=binding, dedupe_key=f'converge:{binding.pk}:{binding.policy_version}')


@sqlite_retry
def change_policy(binding_id, *, expected_policy_version, desired_mode, actor=None, dedupe_key=None):
    if desired_mode not in {'feed', 'full_content'}:
        raise OperationError('invalid_policy')
    with transaction.atomic():
        FeedBinding.objects.filter(pk=binding_id).update(updated_at=F('updated_at'))
        key = dedupe_key or f'policy:{binding_id}:{expected_policy_version + 1}'
        requested = {'desired_mode': desired_mode, 'expected_policy_version': expected_policy_version}
        fingerprint = sha256(json.dumps({'binding': str(binding_id), **requested}, sort_keys=True).encode()).hexdigest()
        old = FeedOperation.objects.filter(actor=actor, dedupe_key=key).first()
        if old:
            if old.request_hash != fingerprint:
                raise OperationError('idempotency_conflict')
            return old
        query = FeedBinding.objects.filter(pk=binding_id, policy_version=expected_policy_version)
        if not query.update(desired_mode=desired_mode, policy_version=F('policy_version') + 1,
                            connection_state='paused', updated_at=timezone.now()):
            raise OperationError('stale_policy')
        binding = FeedBinding.objects.get(pk=binding_id)
        _cancel_old_refetches(binding)
        operation = enqueue_operation('update_feed_policy', actor=actor, binding=binding, dedupe_key=key)
        FeedOperation.objects.filter(pk=operation.pk).update(request_hash=fingerprint, safe_input={'requested_policy': requested})
        operation.refresh_from_db()
        return operation


def refetch_handoffs(limit=100):
    """T09 re-GETs these IDs and sends captured safe_input.fence through T07 CAS."""
    return FeedOperation.objects.filter(kind='refetch_entry', state='succeeded',
        safe_result__pending_sync=True).select_related('entry', 'binding').order_by('created_at')[:limit]


def acknowledge_refetch(operation_id, request_hash):
    return FeedOperation.objects.filter(pk=operation_id, request_hash=request_hash,
        kind='refetch_entry', state='succeeded', safe_result__pending_sync=True).update(
            safe_result={'pending_sync': False}, updated_at=timezone.now()) == 1
