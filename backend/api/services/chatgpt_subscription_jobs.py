"""Durable, owner-private jobs for full-article subscription translations."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Optional

from django.db import close_old_connections, transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Concat
from django.utils import timezone

from api.models import (
    ChatGPTSubscriptionConnection,
    ChatGPTTranslationTask,
    News,
)
from api.services import chatgpt_subscription as subscription
from api.services.chatgpt_subscription import (
    SubscriptionError,
    save_completed_translation,
    source_hash,
    stream_full_translation,
)
from api.services.shared_translations import (
    SharedTranslationError,
    TranslationLease,
    keep_lease_alive,
    result_payload,
)

logger = logging.getLogger(__name__)

TASK_LEASE_TTL = timedelta(seconds=60)
TASK_HEARTBEAT_SECONDS = 20
TERMINAL_STATUSES = frozenset({'succeeded', 'failed', 'cancelled', 'interrupted'})
RESTART_ERROR = '任务已重新开始，请重新连接。'
GENERATION_CHANGED_MESSAGE = '任务已重新开始，请刷新后重试。'
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chatgpt-translation')
_legacy_jobs: dict[tuple, ChatGPTTranslationJob] = {}
# Legacy test fixture name; durable job state never depends on this mapping.
_jobs = _legacy_jobs
_jobs_lock = threading.Lock()
_dispatching: set[tuple[str, int]] = set()


class ChatGPTTranslationJob:
    """Process-local compatibility handle retained for older mock-only tests."""

    def __init__(self, key):
        self.key = key
        self.text = ''
        self.result = None
        self.error: Optional[str] = None
        self.done = False
        self.started_at = time.time()
        self._condition = threading.Condition()

    def append(self, chunk: str) -> None:
        with self._condition:
            self.text += chunk
            self._condition.notify_all()

    def finish(self, result=None, error: Optional[str] = None) -> None:
        with self._condition:
            self.result = result
            self.error = error
            self.done = True
            self._condition.notify_all()

    def wait_for_update(self, last_len: int, timeout: float = 1.0) -> int:
        with self._condition:
            if len(self.text) > last_len or self.done:
                return len(self.text)
            self._condition.wait(timeout=min(max(timeout, 0), 1.0))
            return len(self.text)


class DurableTranslationJob:
    """Generation-bound read handle whose values always come from private DB state."""

    def __init__(self, task_id, generation):
        self.task_id = task_id
        self.generation = int(generation)
        self.key = str(task_id)

    def _state(self):
        task = ChatGPTTranslationTask.objects.filter(pk=self.task_id).first()
        if task is None:
            return None, True
        if task.generation != self.generation:
            return task, True
        return task, False

    @property
    def text(self):
        task, stale = self._state()
        return '' if task is None or stale else task.progress

    @property
    def result(self):
        task, stale = self._state()
        if task is None or stale or task.status != 'succeeded':
            return None
        return task.result

    @property
    def error(self):
        task, stale = self._state()
        if stale:
            return RESTART_ERROR
        if task is None or task.status not in TERMINAL_STATUSES or task.status == 'succeeded':
            return None
        return task.error_message or '本次翻译没有完成，请重试。'

    @property
    def done(self):
        task, stale = self._state()
        return stale or task is None or task.status in TERMINAL_STATUSES

    @property
    def status(self):
        task, _ = self._state()
        return task.status if task is not None else 'failed'

    @property
    def id(self):
        return self.task_id

    def wait_for_update(self, last_len: int, timeout: float = 1.0) -> int:
        deadline = time.monotonic() + min(max(timeout, 0), 1.0)
        while True:
            current = len(self.text)
            if current > last_len or self.done or time.monotonic() >= deadline:
                return current
            time.sleep(min(0.1, max(deadline - time.monotonic(), 0)))


def _task_filter(*, user_id=None, connection_id=None, news_id=None, source_digest=None):
    filters = {}
    if user_id is not None:
        filters['user_id'] = user_id
    if connection_id is not None:
        filters['connection_id'] = connection_id
    if news_id is not None:
        filters['news_id'] = news_id
    if source_digest is not None:
        filters['source_hash'] = source_digest
    return ChatGPTTranslationTask.objects.filter(**filters)


def _recover_expired(task_id, *, user_id=None):
    now = timezone.now()
    expired = ChatGPTTranslationTask.objects.filter(pk=task_id, status='running').filter(
        Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
    )
    if user_id is not None:
        expired = expired.filter(user_id=user_id)
    expired.filter(provider_started=False).update(
        status='queued', run_token=None, started_at=None, lease_expires_at=None,
        updated_at=now,
    )
    expired.filter(provider_started=True).update(
        status='interrupted', run_token=None, lease_expires_at=None,
        error_code='worker_interrupted',
        error_message='翻译进程已中断；为避免重复请求，请明确重试。',
        finished_at=now, updated_at=now,
    )


def get_task(task_id, *, user_id=None):
    """Read a durable task and reconcile only an expired local lease; never call a provider."""
    query = ChatGPTTranslationTask.objects.filter(pk=task_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    task = query.first()
    if task is None:
        return None
    _recover_expired(task.pk, user_id=user_id)
    return query.first()


def _handle(task):
    return DurableTranslationJob(task.pk, task.generation)


def get_job(user_id, connection_id, news_id, source_digest=None):
    query = _task_filter(
        user_id=user_id, connection_id=connection_id, news_id=news_id,
        source_digest=source_digest,
    )
    task = query.order_by('-updated_at').first()
    if task is None:
        return None
    _recover_expired(task.pk, user_id=user_id)
    task = query.order_by('-updated_at').first()
    return _handle(task) if task is not None else None


def _validate_submission(user, connection, news):
    subscription._require_network_mode()
    subscription._require_active_user(user)
    current = ChatGPTSubscriptionConnection.objects.filter(
        pk=connection.pk, user_id=user.pk, is_active=True, user__is_active=True,
    ).first()
    if (
        current is None or current.generation != connection.generation or
        current.selected_model != connection.selected_model
    ):
        raise subscription.ConnectionChangedError('订阅账号已切换或模型已变化，请重新开始翻译。')
    if current.needs_reauth or not current.connected:
        raise SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。')
    if not current.selected_model:
        raise SubscriptionError('请先在订阅设置中选择可见模型。')
    current_news = News.objects.filter(pk=news.pk).only('full_content').first()
    if current_news is None or not current_news.full_content:
        raise SubscriptionError('请先获取完整原文。', 'article_source_missing', 400)
    return current, current_news, source_hash(current_news.full_content)


def _shared_lease_snapshot(lease):
    if lease is None:
        return {'shared_lease_task_id': None, 'shared_lease_token': None}
    return {
        'shared_lease_task_id': int(lease.task_id),
        'shared_lease_token': lease.token,
    }


def _release_unattached_lease(lease):
    if lease is not None:
        lease.finish('failed')


def _snapshot_matches(task, connection, news):
    return bool(
        task.connection_id == connection.pk and
        task.connection_generation == connection.generation and
        task.model_slug == connection.selected_model and
        source_hash(news.full_content) == task.source_hash
    )


def _cancel_stale_active_tasks(user_id, news_id, digest, connection, now):
    candidates = ChatGPTTranslationTask.objects.filter(
        user_id=user_id, news_id=news_id, source_hash=digest,
        status__in=['queued', 'running'],
    ).exclude(
        connection_id=connection.pk,
        connection_generation=connection.generation,
        model_slug=connection.selected_model,
    ).values('pk', 'generation', 'run_token', 'status', 'shared_lease_task_id', 'shared_lease_token')
    for candidate in candidates:
        updated = ChatGPTTranslationTask.objects.filter(
            pk=candidate['pk'], generation=candidate['generation'],
            run_token=candidate['run_token'], status=candidate['status'],
        ).update(
            status='cancelled', run_token=None, lease_expires_at=None,
            error_code='connection_changed',
            error_message='订阅连接或模型已变化，旧任务已停止。',
            finished_at=now, updated_at=now,
        )
        if updated and candidate['shared_lease_task_id'] and candidate['shared_lease_token']:
            TranslationLease(
                candidate['shared_lease_task_id'], candidate['shared_lease_token'],
            ).finish('failed')


def _reset_task(task_id, generation, *, connection, shared_lease, now, expected_statuses):
    return ChatGPTTranslationTask.objects.filter(
        pk=task_id, generation=generation, status__in=expected_statuses,
    ).update(
        connection_id=connection.pk,
        connection_generation=connection.generation,
        model_slug=connection.selected_model,
        generation=F('generation') + 1,
        status='queued', run_token=None,
        **_shared_lease_snapshot(shared_lease),
        provider_started=False, progress='', error_code='', error_message='', result={},
        queued_at=now, started_at=None, finished_at=None, lease_expires_at=None,
        updated_at=now,
    )


def start_or_get_job(user, connection, news, *, force=False, shared_lease=None):
    """Create or attach to a durable owner task; only explicit force resets terminals."""
    current, current_news, digest = _validate_submission(user, connection, news)
    if force not in (True, False):
        _release_unattached_lease(shared_lease)
        raise SubscriptionError('force 必须是布尔值。', 'invalid_force', 400)
    now = timezone.now()
    handle_task = None
    dispatch = False
    attached_lease = False
    with transaction.atomic():
        if force:
            _cancel_stale_active_tasks(user.pk, current_news.pk, digest, current, now)
        task, created = ChatGPTTranslationTask.objects.get_or_create(
            user_id=user.pk,
            connection_id=current.pk,
            news_id=current_news.pk,
            source_hash=digest,
            defaults={
                'model_slug': current.selected_model,
                'connection_generation': current.generation,
                **_shared_lease_snapshot(shared_lease),
                'queued_at': now,
            },
        )
        if not created and task.status in {'queued', 'running'} and not _snapshot_matches(task, current, current_news):
            updated = ChatGPTTranslationTask.objects.filter(
                pk=task.pk, generation=task.generation,
                run_token=task.run_token, status=task.status,
            ).update(
                status='cancelled', run_token=None, lease_expires_at=None,
                error_code='connection_changed',
                error_message='订阅连接或模型已变化，旧任务已停止。',
                finished_at=now, updated_at=now,
            )
            if updated and task.shared_lease_task_id and task.shared_lease_token:
                TranslationLease(task.shared_lease_task_id, task.shared_lease_token).finish('failed')
            task.refresh_from_db()
            if force:
                _reset_task(
                    task.pk, task.generation, connection=current, shared_lease=shared_lease,
                    now=now, expected_statuses={'cancelled'},
                )
                task.refresh_from_db()
                attached_lease = shared_lease is not None
                dispatch = True
            else:
                handle_task = task
        elif not created and force and task.status in TERMINAL_STATUSES:
            changed = _reset_task(
                task.pk, task.generation, connection=current, shared_lease=shared_lease,
                now=now, expected_statuses=TERMINAL_STATUSES,
            )
            if changed:
                task.refresh_from_db()
                attached_lease = shared_lease is not None
                dispatch = True
            else:
                task.refresh_from_db()
        elif task.status == 'queued':
            dispatch = True
            if created:
                attached_lease = shared_lease is not None
        handle_task = task

    if shared_lease is not None and not attached_lease:
        _release_unattached_lease(shared_lease)
    if dispatch and handle_task is not None:
        _dispatch_task(handle_task.pk, handle_task.generation)
    return _handle(handle_task)


def _dispatch_task(task_id, generation):
    key = (str(task_id), int(generation))
    with _jobs_lock:
        if key in _dispatching:
            return
        _dispatching.add(key)
    try:
        _executor.submit(_run_persistent_task, task_id, generation)
    except Exception as exc:
        with _jobs_lock:
            _dispatching.discard(key)
        logger.info('ChatGPT translation dispatch failed (%s).', type(exc).__name__)
        ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, status='queued',
        ).update(
            status='failed', error_code='translation_dispatch_failed',
            error_message='翻译任务暂时无法启动，请重试。', finished_at=timezone.now(),
            updated_at=timezone.now(),
        )


def _lease_from_task(task):
    if task.shared_lease_task_id is None or task.shared_lease_token is None:
        return None
    return TranslationLease(task.shared_lease_task_id, task.shared_lease_token)


def _task_snapshot(task_id, generation, run_token, *, require_started=True):
    subscription._require_network_mode()
    task = ChatGPTTranslationTask.objects.select_related('user', 'connection', 'news').filter(
        pk=task_id, generation=generation, run_token=run_token, status='running',
    ).first()
    now = timezone.now()
    if task is None or task.lease_expires_at is None or task.lease_expires_at <= now:
        raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)
    if require_started and not task.provider_started:
        raise SubscriptionError('翻译任务尚未提交上游请求状态。', 'task_not_started', 409)
    if not task.user.is_active:
        raise SubscriptionError('本地账号已停用，翻译任务已停止。', 'inactive_user', 403)
    connection = task.connection
    if (
        connection.user_id != task.user_id or not connection.is_active or
        connection.needs_reauth or connection.generation != task.connection_generation or
        connection.selected_model != task.model_slug
    ):
        raise subscription.ConnectionChangedError('订阅连接或模型已变化，旧任务已停止。')
    if not task.news.full_content or source_hash(task.news.full_content) != task.source_hash:
        raise SubscriptionError('原文已更新，旧任务已停止。', 'article_source_changed', 409)
    return task


def _execution_guard(task_id, generation, run_token):
    def guard():
        _task_snapshot(task_id, generation, run_token)
    return guard


def _mark_provider_started(task_id, generation, run_token):
    with transaction.atomic():
        task = _task_snapshot(task_id, generation, run_token, require_started=False)
        now = timezone.now()
        changed = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', provider_started=False, lease_expires_at__gt=now,
            connection__is_active=True,
            connection__generation=F('connection_generation'),
            connection__selected_model=F('model_slug'), user__is_active=True,
        ).update(provider_started=True, updated_at=now)
        if not changed:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)


def _append_delta(task_id, generation, run_token, delta):
    if not delta:
        return
    _task_snapshot(task_id, generation, run_token)
    with transaction.atomic():
        task = ChatGPTTranslationTask.objects.select_for_update().filter(
            pk=task_id, generation=generation, run_token=run_token, status='running',
        ).select_related('user', 'connection', 'news').first()
        if task is None:
            raise SubscriptionError('翻译任务已取消。', 'task_cancelled', 409)
        _task_snapshot(task_id, generation, run_token)
        now = timezone.now()
        updated = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', provider_started=True, lease_expires_at__gt=now,
            connection__is_active=True,
            connection__generation=F('connection_generation'),
            connection__selected_model=F('model_slug'), user__is_active=True,
        ).update(progress=Concat(F('progress'), Value(delta)), updated_at=now)
        if not updated:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)


@contextmanager
def _task_heartbeat(task_id, generation, run_token):
    stopped = threading.Event()

    def heartbeat():
        close_old_connections()
        try:
            while not stopped.wait(TASK_HEARTBEAT_SECONDS):
                now = timezone.now()
                try:
                    updated = ChatGPTTranslationTask.objects.filter(
                        pk=task_id, generation=generation, run_token=run_token,
                        status='running', lease_expires_at__gt=now,
                        connection__is_active=True,
                        connection__generation=F('connection_generation'),
                        connection__selected_model=F('model_slug'), user__is_active=True,
                    ).update(lease_expires_at=now + TASK_LEASE_TTL, updated_at=now)
                    if not updated:
                        return
                except Exception as exc:
                    logger.info('ChatGPT translation heartbeat failed (%s).', type(exc).__name__)
                    return
                finally:
                    close_old_connections()
        finally:
            close_old_connections()

    worker = threading.Thread(target=heartbeat, daemon=True, name='chatgpt-translation-heartbeat')
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=2)


def _finalize_task(task_id, generation, run_token, text):
    now = timezone.now()
    with transaction.atomic():
        # This conditional UPDATE is deliberately the first write in the
        # transaction. On SQLite it also takes the write reservation before
        # publishing either private or public translation state.
        locked = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', lease_expires_at__gt=now,
        ).update(updated_at=now)
        if not locked:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)
        task = ChatGPTTranslationTask.objects.select_related('user', 'connection', 'news').get(pk=task_id)
        current = _task_snapshot(task_id, generation, run_token)
        record = save_completed_translation(
            user_id=task.user_id,
            connection_id=task.connection_id,
            news_id=task.news_id,
            expected_generation=task.connection_generation,
            model_slug=task.model_slug,
            text=text,
            source_digest=task.source_hash,
            shared_lease=_lease_from_task(task),
        )
        payload = result_payload(record, 'private')
        updated = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', lease_expires_at__gt=timezone.now(),
        ).update(
            status='succeeded', result=payload, error_code='', error_message='',
            finished_at=timezone.now(), run_token=None, lease_expires_at=None,
            updated_at=timezone.now(),
        )
        if not updated:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)
        return payload


def _safe_error(exc):
    if isinstance(exc, SubscriptionError):
        return str(exc.error_code)[:64], str(exc)[:255]
    return 'translation_failed', 'ChatGPT 全文翻译失败，请稍后重试。'


def _mark_failed(task_id, generation, run_token, exc):
    code, message = _safe_error(exc)
    now = timezone.now()
    try:
        ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', lease_expires_at__gt=now,
        ).update(
            status='failed', error_code=code, error_message=message,
            finished_at=now, run_token=None, lease_expires_at=None, updated_at=now,
        )
    except Exception as finish_exc:
        logger.info('ChatGPT translation failure state was not saved (%s).', type(finish_exc).__name__)


def _run_persistent_task(task_id, generation):
    close_old_connections()
    key = (str(task_id), int(generation))
    run_token = uuid.uuid4()
    shared_lease = None
    try:
        now = timezone.now()
        claimed = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, status='queued',
        ).update(
            status='running', run_token=run_token, provider_started=False,
            started_at=now, lease_expires_at=now + TASK_LEASE_TTL,
            error_code='', error_message='', finished_at=None, updated_at=now,
        )
        if not claimed:
            return
        task = ChatGPTTranslationTask.objects.select_related('user', 'connection', 'news').get(pk=task_id)
        shared_lease = _lease_from_task(task)
        _task_snapshot(task_id, generation, run_token, require_started=False)
        _mark_provider_started(task_id, generation, run_token)
        guard = _execution_guard(task_id, generation, run_token)
        with keep_lease_alive(shared_lease), _task_heartbeat(task_id, generation, run_token):
            guard()
            article = News.objects.only('full_content').get(pk=task.news_id)
            output = stream_full_translation(
                connection_id=task.connection_id,
                expected_generation=task.connection_generation,
                model_slug=task.model_slug,
                article_markdown=article.full_content,
                on_delta=lambda delta: _append_delta(task_id, generation, run_token, delta),
                execution_guard=guard,
            )
            guard()
            _finalize_task(task_id, generation, run_token, output)
    except Exception as exc:
        _mark_failed(task_id, generation, run_token, exc)
        logger.info('ChatGPT article translation job ended without a saved result (%s).', type(exc).__name__)
    finally:
        if shared_lease is not None:
            shared_lease.finish('failed')  # CAS leaves a published/replaced lease untouched.
        close_old_connections()
        with _jobs_lock:
            _dispatching.discard(key)


def cancel_task(task_id, *, user_id, generation):
    """Cancel only the requested generation and revoke only its stored lease snapshot."""
    task = ChatGPTTranslationTask.objects.filter(pk=task_id, user_id=user_id).first()
    if task is None:
        return None, False
    if int(generation) != task.generation:
        raise SubscriptionError(
            GENERATION_CHANGED_MESSAGE, 'task_generation_changed', 409,
        )
    if task.status not in {'queued', 'running'}:
        return task, False
    now = timezone.now()
    with transaction.atomic():
        # Snapshot is read before the CAS so the following shared lease update
        # can target only this exact id/token pair. A concurrent force reset
        # changes generation and makes the CAS fail.
        snapshot = ChatGPTTranslationTask.objects.filter(
            pk=task_id, user_id=user_id, generation=generation,
        ).values('run_token', 'status', 'shared_lease_task_id', 'shared_lease_token').first()
        if snapshot is None:
            return None, False
        updated = ChatGPTTranslationTask.objects.filter(
            pk=task_id, user_id=user_id, generation=generation,
            run_token=snapshot['run_token'], status=snapshot['status'],
            status__in=['queued', 'running'],
        ).update(
            status='cancelled', error_code='cancelled',
            error_message='翻译任务已取消。', finished_at=now,
            run_token=None, lease_expires_at=None, updated_at=now,
        )
        if updated and snapshot['shared_lease_task_id'] is not None and snapshot['shared_lease_token'] is not None:
            TranslationLease(
                snapshot['shared_lease_task_id'], snapshot['shared_lease_token'],
            ).finish('failed')
    return ChatGPTTranslationTask.objects.filter(pk=task_id, user_id=user_id).first(), bool(updated)


def _legacy_job_key(user_id, connection_id, news_id, source_digest):
    return (int(user_id), str(connection_id), int(news_id), source_digest)


def _legacy_run_job(job, *, user_id, connection_id, news_id, source_digest, generation, model_slug, article_markdown, shared_lease):
    """Compatibility path used only by older isolated tests and no public route."""
    close_old_connections()
    try:
        current = News.objects.only('full_content').get(pk=news_id)
        if source_hash(current.full_content) != source_digest:
            raise SubscriptionError('原文已更新，请重新开始全文翻译。')
        with keep_lease_alive(shared_lease):
            output = stream_full_translation(
                connection_id=connection_id,
                expected_generation=generation,
                model_slug=model_slug,
                article_markdown=article_markdown,
                on_delta=job.append,
            )
            record = save_completed_translation(
                user_id=user_id,
                connection_id=connection_id,
                news_id=news_id,
                expected_generation=generation,
                model_slug=model_slug,
                text=output,
                source_digest=source_digest,
                shared_lease=shared_lease,
            )
        job.finish(result=result_payload(record, 'private'))
    except Exception as exc:
        message = str(exc) if isinstance(exc, SubscriptionError) else 'ChatGPT 全文翻译失败，请稍后重试。'
        job.finish(error=message)
        logger.info('ChatGPT article translation job ended without a saved result (%s).', type(exc).__name__)
    finally:
        if shared_lease is not None:
            shared_lease.finish('failed')
        close_old_connections()


def _run_job(job, *, user_id, connection_id, news_id, source_digest, generation, model_slug, article_markdown, shared_lease):
    """Preserve the pre-persistence helper for the existing fake test surface."""
    return _legacy_run_job(
        job, user_id=user_id, connection_id=connection_id, news_id=news_id,
        source_digest=source_digest, generation=generation, model_slug=model_slug,
        article_markdown=article_markdown, shared_lease=shared_lease,
    )
