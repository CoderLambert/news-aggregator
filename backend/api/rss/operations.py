"""Durable, fixed engine intents. Callers own HTTP authorization and quotas.

No network here. T19 may compose these functions with subscription writes in one
short transaction; acquire the binding before reading/modifying other rows on
SQLite. Per-actor operation views never double as a physical-feed ownership grant.
"""
from functools import wraps
from hashlib import sha256
import json
import re
import time
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID

from django.db import OperationalError, connection, transaction
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db.models import F
from django.utils import timezone

from api.models import ChannelSubscription
from api.rss.engine import EngineError, MAX_ID, _url
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation, SourceFeedLink, SourcePublication

KINDS = {'register', 'set_enabled', 'update_feed_policy', 'discover', 'refresh_feed', 'refetch_entry'}
PENDING = ('pending', 'retry_wait')
BODY_POLICIES = {'standard', 'public_rss', 'public_feed', 'official_html', 'regulatory_data'}
SYNC_RESULTS = {'accepted', 'unchanged', 'quarantined', 'stale', 'rejected', 'conflict'}


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


def canonicalize_feed_url(value, *, resolve_rsshub=True):
    if resolve_rsshub:
        from api.rss.rsshub import selection
        resolved=selection(value)
        if resolved is not None:
            # Namespace parameters may legitimately contain opaque IDs. Generic
            # RSSHub has its own structure/credential gate and fixed origin.
            try: return _url(resolved.url)
            except EngineError: raise OperationError("invalid_public_url") from None
    try:
        normalized = _url(value)  # Same identity as engine FeedDTOs; DNS/redirect safety remains engine/deployment.
    except EngineError:
        raise OperationError('invalid_public_url') from None
    parts = urlsplit(normalized)
    sensitive = {'token', 'access_token', 'api_key', 'apikey', 'password', 'secret',
                 'auth', 'authorization', 'cookie', 'signature', 'access-token', 'api-key',
                 'key', 'k', 'sig', 'jwt', 'credential', 'access_key', 'feedkey'}
    opaque = re.compile(r'(?i)^(?:[0-9a-f]{32,}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[a-z0-9_]{32,})$')
    token_parts = [*unquote(parts.path).split('/'), *(value for _, value in parse_qsl(parts.query))]
    if (any(opaque.fullmatch(value) and any(char.isdigit() for char in value) for value in token_parts)
            or any(key.lower() in sensitive or re.search(r'token|secret|password|api.?key|cookie|signature|(?:^|[_-])auth(?:entication|orization)?(?:$|[_-])', key, re.I)
            for key, _ in parse_qsl(parts.query, keep_blank_values=True))
            or re.search(r'/(?:private|tokens?|secrets?|auth)/', unquote(parts.path), re.I)):
        raise OperationError('credential_feed_not_supported')
    return normalized


def rsshub_fields(url):
    from api.rss.rsshub import selection
    chosen=selection(url)
    if chosen is None: return {}
    from datetime import timedelta
    return {'rsshub_alias':chosen.alias,'rsshub_gateway_version':chosen.version,
        'published_since':timezone.now().date()-timedelta(days=7)}


@sqlite_retry
def get_or_create_binding(engine_instance_uuid, account_id, feed_url, desired_mode='feed'):
    if desired_mode not in {'feed', 'full_content'} or type(account_id) is not int or not 0 < account_id <= MAX_ID:
        raise OperationError('invalid_binding')
    identity = dict(engine_instance_uuid=UUID(str(engine_instance_uuid)), account_id=account_id,
                    canonical_feed_url=canonicalize_feed_url(feed_url))
    with transaction.atomic():
        # Write first: SQLite ignores select_for_update and read→write upgrades race.
        FeedBinding.objects.filter(**identity).update(updated_at=F('updated_at'))
        # A separately proven redirect is an alias of the existing physical
        # binding, never a new subscription/visibility grant.
        aliases = FeedBinding.objects.filter(engine_instance_uuid=identity['engine_instance_uuid'],
            account_id=account_id, effective_feed_url=identity['canonical_feed_url'])
        alias = aliases.first()
        if alias:
            if aliases.exclude(pk=alias.pk).exists() or FeedBinding.objects.filter(**identity).exclude(pk=alias.pk).exists():
                raise OperationError('policy_conflict')
            binding = alias
        else:
            binding, _ = FeedBinding.objects.get_or_create(**identity, defaults={'desired_mode': desired_mode, **rsshub_fields(identity['canonical_feed_url'])})
        if binding.desired_mode != desired_mode:
            raise OperationError('policy_conflict')
        return binding


def effective_references(binding_id):
    # Prestaged legacy/paused sources never activate the new collector, even
    # when pinned. Publication visibility is independent of collection owner.
    links = SourceFeedLink.objects.filter(binding_id=binding_id, source__publication__owner='miniflux')
    if links.filter(editorial_pin=True).exists():
        return True
    if links.filter(enabled=True, source__channel_subscriptions__isnull=False).exists():
        return True
    from api.rss.review_models import PublicFeedCandidate
    from api.rss.review_permissions import assert_review_authority
    from rest_framework.exceptions import PermissionDenied
    candidate = PublicFeedCandidate.objects.filter(binding_id=binding_id,state='approved').select_related('decision__actor').first()
    if candidate and candidate.decision_id and candidate.decision.candidate_version == candidate.version:
        try:
            assert_review_authority(candidate.decision.actor,candidate.decision.authority)
            return True
        except PermissionDenied:
            pass
    return FeedOperation.objects.filter(binding_id=binding_id, actor__is_active=True,
        safe_input__subscription_request__isnull=False,
        state__in=['pending', 'running', 'retry_wait', 'unknown', 'manual_blocked']).exists()


def refetch_fence(entry, source_id, actor_id):
    from api.models import News
    binding = FeedBinding.objects.get(pk=entry.binding_id)
    try:
        publication = SourcePublication.objects.get(source_id=source_id)
        news = News.objects.get(pk=entry.news_id)
    except (SourcePublication.DoesNotExist, News.DoesNotExist):
        raise OperationError('refetch_not_allowed') from None
    link = SourceFeedLink.objects.filter(binding=binding, source_id=source_id, enabled=True).exists()
    authorized = actor_id is None or (
        get_user_model().objects.filter(pk=actor_id, is_active=True).exists() and (
            publication.publication == 'public' or ChannelSubscription.objects.filter(
                user_id=actor_id, source_id=source_id).exists()))
    if (not link or not authorized or publication.owner != 'miniflux'
            or publication.reading_policy not in BODY_POLICIES
            or binding.desired_mode != 'full_content' or not binding.desired_enabled
            or binding.connection_state != 'ready' or binding.applied_policy_version != binding.policy_version
            or news.body_owner_binding_id != binding.id or news.url != entry.source_url):
        raise OperationError('refetch_not_allowed')
    from api.rss.feed_policy import assert_article_fetch_allowed, assert_binding_policy
    assert_binding_policy(binding)
    assert_article_fetch_allowed(news.url)
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
            safe_input=inputs, intent_version=version, request_hash=request_hash, execution_phase='not_sent')


def get_operation_for_actor(actor, operation_id):
    if actor is None or not actor.pk or not actor.is_active:
        raise OperationError('not_found')
    try:
        operation = FeedOperation.objects.get(pk=operation_id, actor=actor)
    except (FeedOperation.DoesNotExist, ValueError, ValidationError):
        raise OperationError('not_found') from None
    result = operation.safe_result
    public = {key: result[key] for key in ('retryable', 'outcome_unknown', 'cancelled', 'connected',
        'pending_sync', 'refresh_requested', 'not_created') if type(result.get(key)) is bool}
    if isinstance(result.get('code'), str) and re.fullmatch('[a-z0-9_]{1,64}', result['code']):
        public['code'] = result['code']
    if result.get('sync_status') in SYNC_RESULTS:
        public['sync_status'] = result['sync_status']
    for key in ('feed_id', 'entry_id', 'revision'):
        value = result.get(key)
        if isinstance(value, str) and value.isdecimal() and (0 if key == 'revision' else 1) <= int(value) <= MAX_ID:
            public[key] = value
    if operation.kind == 'discover' and isinstance(result.get('candidates'), list):
        candidates = []
        for candidate in result['candidates'][:20]:
            try:
                url = canonicalize_feed_url(candidate['url'])
                title = candidate.get('title', '')
                if not isinstance(title, str) or '<' in title or '>' in title:
                    title = ''
                candidates.append({'url': url, 'title': title[:255]})
            except (OperationError, KeyError, TypeError):
                continue
        public['candidates'] = candidates
    return {'id': str(operation.pk), 'kind': operation.kind,
            'state': 'cancelled' if operation.safe_result.get('cancelled') else operation.state,
            'result': public, 'attempts': operation.attempts}


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
        # A follower owns no network request; cancellation never revokes the
        # system physical lease or creates an unknown remote result.
        uncertain = not operation.shared_operation_id and (operation.state in {'running', 'unknown'} or operation.safe_result.get('outcome_unknown', False))
        scope.update(state='cancelled', lease_epoch=F('lease_epoch') + 1, lease_token=None,
            lease_until=None, next_attempt=timezone.now() if uncertain else None,
            safe_result={**operation.safe_result, 'cancelled': True, 'outcome_unknown': bool(uncertain)})
        updated = scope.get()
        if updated.shared_operation_id and not effective_references(updated.binding_id):
            root = FeedOperation.objects.get(pk=updated.shared_operation_id)
            # Only a positively never-dispatched root can be retired here.
            FeedOperation.objects.filter(pk=root.pk, state__in=['pending', 'retry_wait'],
                execution_phase='not_sent').update(state='cancelled', resolved_at=timezone.now(),
                    resolution={'reason': 'no_subscription_intents'}, lease_epoch=F('lease_epoch') + 1,
                    lease_token=None, lease_until=None, next_attempt=None)
        if 'subscription_request' in updated.safe_input and updated.binding_id:
            reconcile_binding(updated.binding_id)
        return updated


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
        # An administrative recovery owns this policy version until the next
        # explicit submission. Never create a parallel convergence/retry loop.
        if FeedOperation.objects.filter(binding=binding, intent_version=binding.policy_version,
                safe_input__admin_recovery__isnull=False, resolved_at__isnull=True).exclude(state='succeeded').exists():
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
        from api.rss.feed_policy import assert_binding_policy
        current = FeedBinding.objects.get(pk=binding_id)
        # No privilege, including admin, overrides publisher/source restrictions.
        assert_binding_policy(current, desired_mode=desired_mode)
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


@sqlite_retry
def acknowledge_refetch(operation_id, request_hash, *, sync_status='accepted', reason='', revision=None):
    """T09 calls after T07 CAS, ideally in the same short transaction as that CAS."""
    if sync_status not in SYNC_RESULTS or (reason and not re.fullmatch('[a-z0-9_]{1,64}', reason)):
        raise OperationError('invalid_sync_result')
    if revision is not None and (type(revision) is not int or not 0 <= revision <= MAX_ID):
        raise OperationError('invalid_sync_result')
    with transaction.atomic():
        query = FeedOperation.objects.filter(pk=operation_id, request_hash=request_hash,
            kind='refetch_entry', state='succeeded', safe_result__pending_sync=True)
        if not query.update(updated_at=timezone.now()):
            return False
        operation = query.get()
        result = {**operation.safe_result, 'pending_sync': False, 'sync_status': sync_status}
        if reason:
            result['code'] = reason
        if revision is not None:
            result['revision'] = str(revision)
        query.update(safe_result=result)
        return True


def unresolved_control_operations(binding_id):
    from django.db.models import Q
    return FeedOperation.objects.filter(binding_id=binding_id, shared_operation__isnull=True, kind__in=['register', 'set_enabled', 'update_feed_policy'],
        resolved_at__isnull=True).filter(Q(state__in=['unknown', 'manual_blocked']) | Q(safe_result__outcome_unknown=True)).exclude(state='succeeded')
