"""Durable owner-private research runs and their replayable SSE events."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone

from api.models import ResearchRun, ResearchRunEvent, ResearchSession

logger = logging.getLogger(__name__)

RUN_LEASE = timedelta(seconds=60)
RUN_HEARTBEAT_SECONDS = 20
MAX_EVENT_WIRE_BYTES = 16 * 1024
MAX_RUN_WIRE_BYTES = 2 * 1024 * 1024
MAX_TEXT_DELTA_BYTES = 2048
IDEMPOTENCY_KEY_RE = re.compile(r'^[\x20-\x7e]{1,64}$')
ACTIVE_STATUSES = ('queued', 'running')


class ResearchRunError(Exception):
    """A fixed, safe failure that may be returned to a research caller."""

    def __init__(self, error_code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


_capacity_lock = threading.Lock()
_admitted_runs: set[str] = set()
_dispatching: set[str] = set()
_dispatch_lock = threading.Lock()
_run_change_condition = threading.Condition()


def _blocked_hosted_environment() -> bool:
    return settings.DJANGO_ENV == 'production'


def validate_idempotency_key(value: str | None) -> str:
    if value is None or value == '':
        return str(uuid.uuid4())
    if not isinstance(value, str) or not IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise ResearchRunError(
            'invalid_idempotency_key', 'Idempotency-Key 必须为 1–64 个可打印 ASCII 字符。', 400,
        )
    return value


def request_digest(query: str, local_only: bool, session_id: str | None) -> str:
    canonical = json.dumps(
        {'query': query, 'local_only': bool(local_only), 'session': str(session_id) if session_id else 'create'},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _reserve(run_key: str) -> bool:
    with _capacity_lock:
        if run_key in _admitted_runs:
            return True
        if len(_admitted_runs) >= 2:
            return False
        _admitted_runs.add(run_key)
        return True


def _rename_reservation(old_key: str, run_key: str) -> None:
    with _capacity_lock:
        _admitted_runs.discard(old_key)
        _admitted_runs.add(run_key)


def _release(run_key: str) -> None:
    with _capacity_lock:
        _admitted_runs.discard(run_key)


def _notify(run_id) -> None:
    del run_id
    with _run_change_condition:
        _run_change_condition.notify_all()


def wait_for_run_change(run_id, timeout: float = 1.0) -> None:
    del run_id
    with _run_change_condition:
        _run_change_condition.wait(timeout=max(0.0, min(float(timeout), 1.0)))


def _wire_record(event_type: str, data: dict) -> bytes:
    payload = {'type': event_type, **data}
    record = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return record.encode('utf-8')


def serialize_event(event_type: str, data: dict) -> str:
    return _wire_record(event_type, data).decode('utf-8')


def _split_text(text: str):
    chunk = []
    byte_count = 0
    for character in text:
        size = len(character.encode('utf-8'))
        if chunk and byte_count + size > MAX_TEXT_DELTA_BYTES:
            yield ''.join(chunk)
            chunk = []
            byte_count = 0
        chunk.append(character)
        byte_count += size
    if chunk:
        yield ''.join(chunk)


def _safe_cas_filter(run_id, run_token):
    filters = {
        'pk': run_id,
        'status': 'running',
        'run_token': run_token,
        'lease_expires_at__gt': timezone.now(),
        'user__is_active': True,
        'session__user_id': F('user_id'),
    }
    return filters


def _interrupt_expired(run_id, run_token) -> bool:
    now = timezone.now()
    changed = ResearchRun.objects.filter(
        pk=run_id, status='running', run_token=run_token,
    ).filter(
        Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
    ).update(
        status='interrupted', run_token=None, lease_expires_at=None,
        error_code='worker_interrupted',
        error_message='研究进程已中断；请明确发起新一轮研究。',
        finished_at=now, updated_at=now,
    )
    if changed:
        _notify(run_id)
    return bool(changed)


def _snapshot(run_id, run_token):
    run = ResearchRun.objects.select_related('user', 'session').filter(
        pk=run_id, status='running', run_token=run_token,
    ).first()
    now = timezone.now()
    if run is None:
        raise ResearchRunError('research_run_changed', '研究任务已取消或已更改。')
    if run.lease_expires_at is None or run.lease_expires_at <= now:
        _interrupt_expired(run_id, run_token)
        raise ResearchRunError('research_lease_lost', '研究任务租约已失效。')
    if _blocked_hosted_environment():
        raise ResearchRunError(
            'hosted_integration_unapproved', '网站订阅研究集成尚未获批。', 503,
        )
    if not run.user.is_active:
        raise ResearchRunError('inactive_owner', '账号已停用，研究任务已停止。', 403)
    if run.session.user_id != run.user_id:
        raise ResearchRunError('research_session_changed', '研究会话归属已更改。')
    return run


def execution_guard(run_id, run_token):
    def guard():
        _snapshot(run_id, run_token)
    return guard


def _append_one_event(run_id, run_token, event_type: str, data: dict, guard) -> None:
    guard()
    wire = _wire_record(event_type, data)
    if len(wire) > MAX_EVENT_WIRE_BYTES:
        raise ResearchRunError(
            'research_event_too_large', '研究进度事件超过安全大小限制。', 413,
        )
    snapshot = ResearchRun.objects.filter(
        pk=run_id, status='running', run_token=run_token,
    ).values('last_event_sequence', 'event_wire_bytes').first()
    if snapshot is None:
        raise ResearchRunError('research_run_changed', '研究任务已取消或已更改。')
    if snapshot['event_wire_bytes'] + len(wire) > MAX_RUN_WIRE_BYTES:
        raise ResearchRunError(
            'research_event_limit_exceeded', '研究进度超过安全大小限制。', 413,
        )
    sequence = snapshot['last_event_sequence'] + 1
    now = timezone.now()
    with transaction.atomic():
        changed = ResearchRun.objects.filter(
            **_safe_cas_filter(run_id, run_token),
            last_event_sequence=snapshot['last_event_sequence'],
            event_wire_bytes=snapshot['event_wire_bytes'],
        ).update(
            last_event_sequence=sequence,
            event_wire_bytes=snapshot['event_wire_bytes'] + len(wire),
            updated_at=now,
        )
        if not changed:
            raise ResearchRunError('research_run_changed', '研究任务已取消或租约已失效。')
        ResearchRunEvent.objects.create(
            run_id=run_id, sequence=sequence, event_type=event_type,
            data=data, wire_bytes=len(wire),
        )
    _notify(run_id)


def append_event(run_id, run_token, event_type: str, data: dict, guard=None) -> None:
    guard = guard or execution_guard(run_id, run_token)
    if event_type == 'text_delta' and isinstance(data.get('text'), str):
        for chunk in _split_text(data['text']):
            _append_one_event(run_id, run_token, event_type, {'text': chunk}, guard)
        return
    _append_one_event(run_id, run_token, event_type, data, guard)


def _terminal_error_event(run_id, message: str):
    return 'error', {'message': message}


def _finish_failed(run_id, run_token, error_code: str, message: str) -> bool:
    now = timezone.now()
    event_type, data = _terminal_error_event(run_id, message)
    wire = _wire_record(event_type, data)
    try:
        with transaction.atomic():
            snapshot = ResearchRun.objects.filter(
                pk=run_id, status='running', run_token=run_token,
                user__is_active=True, session__user_id=F('user_id'),
            ).values('last_event_sequence', 'event_wire_bytes').first()
            if snapshot is None:
                return False
            can_event = (
                len(wire) <= MAX_EVENT_WIRE_BYTES and
                snapshot['event_wire_bytes'] + len(wire) <= MAX_RUN_WIRE_BYTES
            )
            changed = ResearchRun.objects.filter(
                pk=run_id, status='running', run_token=run_token,
                lease_expires_at__gt=now, user__is_active=True,
                session__user_id=F('user_id'),
                last_event_sequence=snapshot['last_event_sequence'],
                event_wire_bytes=snapshot['event_wire_bytes'],
            ).update(
                status='failed', run_token=None, lease_expires_at=None,
                error_code=error_code[:64], error_message=message[:255],
                finished_at=now, updated_at=now,
                **({
                    'last_event_sequence': snapshot['last_event_sequence'] + 1,
                    'event_wire_bytes': snapshot['event_wire_bytes'] + len(wire),
                } if can_event else {}),
            )
            if not changed:
                return False
            if can_event:
                ResearchRunEvent.objects.create(
                    run_id=run_id, sequence=snapshot['last_event_sequence'] + 1,
                    event_type=event_type, data=data, wire_bytes=len(wire),
                )
        _notify(run_id)
        return True
    except Exception as exc:
        logger.info('Research failure state was not saved (%s).', type(exc).__name__)
        return False


def _finish_queued_failed(run_id, error_code: str, message: str) -> bool:
    now = timezone.now()
    event_type, data = _terminal_error_event(run_id, message)
    wire = _wire_record(event_type, data)
    with transaction.atomic():
        snapshot = ResearchRun.objects.filter(pk=run_id, status='queued').values(
            'last_event_sequence', 'event_wire_bytes',
        ).first()
        if snapshot is None:
            return False
        can_event = len(wire) <= MAX_EVENT_WIRE_BYTES and snapshot['event_wire_bytes'] + len(wire) <= MAX_RUN_WIRE_BYTES
        changed = ResearchRun.objects.filter(
            pk=run_id, status='queued', last_event_sequence=snapshot['last_event_sequence'],
            event_wire_bytes=snapshot['event_wire_bytes'],
        ).update(
            status='failed', error_code=error_code[:64], error_message=message[:255],
            finished_at=now, updated_at=now,
            **({
                'last_event_sequence': snapshot['last_event_sequence'] + 1,
                'event_wire_bytes': snapshot['event_wire_bytes'] + len(wire),
            } if can_event else {}),
        )
        if not changed:
            return False
        if can_event:
            ResearchRunEvent.objects.create(
                run_id=run_id, sequence=snapshot['last_event_sequence'] + 1,
                event_type=event_type, data=data, wire_bytes=len(wire),
            )
    _notify(run_id)
    return True


def _claim(run_id):
    token = uuid.uuid4()
    now = timezone.now()
    with transaction.atomic():
        changed = ResearchRun.objects.filter(
            pk=run_id, status='queued', started_at__isnull=True,
            session__user_id=F('user_id'),
        ).update(
            status='running', run_token=token, started_at=now,
            heartbeat_at=now, lease_expires_at=now + RUN_LEASE, updated_at=now,
        )
    return token if changed else None


@contextmanager
def _heartbeat(run_id, run_token):
    stop = threading.Event()

    def beat():
        close_old_connections()
        try:
            while not stop.wait(RUN_HEARTBEAT_SECONDS):
                now = timezone.now()
                try:
                    changed = ResearchRun.objects.filter(
                        pk=run_id, status='running', run_token=run_token,
                        lease_expires_at__gt=now, user__is_active=True,
                        session__user_id=F('user_id'),
                    ).update(
                        heartbeat_at=now, lease_expires_at=now + RUN_LEASE,
                        updated_at=now,
                    )
                    if not changed:
                        return
                except Exception as exc:
                    logger.info('Research heartbeat stopped (%s).', type(exc).__name__)
                    return
                finally:
                    close_old_connections()
        finally:
            close_old_connections()

    thread = threading.Thread(target=beat, name='research-run-heartbeat', daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def _persist_tool_result(run_id, run_token, session, tool_name, args, result):
    guard = execution_guard(run_id, run_token)
    guard()
    with transaction.atomic():
        # This conditional update is intentionally the transaction's first write.
        changed = ResearchRun.objects.filter(**_safe_cas_filter(run_id, run_token)).update(updated_at=timezone.now())
        if not changed:
            raise ResearchRunError('research_run_changed', '研究任务已取消或租约已失效。')
        from .tools import _save_search_result
        _save_search_result(session, tool_name, args, result, guard=guard)
    guard()


def _persist_success(run_id, run_token, session, messages):
    now = timezone.now()
    event_type, data = 'complete', {}
    wire = _wire_record(event_type, data)
    snapshot = ResearchRun.objects.filter(
        pk=run_id, status='running', run_token=run_token,
    ).values('last_event_sequence', 'event_wire_bytes').first()
    if snapshot is None:
        raise ResearchRunError('research_run_changed', '研究任务已取消或已更改。')
    if len(wire) > MAX_EVENT_WIRE_BYTES or snapshot['event_wire_bytes'] + len(wire) > MAX_RUN_WIRE_BYTES:
        raise ResearchRunError(
            'research_event_limit_exceeded', '研究进度超过安全大小限制。', 413,
        )
    sequence = snapshot['last_event_sequence'] + 1
    with transaction.atomic():
        # The run CAS is the first database write, taking SQLite's write lock.
        changed = ResearchRun.objects.filter(
            **_safe_cas_filter(run_id, run_token),
            last_event_sequence=snapshot['last_event_sequence'],
            event_wire_bytes=snapshot['event_wire_bytes'],
        ).update(
            status='succeeded', run_token=None, lease_expires_at=None,
            error_code='', error_message='', finished_at=now,
            last_event_sequence=sequence,
            event_wire_bytes=snapshot['event_wire_bytes'] + len(wire),
            updated_at=now,
        )
        if not changed:
            raise ResearchRunError('research_run_changed', '研究任务已取消或租约已失效。')
        updated = ResearchSession.objects.filter(
            pk=session.pk, user_id=session.user_id,
        ).update(messages=messages, title=session.title, updated_at=now)
        if not updated:
            raise ResearchRunError('research_session_changed', '研究会话已删除或归属已更改。')
        ResearchRunEvent.objects.create(
            run_id=run_id, sequence=sequence, event_type=event_type,
            data=data, wire_bytes=len(wire),
        )
    _notify(run_id)


def _run_worker(run_id, query, local_only):
    close_old_connections()
    token = None
    key = str(run_id)
    try:
        if _blocked_hosted_environment():
            _finish_queued_failed(
                run_id, 'hosted_integration_unapproved',
                '网站订阅研究集成尚未获批。',
            )
            return
        token = _claim(run_id)
        if token is None:
            return
        guard = execution_guard(run_id, token)
        guard()
        run = ResearchRun.objects.select_related('session').get(pk=run_id)
        session = run.session
        from .agent_loop import run_agent_loop

        def emit(event_type, data):
            if event_type == 'complete':
                _notify(run_id)
                return
            if event_type == 'error':
                raise ResearchRunError('research_provider_unavailable', '研究服务暂时不可用，请稍后重试。', 503)
            append_event(run_id, token, event_type, data, guard)

        def persist_completion(messages):
            _persist_success(run_id, token, session, messages)

        with _heartbeat(run_id, token):
            run_agent_loop(
                session, query, emit, local_only=local_only,
                execution_guard=guard,
                persist_completion=persist_completion,
                persist_tool_result=lambda name, args, result: _persist_tool_result(
                    run_id, token, session, name, args, result,
                ),
            )
    except ResearchRunError as exc:
        if exc.error_code == 'research_lease_lost':
            _interrupt_expired(run_id, token)
        elif exc.error_code not in {'research_run_changed', 'inactive_owner', 'research_session_changed'}:
            _finish_failed(run_id, token, exc.error_code, exc.message)
    except Exception as exc:
        logger.info('Research worker failed (%s).', type(exc).__name__)
        if token is not None:
            _finish_failed(run_id, token, 'research_failed', '研究任务失败，请稍后重试。')
        else:
            _finish_queued_failed(run_id, 'research_dispatch_failed', '研究任务暂时无法启动，请重试。')
    finally:
        with _dispatch_lock:
            _dispatching.discard(key)
        _release(key)
        _notify(run_id)
        close_old_connections()


def _dispatch(run_id, query, local_only):
    key = str(run_id)
    if not _reserve(key):
        raise ResearchRunError('research_capacity_reached', '研究任务容量已满，请稍后重试。', 503)
    with _dispatch_lock:
        if key in _dispatching:
            return
        _dispatching.add(key)
    try:
        from api.services.chatgpt_subscription_jobs import submit_background_task
        submit_background_task(_run_worker, run_id, query, local_only)
    except Exception as exc:
        with _dispatch_lock:
            _dispatching.discard(key)
        _release(key)
        logger.info('Research dispatch failed (%s).', type(exc).__name__)
        _finish_queued_failed(run_id, 'research_dispatch_failed', '研究任务暂时无法启动，请重试。')


def _expire_run_if_needed(run):
    now = timezone.now()
    if run.status == 'running' and (run.lease_expires_at is None or run.lease_expires_at <= now):
        _interrupt_expired(run.pk, run.run_token)
        run.refresh_from_db()
    return run


def _attach_existing(run, digest, query, local_only):
    if run.request_hash != digest:
        raise ResearchRunError('idempotency_key_reused', 'Idempotency-Key 已用于不同的研究请求。', 409)
    run = _expire_run_if_needed(run)
    if run.status == 'queued':
        _dispatch(run.pk, query, local_only)
    return run.session, run


def submit_research_run(user, *, session_id, query: str, local_only: bool, idempotency_key: str):
    """Create an owner-private run or attach only to its exact idempotent request."""
    if _blocked_hosted_environment():
        raise ResearchRunError(
            'hosted_integration_unapproved', '网站订阅研究集成尚未获批。', 503,
        )
    key = validate_idempotency_key(idempotency_key)
    if not isinstance(query, str) or not query.strip() or len(query) > 20_000:
        raise ResearchRunError('invalid_research_query', '研究问题长度不合法。', 400)
    query = query.strip()
    digest = request_digest(query, local_only, session_id)
    if session_id is not None:
        session = ResearchSession.objects.filter(pk=session_id, user=user).first()
        if session is None:
            raise ResearchRunError('research_session_not_found', '研究会话不存在。', 404)
    existing = ResearchRun.objects.select_related('session').filter(
        user=user, idempotency_key=key,
    ).first()
    if existing is not None:
        return _attach_existing(existing, digest, query, local_only)

    if session_id is not None:
        _reconcile_session_expiry(user.pk, session_id)
        if ResearchRun.objects.filter(
            user=user, session_id=session_id, status__in=ACTIVE_STATUSES,
        ).exists():
            raise ResearchRunError('research_run_active', '此研究会话已有正在运行的任务。', 409)

    reservation = f'request:{uuid.uuid4()}'
    if not _reserve(reservation):
        raise ResearchRunError('research_capacity_reached', '研究任务容量已满，请稍后重试。', 503)
    try:
        with transaction.atomic():
            raced = ResearchRun.objects.select_related('session').filter(
                user=user, idempotency_key=key,
            ).first()
            if raced is not None:
                raise IntegrityError('idempotency race')
            if session_id is not None:
                session = ResearchSession.objects.filter(pk=session_id, user=user).first()
                if session is None:
                    raise ResearchRunError('research_session_not_found', '研究会话不存在。', 404)
                if ResearchRun.objects.filter(
                    user=user, session=session, status__in=ACTIVE_STATUSES,
                ).exists():
                    raise ResearchRunError('research_run_active', '此研究会话已有正在运行的任务。', 409)
            else:
                session = ResearchSession.objects.create(user=user, title='', messages=[])
            run = ResearchRun.objects.create(
                user=user, session=session, idempotency_key=key,
                request_hash=digest, status='queued',
                queued_query=query, queued_local_only=local_only,
            )
        _rename_reservation(reservation, str(run.pk))
    except IntegrityError:
        _release(reservation)
        raced = ResearchRun.objects.select_related('session').filter(
            user=user, idempotency_key=key,
        ).first()
        if raced is not None:
            return _attach_existing(raced, digest, query, local_only)
        if session_id is not None and ResearchRun.objects.filter(
            user=user, session_id=session_id, status__in=ACTIVE_STATUSES,
        ).exists():
            raise ResearchRunError('research_run_active', '此研究会话已有正在运行的任务。', 409)
        raise ResearchRunError('research_storage_busy', '研究任务暂时无法保存，请重试。', 503)
    except OperationalError:
        _release(reservation)
        raise ResearchRunError('research_storage_busy', '研究任务暂时无法保存，请重试。', 503) from None
    except Exception:
        _release(reservation)
        raise
    _dispatch(run.pk, query, local_only)
    return session, run



def resume_queued_run(user, session, run_id):
    """Explicitly dispatch an existing never-started job, without creating a run.

    A read-only GET cannot dispatch. A RUNNING (or terminal) attempt must never
    be scheduled again, even after its lease expires or the frontend loses state.
    """
    if _blocked_hosted_environment():
        raise ResearchRunError(
            'hosted_integration_unapproved', '网站订阅研究集成尚未获批。', 503,
        )
    if not user.is_active or session.user_id != user.pk:
        raise ResearchRunError('research_session_not_found', '研究会话不存在。', 404)
    run = ResearchRun.objects.filter(
        pk=run_id, user=user, session=session,
    ).first()
    if run is None:
        raise ResearchRunError('research_run_not_found', '研究任务不存在。', 404)
    if run.status == 'running':
        # A committed worker already owns the provider call. Do not dispatch.
        return _expire_run_if_needed(run)
    if run.status != 'queued' or run.started_at is not None:
        raise ResearchRunError('research_run_changed', '研究任务不再等待启动。', 409)
    if not run.queued_query:
        # Migration deliberately does not invent historic prompts.
        raise ResearchRunError(
            'research_queued_input_missing', '旧任务缺少恢复参数，请明确重新研究。', 409,
        )
    if len(run.queued_query) > 20_000:
        raise ResearchRunError(
            'research_queued_input_invalid', '研究任务参数不合法。', 409,
        )
    _dispatch(run.pk, run.queued_query, run.queued_local_only)
    run.refresh_from_db()
    return run


def _reconcile_session_expiry(user_id, session_id):
    now = timezone.now()
    stale = ResearchRun.objects.filter(
        user_id=user_id, session_id=session_id, status='running',
    ).filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
    for run_id, token in stale.values_list('pk', 'run_token'):
        _interrupt_expired(run_id, token)


def latest_run_state(user, session):
    run = ResearchRun.objects.filter(user=user, session=session).order_by('-queued_at', '-pk').first()
    if run is None:
        return None
    status_value = run.status
    if status_value == 'running' and (run.lease_expires_at is None or run.lease_expires_at <= timezone.now()):
        status_value = 'interrupted'
    return {
        'run_id': str(run.pk),
        'status': status_value,
        'error_code': run.error_code,
        'error_message': run.error_message,
        'last_event_sequence': run.last_event_sequence,
    }


def active_run_for_session(user, session):
    run = ResearchRun.objects.filter(
        user=user, session=session, status__in=ACTIVE_STATUSES,
    ).order_by('-queued_at', '-pk').first()
    # A GET remains strictly read-only. Queued work is claimed only by the
    # same idempotent POST, never by opening its event stream.
    if run is None:
        return None
    if run.status == 'running' and (
        run.lease_expires_at is None or run.lease_expires_at <= timezone.now()
    ):
        return None
    return run


def cancel_research_run(user, session, run_id):
    latest = ResearchRun.objects.filter(user=user, session=session).order_by('-queued_at', '-pk').first()
    if latest is None or str(latest.pk) != str(run_id):
        raise ResearchRunError('research_run_changed', '研究任务已更改，请刷新后重试。', 409)
    if latest.status not in ACTIVE_STATUSES:
        return latest
    now = timezone.now()
    data = {'message': '研究任务已取消。'}
    wire = _wire_record('error', data)
    with transaction.atomic():
        snapshot = ResearchRun.objects.filter(
            pk=latest.pk, user=user, session=session, status__in=ACTIVE_STATUSES,
        ).values('last_event_sequence', 'event_wire_bytes').first()
        if snapshot is None:
            current = ResearchRun.objects.get(pk=latest.pk, user=user, session=session)
            if current.status not in ACTIVE_STATUSES:
                return current
            raise ResearchRunError('research_run_changed', '研究任务已更改，请刷新后重试。', 409)
        can_event = len(wire) <= MAX_EVENT_WIRE_BYTES and snapshot['event_wire_bytes'] + len(wire) <= MAX_RUN_WIRE_BYTES
        changed = ResearchRun.objects.filter(
            pk=latest.pk, user=user, session=session, status__in=ACTIVE_STATUSES,
            last_event_sequence=snapshot['last_event_sequence'], event_wire_bytes=snapshot['event_wire_bytes'],
        ).update(
            status='cancelled', run_token=None, lease_expires_at=None,
            error_code='research_cancelled', error_message=data['message'],
            finished_at=now, updated_at=now,
            **({
                'last_event_sequence': snapshot['last_event_sequence'] + 1,
                'event_wire_bytes': snapshot['event_wire_bytes'] + len(wire),
            } if can_event else {}),
        )
        if changed and can_event:
            ResearchRunEvent.objects.create(
                run=latest, sequence=snapshot['last_event_sequence'] + 1,
                event_type='error', data=data, wire_bytes=len(wire),
            )
    if not changed:
        return ResearchRun.objects.get(pk=latest.pk, user=user, session=session)
    _notify(latest.pk)
    return ResearchRun.objects.get(pk=latest.pk, user=user, session=session)


def fence_session_runs(user_id, session_id):
    now = timezone.now()
    ResearchRun.objects.filter(
        user_id=user_id, session_id=session_id, status__in=ACTIVE_STATUSES,
    ).update(
        status='cancelled', run_token=None, lease_expires_at=None,
        error_code='research_session_deleted', error_message='研究会话已删除。',
        finished_at=now, updated_at=now,
    )


def get_run_events(run_id, after_sequence=0, limit=100):
    return ResearchRunEvent.objects.filter(
        run_id=run_id, sequence__gt=after_sequence,
    ).order_by('sequence')[:limit]
