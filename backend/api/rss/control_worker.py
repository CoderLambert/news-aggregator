"""One control slot plus one reserved short-read slot, no network DB transactions.

Lease expiry/future timeout never frees a running slot or proves remote cancellation.
Unknown create/refetch operations only reconcile; absence never authorizes reissue.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
import re
import time
import uuid

from django.db import connection, transaction
from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from api.rss.engine import EngineAdapter, EngineError, PolicyBinding
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation
from api.rss.operations import (OperationError, effective_references, reconcile_binding,
                               refetch_fence, sqlite_retry)


@dataclass(frozen=True)
class Claim:
    operation_id: object
    token: object
    epoch: int
    reconcile: bool


@dataclass(frozen=True)
class Request:
    claim: Claim
    kind: str
    binding_id: object
    policy: object
    url: str
    engine_entry_id: int | None
    inputs: dict
    cancelled: bool
    applied: bool
    entry_url_block_rules: str = ''


@dataclass
class Outcome:
    result: dict | None = None
    feed: object = None
    error: object = None


class ControlWorker:
    def __init__(self, config, *, adapter_factory=None, lease_seconds=90, max_attempts=5):
        self.config = config
        self.adapter_factory = adapter_factory
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self._control = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rss-control')
        self._reads = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rss-short-read')
        self._future = self._request = self._read_future = None
        self._started = None

    def _owned(self, claim, now):
        return FeedOperation.objects.filter(pk=claim.operation_id, state='running',
            lease_token=claim.token, lease_epoch=claim.epoch, lease_until__gt=now)

    @sqlite_retry
    def claim_next(self, now=None):
        now = now or timezone.now()
        due = Q(next_attempt__isnull=True) | Q(next_attempt__lte=now)
        ready = Q(state__in=['pending', 'retry_wait', 'unknown']) & due
        ready |= Q(state='cancelled', safe_result__outcome_unknown=True) & due
        ready |= Q(state='running', lease_until__lte=now)
        scope = Q(binding__isnull=True) | Q(binding__engine_instance_uuid=self.config.engine_instance_uuid,
                                           binding__account_id=self.config.account_id)
        candidates = list(FeedOperation.objects.filter(ready & scope).annotate(priority=Case(
            When(state='running', then=Value(0)), When(state__in=['unknown', 'cancelled'], then=Value(1)),
            default=Value(2))).order_by('priority', 'created_at')[:20])
        for old in candidates:
            with transaction.atomic():
                token = uuid.uuid4()
                query = FeedOperation.objects.filter(pk=old.pk, state=old.state, lease_epoch=old.lease_epoch)
                if not query.update(state='running', lease_token=token, lease_epoch=F('lease_epoch') + 1,
                    lease_until=now + timedelta(seconds=self.lease_seconds), attempts=F('attempts') + 1,
                    updated_at=now):
                    continue
                # The UPDATE acquired SQLite's writer lock before any read below.
                if old.binding_id and FeedOperation.objects.filter(binding_id=old.binding_id,
                        state='running').exclude(pk=old.pk).exists():
                    transaction.set_rollback(True)
                    continue
                return Claim(old.pk, token, old.lease_epoch + 1,
                             old.state in {'running', 'unknown', 'cancelled'})
        return None

    def prepare(self, claim):
        if connection.in_atomic_block:
            raise OperationError('worker_inside_transaction')
        operation = self._owned(claim, timezone.now()).select_related('binding', 'entry').first()
        if not operation:
            return None
        binding = operation.binding
        cancelled = bool(operation.safe_result.get('cancelled'))
        if binding:
            if effective_references(binding.pk) != binding.desired_enabled:
                reconcile_binding(binding.pk)
                binding.refresh_from_db()
            # A different unsettled mutation fences new physical writes.
            unsettled = FeedOperation.objects.filter(binding=binding).exclude(pk=operation.pk).filter(
                Q(state='unknown') | Q(safe_result__outcome_unknown=True,
                    state__in=['manual_blocked', 'cancelled'])).filter(
                        kind__in=['register', 'set_enabled', 'update_feed_policy'])
            if unsettled.exists() and not claim.reconcile:
                raise EngineError('binding_outcome_unknown', retryable=True)
            if operation.intent_version != binding.policy_version:
                if (not claim.reconcile and 'subscription_request' in operation.safe_input
                        and operation.kind in {'register', 'set_enabled'}):
                    # A pending subscription has no mode override. Dispatch only
                    # the CURRENT approved policy, still under this owned lease.
                    self._owned(claim, timezone.now()).update(intent_version=binding.policy_version)
                elif claim.reconcile:
                    # Recovery is read-only except a located committed create can
                    # converge CURRENT policy. No old refetch is reissued/published.
                    self._owned(claim, timezone.now()).update(intent_version=binding.policy_version)
                else:
                    raise OperationError('stale_policy')
            if not claim.reconcile and operation.kind in {'refresh_feed', 'refetch_entry'} and (
                    not binding.desired_enabled or binding.connection_state != 'ready'
                    or binding.applied_policy_version != binding.policy_version):
                raise OperationError('binding_not_ready')
            if operation.kind == 'refetch_entry' and not claim.reconcile:
                current = refetch_fence(operation.entry, operation.safe_input['fence']['source_id'], operation.actor_id)
                if current != operation.safe_input['fence']:
                    raise OperationError('stale_fence')
            from api.rss.feed_policy import assert_binding_policy
            assert_binding_policy(binding, enabled=binding.desired_enabled)
            policy = PolicyBinding(str(binding.engine_instance_uuid), binding.account_id,
                binding.engine_feed_id, binding.policy_version, binding.desired_mode, binding.desired_enabled,
                published_since=binding.published_since.isoformat() if binding.published_since else None)
            applied = binding.applied_policy_version == binding.policy_version and binding.connection_state == (
                'ready' if binding.desired_enabled else 'paused')
        else:
            policy, applied = None, False
        from api.rss.feed_policy import required_entry_url_block_rules
        return Request(claim, operation.kind, binding.pk if binding else None, policy,
            binding.canonical_feed_url if binding else operation.safe_input['url'],
            operation.entry.engine_entry_id if operation.entry_id else None,
            operation.safe_input, cancelled, applied, required_entry_url_block_rules(include_database=True,
                include_html=bool(binding and binding.desired_mode == 'full_content')))

    def _dispatch(self, request):
        """Last main-thread ORM fence; executor receives immutable data only.

        No queue behind a busy control slot, no publisher request inside a DB
        transaction. After dispatch, a policy change cannot retract remote I/O.
        """
        if request.binding_id:
            from api.rss.feed_policy import assert_binding_policy
            binding = FeedBinding.objects.get(pk=request.binding_id)
            if (binding.policy_version != request.policy.policy_version
                    or binding.desired_mode != request.policy.desired_mode
                    or binding.desired_enabled != request.policy.desired_enabled
                    or binding.canonical_feed_url != request.url):
                raise OperationError('stale_policy')
            assert_binding_policy(binding, enabled=binding.desired_enabled)
            if request.kind == 'refetch_entry' and not request.claim.reconcile:
                operation = FeedOperation.objects.select_related('entry').get(pk=request.claim.operation_id)
                if refetch_fence(operation.entry, request.inputs['fence']['source_id'], operation.actor_id) != request.inputs['fence']:
                    raise OperationError('stale_fence')
        from api.rss.feed_policy import required_entry_url_block_rules
        return replace(request, entry_url_block_rules=required_entry_url_block_rules(include_database=True,
            include_html=bool(request.policy and request.policy.desired_mode == 'full_content')))

    def _dispatch_or_finish(self, request):
        try:
            return self._dispatch(request)
        except OperationError as error:
            if request.claim.reconcile:
                error = EngineError('stale_remote_outcome_unknown', unknown_result=True)
            self.complete(request, Outcome(error=error))
            return None

    def network(self, request):
        # Only plain immutable request data crosses into the network thread.
        adapter = self.adapter_factory() if self.adapter_factory else EngineAdapter(
            replace(self.config, server_entry_url_block_rules=request.entry_url_block_rules))
        try:
            if request.kind == 'discover':
                try:
                    rows = adapter.discover(request.url)
                except EngineError as error:
                    # Miniflux2.3.3 discovery uses404 only for zero candidates;
                    # actual finder errors/timeouts are500. Other actions retain404.
                    if error.code != 'not_found':
                        raise
                    rows = []
                from api.rss.operations import canonicalize_feed_url
                candidates = [{'url': canonicalize_feed_url(row['url']),
                    'title': row.get('title', '')[:255] if not any(c in row.get('title', '') for c in '<>') else ''}
                    for row in rows[:20]]
                return Outcome({'candidates': candidates})
            policy = request.policy
            if request.kind in {'register', 'set_enabled', 'update_feed_policy'}:
                if request.applied and not request.claim.reconcile:
                    return Outcome({'connected': bool(policy.engine_feed_id)})
                feed_id = policy.engine_feed_id
                if request.claim.reconcile:
                    if request.kind != 'register':
                        if feed_id:
                            adapter.get_feed(feed_id)
                        # FeedDTO exposes crawler/disabled but omits both
                        # blocklist_rules and keeplist_rules. Matching flags
                        # alone cannot prove this complete approved policy.
                        raise EngineError('policy_outcome_unproven', unknown_result=True)
                    matches = [f for f in adapter.list_feeds() if f.feed_url == request.url]
                    if len(matches) != 1:
                        raise EngineError('create_outcome_unproven', retryable=True, unknown_result=True)
                    feed_id = matches[0].id
                elif feed_id is None:
                    if not policy.desired_enabled:
                        return Outcome({'connected': False, 'not_created': True})
                    feed_id = adapter.create_feed(request.url, desired_mode=policy.desired_mode,
                                                  disabled=not policy.desired_enabled,
                        **({'published_since': policy.published_since} if policy.published_since else {})).id
                # Converge all approved fields together; never re-enable an old mode.
                if feed_id is None:
                    return Outcome({'connected': False, 'not_created': True})
                desired = PolicyBinding(policy.engine_instance_uuid, policy.account_id, feed_id,
                    policy.policy_version, policy.desired_mode, policy.desired_enabled,
                    published_since=policy.published_since)
                receipt = adapter.update_feed_policy(desired, desired.policy_version)
                feed = receipt.feed
                if (receipt.applied_policy_version != policy.policy_version
                        or str(feed.engine_instance_uuid) != policy.engine_instance_uuid
                        or feed.account_id != policy.account_id or feed.id != feed_id
                        or feed.feed_url != request.url or feed.disabled == policy.desired_enabled
                        or feed.crawler != (policy.desired_mode == 'full_content')):
                    raise EngineError('policy_unconfirmed', unknown_result=True)
                return Outcome({'connected': True, 'feed_id': str(feed.id)}, feed=feed)
            if request.kind == 'refresh_feed':
                if request.claim.reconcile:
                    adapter.get_feed(policy.engine_feed_id)
                    raise EngineError('refresh_outcome_unproven', unknown_result=True)
                adapter.refresh_feed(policy.engine_feed_id)
                return Outcome({'refresh_requested': True})
            if request.kind == 'refetch_entry':
                if request.claim.reconcile:
                    adapter.get_entry(request.engine_entry_id)
                    raise EngineError('refetch_outcome_unproven', unknown_result=True)
                # The publisher target may have changed remotely since enqueue.
                # GET is safe; never issue fetch-content for an unapproved URL.
                current = adapter.get_entry(request.engine_entry_id)
                from api.services.article_identity import normalize_article_url
                if (current.feed_id != policy.engine_feed_id or current.id != request.engine_entry_id
                        or str(current.engine_instance_uuid) != policy.engine_instance_uuid
                        or current.account_id != policy.account_id
                        or normalize_article_url(current.url) != request.inputs['fence']['news_url']):
                    raise OperationError('stale_fence')
                entry = adapter.refetch_entry(request.engine_entry_id)
                if (entry.feed_id != policy.engine_feed_id or entry.id != request.engine_entry_id
                        or str(entry.engine_instance_uuid) != policy.engine_instance_uuid
                        or entry.account_id != policy.account_id or entry.url != request.inputs['fence']['news_url']):
                    raise EngineError('identity_mismatch', unknown_result=True)
                # No HTML in operations, no News write. T09 re-GET + T07 fenced CAS.
                return Outcome({'entry_id': str(entry.id), 'pending_sync': True})
            raise OperationError('invalid_intent')
        except (EngineError, OperationError) as exc:
            return Outcome(error=exc)
        except Exception:
            return Outcome(error=EngineError('worker_internal'))
        finally:
            adapter.close()

    @sqlite_retry
    def complete(self, request, outcome):
        now = timezone.now()
        with transaction.atomic():
            query = self._owned(request.claim, now)
            if not query.update(updated_at=now):
                return False  # Old lease and revoked cancellation can never publish.
            operation = query.get()
            binding = FeedBinding.objects.get(pk=request.binding_id) if request.binding_id else None
            error = outcome.error
            if binding and effective_references(binding.pk) != binding.desired_enabled:
                reconcile_binding(binding.pk)
                binding.refresh_from_db()
            if binding and binding.policy_version != request.policy.policy_version:
                if request.kind == 'register' and outcome.feed is not None:
                    error = EngineError('stale_create_requires_reconciliation', retryable=True, unknown_result=True)
                else:
                    error = EngineError('stale_remote_outcome_unknown', unknown_result=True) if (
                        getattr(error, 'unknown_result', False)) else OperationError('stale_policy')
            if not error and request.kind == 'refetch_entry':
                try:
                    entry = EngineEntryMap.objects.get(pk=operation.entry_id)
                    if refetch_fence(entry, request.inputs['fence']['source_id'], operation.actor_id) != request.inputs['fence']:
                        raise OperationError('stale_fence')
                except OperationError as exc:
                    error = exc
            cancelled = request.cancelled
            if error:
                code = error.code if re.fullmatch('[a-z0-9_]{1,64}', str(error.code)) else 'upstream_error'
                unknown = bool(getattr(error, 'unknown_result', False))
                retryable = bool(getattr(error, 'retryable', False)) or unknown
                if isinstance(error, OperationError):
                    state, next_attempt = 'cancelled', None
                elif retryable and operation.attempts < self.max_attempts:
                    state = 'unknown' if unknown else 'retry_wait'
                    delay = max(min(2 ** (operation.attempts - 1), 60), getattr(error, 'retry_after', None) or 0)
                    next_attempt = now + timedelta(seconds=delay)
                else:
                    state, next_attempt = ('manual_blocked' if unknown else 'failed'), None
                result = {'code': code, 'retryable': retryable, 'outcome_unknown': unknown}
                if cancelled:
                    result['cancelled'] = True
                if binding and (unknown or state == 'failed'):
                    FeedBinding.objects.filter(pk=binding.pk).update(
                        connection_state='paused' if unknown else 'error', last_error=code)
            else:
                state, next_attempt = ('cancelled' if cancelled else 'succeeded'), None
                result = {**(outcome.result or {}), **({'cancelled': True} if cancelled else {})}
                if binding and request.kind in {'register', 'set_enabled', 'update_feed_policy'}:
                    fields = dict(applied_policy_version=binding.policy_version,
                        connection_state='ready' if binding.desired_enabled else 'paused', last_error='')
                    if outcome.feed:
                        fields['engine_feed_id'] = outcome.feed.id
                    FeedBinding.objects.filter(pk=binding.pk, policy_version=request.policy.policy_version).update(**fields)
            if state == 'succeeded' and binding and request.kind in {'register', 'set_enabled'}:
                from api.rss.subscriptions import complete_subscription
                complete_subscription(operation)
            query.update(state=state, safe_result=result, next_attempt=next_attempt,
                         lease_token=None, lease_until=None, updated_at=now)
            if binding:
                reconcile_binding(binding.pk)
            return True

    def _prepare_or_finish(self, claim):
        try:
            return self.prepare(claim)
        except (EngineError, OperationError) as error:
            if claim.reconcile and isinstance(error, OperationError):
                error = EngineError('stale_remote_outcome_unknown', unknown_result=True)
            # Still use the leased CAS, including a current binding policy snapshot.
            operation = self._owned(claim, timezone.now()).select_related('binding').first()
            if operation:
                binding = operation.binding
                policy = PolicyBinding(str(binding.engine_instance_uuid), binding.account_id,
                    binding.engine_feed_id, binding.policy_version, binding.desired_mode,
                    binding.desired_enabled) if binding else None
                request = Request(claim, operation.kind, operation.binding_id, policy, '', None,
                    operation.safe_input, bool(operation.safe_result.get('cancelled')), False)
                self.complete(request, Outcome(error=error))
            return None

    def run_once(self):
        if connection.in_atomic_block:
            raise OperationError('worker_inside_transaction')
        if self._future is not None:
            raise OperationError('control_slot_busy')
        claim = self.claim_next()
        if claim is None:
            return False
        request = self._prepare_or_finish(claim)
        request = self._dispatch_or_finish(request) if request else None
        if request:
            self.complete(request, self.network(request))
        return True

    def tick(self):
        """Main thread owns DB writes; executor owns network only, with no queue."""
        if connection.in_atomic_block:
            raise OperationError('worker_inside_transaction')
        if self._future is not None and self._future.done():
            self.complete(self._request, self._future.result())
            self._future = self._request = self._started = None
        if self._future is None:
            claim = self.claim_next()
            request = self._prepare_or_finish(claim) if claim else None
            request = self._dispatch_or_finish(request) if request else None
            if request:
                self._request, self._started = request, time.monotonic()
                self._future = self._control.submit(self.network, request)
        return self.status()

    def submit_short_read(self, callback):
        """T09 owns completion/commit. A busy control slot never takes this slot."""
        if self._read_future is not None and not self._read_future.done():
            return None
        def read():
            adapter = self.adapter_factory() if self.adapter_factory else EngineAdapter(self.config)
            try:
                return callback(adapter)
            finally:
                adapter.close()
        self._read_future = self._reads.submit(read)
        return self._read_future

    def status(self):
        age = time.monotonic() - self._started if self._started is not None else 0
        return {'control_busy': self._future is not None,
                'short_read_busy': self._read_future is not None and not self._read_future.done(),
                'control_stalled': self._started is not None and age > self.lease_seconds,
                'control_age_seconds': round(age, 2)}

    def close(self):
        # Does NOT cancel running HTTP or reclaim its slot. Supervisor terminates a
        # stuck process; persisted leases resume through unknown-result handling.
        self._control.shutdown(wait=False, cancel_futures=True)
        self._reads.shutdown(wait=False, cancel_futures=True)
