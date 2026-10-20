"""Durable fixed-bound keyset runs and one reserved short-read scheduler."""
from dataclasses import dataclass
from datetime import timedelta
import time
import uuid

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api.models import FeedSyncState
from api.rss.content_store import StaleWrite
from api.rss.engine import EngineError
from api.rss.sync import commit_entry, prepare_page, prepare_refetch, commit_refetch, reject_missing_refetch


@dataclass(frozen=True)
class SyncLease:
    state_id: uuid.UUID
    token: uuid.UUID
    epoch: int


def acquire_lease(instance_uuid, account_id, *, seconds=120):
    state, _ = FeedSyncState.objects.get_or_create(engine_instance_uuid=instance_uuid, account_id=account_id)
    now, token = timezone.now(), uuid.uuid4()
    with transaction.atomic():
        changed = FeedSyncState.objects.filter(pk=state.pk).filter(
            lease_until__isnull=True).update(lease_token=token, lease_epoch=F('lease_epoch') + 1,
                                           lease_until=now + timedelta(seconds=seconds))
        if not changed:
            changed = FeedSyncState.objects.filter(pk=state.pk, lease_until__lte=now).update(
                lease_token=token, lease_epoch=F('lease_epoch') + 1, lease_until=now + timedelta(seconds=seconds))
        if not changed:
            return None
        state.refresh_from_db()
        return SyncLease(state.pk, token, state.lease_epoch)


def reserve_lease(lease, *, seconds=120):
    # This UPDATE must be the FIRST statement in a commit transaction.
    if not FeedSyncState.objects.filter(pk=lease.state_id, lease_token=lease.token,
            lease_epoch=lease.epoch, lease_until__gt=timezone.now()).update(
            lease_until=timezone.now() + timedelta(seconds=seconds)):
        raise StaleWrite('sync_lease_expired')


def release_lease(lease):
    FeedSyncState.objects.filter(pk=lease.state_id, lease_token=lease.token,
        lease_epoch=lease.epoch).update(lease_until=None, lease_token=None)


def _fields(full):
    return ('reconciliation_run_id', 'reconciliation_upper_id', 'reconciliation_page_cursor',
            'reconciliation_last_complete_at') if full else ('run_id', 'upper_id', 'page_cursor', 'last_complete_at')


def begin_run(lease, upper, *, full=False, lookback=1000):
    run, high, cursor, _ = _fields(full)
    with transaction.atomic():
        reserve_lease(lease)
        state = FeedSyncState.objects.get(pk=lease.state_id)
        if getattr(state, run) is None:
            FeedSyncState.objects.filter(pk=state.pk).update(**{run: uuid.uuid4(), high: upper,
                cursor: 0 if full else max(0, min(state.new_cursor, upper) - lookback)})
    return FeedSyncState.objects.get(pk=lease.state_id)


def finish_page(lease, *, run_id, upper, lower, ids, full=False):
    run, high, cursor, completed = _fields(full)
    with transaction.atomic():
        reserve_lease(lease)
        state = FeedSyncState.objects.get(pk=lease.state_id)
        if (getattr(state, run), getattr(state, high), getattr(state, cursor)) != (run_id, upper, lower):
            raise StaleWrite('sync_run_changed')
        if ids and (ids != sorted(set(ids)) or ids[0] <= lower or ids[-1] > upper):
            raise StaleWrite('invalid_page_bounds')
        done = not ids or ids[-1] == upper
        updates = {cursor: ids[-1] if ids else upper}
        if done:
            updates.update({run: None, completed: timezone.now()})
            if not full:
                updates['new_cursor'] = max(state.new_cursor, upper)
        FeedSyncState.objects.filter(pk=state.pk).update(**updates)
        return done


def health_snapshot(instance_uuid, account_id, runtime_status=None):
    runtime = runtime_status or {}
    state = FeedSyncState.objects.filter(engine_instance_uuid=instance_uuid, account_id=account_id).first()
    return dict(engine_ready=runtime.get('engine_ready') is True,
        initial_sync=not state or state.last_complete_at is None,
        last_successful_incremental=state.last_complete_at.isoformat() if state and state.last_complete_at else None,
        last_successful_full_reconcile=state.reconciliation_last_complete_at.isoformat() if state and state.reconciliation_last_complete_at else None,
        new_cursor=str(state.new_cursor if state else 0),
        observed_upper_id=str(state.upper_id) if state and state.upper_id is not None else None,
        lag=max(0, state.upper_id - state.new_cursor) if state and state.upper_id is not None else None,
        incremental_running=bool(state and state.run_id),
        full_reconcile_running=bool(state and state.reconciliation_run_id),
        error_class=runtime.get('error_class'))


class SyncWorker:
    """Main-thread ORM, one future, no read backlog; each page takes two GETs.

    Finish every captured H before starting another run. Alternate full and
    incremental pages so a large retained sweep cannot starve new arrivals.
    """
    def __init__(self, control, config, *, page_size=100, incremental_seconds=30,
                 reconcile_seconds=86400, lookback=1000):
        self.control, self.config = control, config
        self.page_size, self.incremental_seconds = page_size, incremental_seconds
        self.reconcile_seconds, self.lookback = reconcile_seconds, lookback
        self.lease = None
        self.future = None
        self.phase = None
        self.full = False
        self.previous_full = True
        self.retry_at = 0
        self.failures = 0
        self.error_class = None
        self.engine_ready = False
        self.probed = False
        self.read_started = None
        self.refetch_turn = True
        self.discard_read = False
        self.public_member_turn = True

    def _submit(self, phase, callback):
        future = self.control.submit_short_read(callback)
        if future is not None:
            self.future, self.phase, self.read_started = future, phase, time.monotonic()
            return True
        return False

    def _choose(self):
        if not self.probed:
            return self._submit('probe', lambda adapter: adapter.read_upper_bound())
        from api.rss.public_membership import process_approved_candidates, prepare_public_member
        process_approved_candidates(limit=1,instance_uuid=self.config.engine_instance_uuid,account_id=self.config.account_id)
        if self.public_member_turn:
            self.public_member_turn = False
            token = prepare_public_member(instance_uuid=self.config.engine_instance_uuid,account_id=self.config.account_id)
            if token:
                self.public_member_token = token
                entry_id = token['entry_id']
                return self._submit('public_member',lambda adapter: adapter.get_entry(entry_id))
        else:
            self.public_member_turn = True
        from api.rss.operations import refetch_handoffs
        if self.refetch_turn:
            operation = refetch_handoffs(limit=None).filter(
                binding__engine_instance_uuid=self.config.engine_instance_uuid,
                binding__account_id=self.config.account_id).first()
            if operation:
                self.operation_token, self.refetch_fence = prepare_refetch(operation)
                entry_id = operation.entry.engine_entry_id
                self.refetch_turn = False
                return self._submit('refetch', lambda adapter: adapter.get_entry(entry_id))
        self.refetch_turn = True
        state = FeedSyncState.objects.get(pk=self.lease.state_id)
        now = timezone.now()
        incremental = bool(state.run_id or state.last_complete_at is None or
            (now - state.last_complete_at).total_seconds() >= self.incremental_seconds)
        full = bool(state.reconciliation_run_id or state.reconciliation_last_complete_at is None or
            (now - state.reconciliation_last_complete_at).total_seconds() >= self.reconcile_seconds)
        full = full and state.last_complete_at is not None
        if not incremental and not full:
            return False
        self.full = full and (not incremental or not self.previous_full)
        self.previous_full = self.full
        run, high, cursor, _ = _fields(self.full)
        if getattr(state, run) is None:
            return self._submit('upper', lambda adapter: adapter.read_upper_bound())
        self.run_id, self.upper, self.lower = getattr(state, run), getattr(state, high), getattr(state, cursor)
        lower, upper, limit = self.lower, self.upper, self.page_size
        return self._submit('discover', lambda adapter: adapter.list_entries(lower=lower, upper=upper, limit=limit))

    def _complete(self, phase, result):
        self.engine_ready = True
        if phase == 'probe':
            self.probed = True
            return
        if phase == 'public_member':
            from api.rss.public_membership import finish_public_member
            finish_public_member(self.public_member_token,result,reserve=lambda: reserve_lease(self.lease))
            return
        if phase == 'refetch':
            commit_refetch(result, self.operation_token, self.refetch_fence,
                           reserve=lambda: reserve_lease(self.lease))
            return
        if phase == 'upper':
            begin_run(self.lease, result, full=self.full, lookback=self.lookback)
            # Resume this run, rather than allowing the scheduler to select the
            # other run between its upper-bound query and its first page.
            self.previous_full = not self.full
            return
        if phase == 'discover':
            self.fences = prepare_page(result, instance_uuid=self.config.engine_instance_uuid, account_id=self.config.account_id)
            self.discovery_ids = [dto.id for dto in result]
            lower, upper, limit = self.lower, self.upper, self.page_size
            if not self._submit('candidate', lambda adapter: adapter.list_entries(lower=lower, upper=upper, limit=limit)):
                raise StaleWrite('short_read_slot_unavailable')
            return
        if phase == 'candidate':
            if [dto.id for dto in result] != self.discovery_ids:
                raise StaleWrite('page_members_changed')
            seen_urls = set()
            for dto in result:
                url = self.fences[dto.id].url
                if url in seen_urls:
                    from api.rss.sync import record_duplicate
                    record_duplicate(dto, reserve=lambda: reserve_lease(self.lease))
                    continue
                seen_urls.add(url)
                commit_entry(dto, self.fences[dto.id], reserve=lambda: reserve_lease(self.lease))
            finish_page(self.lease, run_id=self.run_id, upper=self.upper, lower=self.lower,
                        ids=[dto.id for dto in result], full=self.full)

    def tick(self):
        from django.db import OperationalError
        if self.lease is None:
            self.lease = acquire_lease(self.config.engine_instance_uuid, self.config.account_id)
            if self.lease is None:
                self.error_class = 'sync_lease_busy'
                return self.status()
        try:
            reserve_lease(self.lease)
            if self.future is not None:
                if not self.future.done():
                    return self.status()
                future, phase = self.future, self.phase
                self.future = self.phase = self.read_started = None
                if self.discard_read:
                    # Drain the old slot but never authorize its result with a
                    # newly acquired lease epoch. Re-discover under the new lease.
                    self.discard_read = False
                    self._choose()
                    return self.status()
                try:
                    result = future.result()
                except EngineError as error:
                    if phase == 'public_member' and error.code == 'not_found':
                        from api.rss.public_membership import finish_public_member
                        finish_public_member(self.public_member_token,None,reserve=lambda: reserve_lease(self.lease))
                    elif phase != 'refetch' or error.code != 'not_found':
                        raise
                    else:
                        reject_missing_refetch(self.operation_token, reserve=lambda: reserve_lease(self.lease))
                else:
                    self._complete(phase, result)
                self.failures, self.error_class = 0, None
            if self.future is None and time.monotonic() >= self.retry_at:
                self._choose()
        except (EngineError, OperationalError, StaleWrite) as error:
            self.error_class = getattr(error, 'code', getattr(error, 'reason', 'sqlite_busy'))
            if isinstance(error, EngineError):
                self.engine_ready = False
            if isinstance(error, EngineError) and error.code == 'response_too_large' and self.page_size > 1:
                self.page_size = max(1, self.page_size // 2)
            self.failures += 1
            delay = min(60, 2 ** min(self.failures, 6))
            retry_after = getattr(error, 'retry_after', None)
            self.retry_at = time.monotonic() + max(delay, min(300, retry_after or 0))
            if isinstance(error, StaleWrite) and error.reason == 'sync_lease_expired':
                self.lease = None
                self.discard_read = self.future is not None
        return self.status()

    def status(self):
        return {**health_snapshot(self.config.engine_instance_uuid, self.config.account_id, {
            'engine_ready': self.engine_ready, 'error_class': self.error_class}),
            'sync_read_age_seconds': 0 if self.read_started is None else time.monotonic() - self.read_started,
            'sync_read_busy': self.future is not None}

    def close(self):
        if self.lease:
            release_lease(self.lease)
