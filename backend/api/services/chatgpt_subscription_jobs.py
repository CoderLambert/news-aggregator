"""Durable, owner-private jobs for full-article subscription translations."""

from __future__ import annotations

import logging
import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Concat
from django.utils import timezone

from api.models import (
    ChatGPTArticleTranslation,
    ChatGPTSubscriptionConnection,
    ChatGPTTranslationTask,
    News,
    UserAIConnection,
    UserAIModelConfig,
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
    LEASE_TTL as SHARED_LEASE_TTL,
    TranslationLease,
    keep_lease_alive,
    result_payload,
)
from api.services.ai_execution import ExecutionSnapshot, ModelSelectionError, resolve_execution
from api.services.ai_model_registry import get_model_preset
from api.services.ai_translation import (
    BYOKTranslationError,
    TRANSLATION_ERRORS,
    assert_byok_translation_snapshot_current,
    preflight_byok_translation_source,
    prepare_byok_translation_execution,
    stream_byok_translation,
)
from api.services.ai_registry import get_profile

logger = logging.getLogger(__name__)

TASK_LEASE_TTL = timedelta(seconds=60)
TASK_HEARTBEAT_SECONDS = 20
TERMINAL_STATUSES = frozenset({'succeeded', 'failed', 'cancelled', 'interrupted'})
RESTART_ERROR = '任务已重新开始，请重新连接。'
GENERATION_CHANGED_MESSAGE = '任务已重新开始，请刷新后重试。'
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chatgpt-translation')


def submit_background_task(function, *args, **kwargs):
    """Submit one private background task to the shared two-worker executor."""
    return _executor.submit(function, *args, **kwargs)
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

    def __init__(self, task_id, generation, user_id=None):
        self.task_id = task_id
        self.generation = int(generation)
        self.user_id = user_id
        self.key = str(task_id)

    def _state(self):
        task = get_task(self.task_id, user_id=self.user_id)
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
        task, stale = self._state()
        return 'interrupted' if stale else (task.status if task is not None else 'failed')

    @property
    def id(self):
        return self.task_id

    def wait_for_update(self, last_len: int, timeout: float = 1.0) -> int:
        deadline = time.monotonic() + min(max(timeout, 0), 1.0)
        while True:
            task, stale = self._state()
            if task is not None and not stale and task.status == 'queued':
                _dispatch_task(task.pk, task.generation)
            current = 0 if task is None or stale else len(task.progress)
            if (
                current > last_len or stale or task is None or
                task.status in TERMINAL_STATUSES or time.monotonic() >= deadline
            ):
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


_IDEMPOTENCY_KEY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
_BYOK_SUBMISSION_LOCKS = tuple(threading.Lock() for _ in range(32))


def _byok_snapshot_from_task(task) -> ExecutionSnapshot:
    """Rebuild the immutable, secret-free resolver snapshot stored at submission."""
    if (
        task.ai_connection_id is None or task.model_config_id_snapshot is None
        or task.credential_epoch is None or task.config_revision is None
        or task.endpoint_profile_version is None or not task.execution_digest
    ):
        raise BYOKTranslationError('execution_changed')
    values = {
        'user_id': task.user_id,
        'task_kind': 'full_translation',
        'selected_by_task_kind': task.selected_by_task_kind,
        'model_config_id': str(task.model_config_id_snapshot),
        'connection_id': str(task.ai_connection_id),
        'provider_id': task.provider_id_snapshot,
        'endpoint_profile': task.endpoint_profile_snapshot,
        'endpoint_profile_version': task.endpoint_profile_version,
        'credential_epoch': task.credential_epoch,
        'config_revision': task.config_revision,
        'model_id': task.model_slug,
    }
    digest = hashlib.sha256(
        json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8'),
    ).hexdigest()
    if digest != task.execution_digest:
        raise BYOKTranslationError('execution_changed')
    return ExecutionSnapshot(**values, digest=digest)


def _validate_byok_task_snapshot(task, *, current_news=None):
    if (
        task.connection_id is not None or task.ai_connection_id is None
        or task.ai_connection.user_id != task.user_id
        or not task.ai_connection.is_enabled or task.ai_connection.is_deleted
        or not task.ai_connection.credential_ciphertext
        or not task.ai_connection.encryption_key_id
        or task.ai_connection.credential_epoch != task.credential_epoch
        or task.ai_connection.credential_version != task.credential_version
        or task.ai_connection.provider_id != task.provider_id_snapshot
        or task.ai_connection.endpoint_profile != task.endpoint_profile_snapshot
        or task.ai_connection.endpoint_profile_version != task.endpoint_profile_version
    ):
        raise BYOKTranslationError('execution_changed')
    if not task.user.is_active:
        raise BYOKTranslationError('execution_changed')
    snapshot = _byok_snapshot_from_task(task)
    assert_byok_translation_snapshot_current(snapshot)
    if current_news is None:
        current_news = News.objects.only('full_content').filter(pk=task.news_id).first()
    if (
        current_news is None or not current_news.full_content
        or source_hash(current_news.full_content) != task.source_hash
        or source_hash(task.source_snapshot) != task.source_hash
    ):
        raise BYOKTranslationError('article_source_changed')
    return snapshot


def _byok_error_message(code):
    return TRANSLATION_ERRORS.get(code, '个人模型全文翻译失败，请稍后重试。')


def _same_byok_submission(task, *, user_id, news_id, source_text, snapshot, connection):
    return bool(
        task.user_id == user_id
        and task.news_id == news_id
        and task.ai_connection_id == connection.pk
        and task.source_hash == source_hash(source_text)
        and task.source_snapshot == source_text
        and task.execution_digest == snapshot.digest
        and task.credential_epoch == snapshot.credential_epoch
        and task.credential_version == connection.credential_version
        and str(task.model_config_id_snapshot) == snapshot.model_config_id
        and task.config_revision == snapshot.config_revision
        and task.model_slug == snapshot.model_id
    )


def start_or_get_byok_job(user, news, idempotency_key):
    """Start or attach to one explicit, owner-private BYOK translation attempt."""
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise BYOKTranslationError('invalid_idempotency_key')
    lock_index = hash((getattr(user, 'pk', None), idempotency_key)) % len(_BYOK_SUBMISSION_LOCKS)
    # SQLite cannot reliably upgrade competing read transactions into writers.
    # A fixed set of in-process stripes serializes only concurrent submissions;
    # the database unique constraint still protects separate application workers.
    with _BYOK_SUBMISSION_LOCKS[lock_index]:
        return _start_or_get_byok_job_locked(user, news, idempotency_key)


def _start_or_get_byok_job_locked(user, news, idempotency_key):
    if not settings.AI_BYOK_ENABLED:
        raise BYOKTranslationError('byok_disabled')
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_active', False):
        raise BYOKTranslationError('authentication_required')

    try:
        snapshot = resolve_execution(user, 'full_translation')
    except ModelSelectionError as exc:
        raise BYOKTranslationError(exc.args[0]) from None

    try:
        assert_byok_translation_snapshot_current(snapshot)
    except BYOKTranslationError:
        raise

    source_text = None
    digest = None
    connection = None
    try:
        with transaction.atomic():
            current_news = News.objects.select_for_update().only('id', 'full_content').filter(
                pk=news.pk,
            ).first()
            if current_news is None or not current_news.full_content:
                raise BYOKTranslationError('article_source_missing')
            source_text = current_news.full_content

            connection = UserAIConnection.objects.select_for_update().filter(
                pk=snapshot.connection_id,
                user_id=user.pk,
                is_enabled=True,
                is_deleted=False,
                credential_epoch=snapshot.credential_epoch,
            ).first()
            if connection is None:
                raise BYOKTranslationError('execution_changed')

            preflight_byok_translation_source(source_text, snapshot)

            digest = source_hash(source_text)
            existing = ChatGPTTranslationTask.objects.filter(
                user_id=user.pk,
                idempotency_key=idempotency_key,
                ai_connection__isnull=False,
            ).first()
            if existing is not None:
                if not _same_byok_submission(
                    existing, user_id=user.pk, news_id=current_news.pk,
                    source_text=source_text,
                    snapshot=snapshot, connection=connection,
                ):
                    raise BYOKTranslationError('idempotency_key_reused')
                task = existing
                _recover_expired(task.pk, user_id=user.pk)
                task.refresh_from_db()
                dispatch = task.status == 'queued'
            else:
                task_values = {
                    'user': user,
                    'connection': None,
                    'ai_connection': connection,
                    'news': current_news,
                    'source_hash': digest,
                    'model_slug': snapshot.model_id,
                    'connection_generation': None,
                    'credential_epoch': snapshot.credential_epoch,
                    'credential_version': connection.credential_version,
                    'model_config_id_snapshot': snapshot.model_config_id,
                    'selected_by_task_kind': snapshot.selected_by_task_kind,
                    'config_revision': snapshot.config_revision,
                    'endpoint_profile_version': snapshot.endpoint_profile_version,
                    'provider_id_snapshot': snapshot.provider_id,
                    'endpoint_profile_snapshot': snapshot.endpoint_profile,
                    'execution_digest': snapshot.digest,
                    'idempotency_key': idempotency_key,
                    'source_snapshot': source_text,
                }
                try:
                    with transaction.atomic():
                        task = ChatGPTTranslationTask.objects.create(**task_values)
                    dispatch = True
                except IntegrityError:
                    task = ChatGPTTranslationTask.objects.filter(
                        user_id=user.pk,
                        idempotency_key=idempotency_key,
                        ai_connection__isnull=False,
                    ).first()
                    if task is None or not _same_byok_submission(
                        task, user_id=user.pk, news_id=current_news.pk,
                        source_text=source_text,
                        snapshot=snapshot, connection=connection,
                    ):
                        raise BYOKTranslationError('idempotency_key_reused') from None
                    dispatch = task.status == 'queued'
    except OperationalError:
        # SQLite may briefly report a busy writer for concurrent identical
        # submissions. Retry only the owner-scoped attach; never create a
        # second task from this fallback path.
        if source_text is not None and digest is not None and connection is not None:
            for delay in (0.02, 0.05, 0.10, 0.20):
                time.sleep(delay)
                try:
                    task = ChatGPTTranslationTask.objects.filter(
                        user_id=user.pk,
                        idempotency_key=idempotency_key,
                        ai_connection__isnull=False,
                    ).first()
                    if task is None:
                        continue
                    if not _same_byok_submission(
                        task, user_id=user.pk, news_id=news.pk,
                        source_text=source_text, snapshot=snapshot, connection=connection,
                    ):
                        raise BYOKTranslationError('idempotency_key_reused')
                    _recover_expired(task.pk, user_id=user.pk)
                    task.refresh_from_db()
                    if task.status == 'queued':
                        _dispatch_task(task.pk, task.generation)
                    return _handle(task)
                except OperationalError:
                    continue
        raise SubscriptionError(
            '翻译任务暂时无法处理，请稍后重试。', 'task_storage_busy', 503,
        ) from None

    if dispatch:
        _dispatch_task(task.pk, task.generation)
    return _handle(task)


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


def _expired_running_task(task, now):
    return (
        task.status == 'running' and
        (task.lease_expires_at is None or task.lease_expires_at <= now)
    )


def get_task(task_id, *, user_id=None):
    """Read a durable task and reconcile only an expired local lease; never call a provider."""
    query = ChatGPTTranslationTask.objects.filter(pk=task_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    try:
        task = query.first()
        if task is None:
            return None
        if _expired_running_task(task, timezone.now()):
            _recover_expired(task.pk, user_id=user_id)
            task = query.first()
        return task
    except OperationalError:
        raise SubscriptionError(
            '任务状态暂时不可用，请稍后重试。', 'task_storage_busy', 503,
        ) from None


def _handle(task):
    return DurableTranslationJob(task.pk, task.generation, task.user_id)


def get_job(user_id, connection_id, news_id, source_digest=None):
    query = _task_filter(
        user_id=user_id, connection_id=connection_id, news_id=news_id,
        source_digest=source_digest,
    )
    try:
        task = query.order_by('-updated_at').first()
        if task is None:
            return None
        if _expired_running_task(task, timezone.now()):
            _recover_expired(task.pk, user_id=user_id)
            task = query.order_by('-updated_at').first()
        return _handle(task) if task is not None else None
    except OperationalError:
        raise SubscriptionError(
            '任务状态暂时不可用，请稍后重试。', 'task_storage_busy', 503,
        ) from None


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
        try:
            lease.finish('failed')
        except Exception as exc:
            logger.info('Unattached translation lease release failed (%s).', type(exc).__name__)


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
        if updated and candidate['shared_lease_task_id'] is not None and candidate['shared_lease_token'] is not None:
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
    try:
        current, current_news, digest = _validate_submission(user, connection, news)
    except OperationalError:
        _release_unattached_lease(shared_lease)
        raise SubscriptionError(
            '翻译任务暂时无法处理，请稍后重试。', 'task_storage_busy', 503,
        ) from None
    except Exception:
        _release_unattached_lease(shared_lease)
        raise
    if type(force) is not bool:
        _release_unattached_lease(shared_lease)
        raise SubscriptionError('force 必须是布尔值。', 'invalid_force', 400)
    now = timezone.now()
    handle_task = None
    dispatch = False
    attached_lease = False
    try:
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
            if not created:
                _recover_expired(task.pk, user_id=user.pk)
                task.refresh_from_db()
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
                if updated and task.shared_lease_task_id is not None and task.shared_lease_token is not None:
                    TranslationLease(
                        task.shared_lease_task_id, task.shared_lease_token,
                    ).finish('failed')
                task.refresh_from_db()
                if force:
                    _reset_task(
                        task.pk, task.generation, connection=current, shared_lease=shared_lease,
                        now=now, expected_statuses={'cancelled'},
                    )
                    task.refresh_from_db()
                    attached_lease = shared_lease is not None
                    dispatch = task.status == 'queued'
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
    except OperationalError as exc:
        _release_unattached_lease(shared_lease)
        # SQLite can still be releasing the competing transaction when we try
        # to attach to its unique task. Retry ONLY the idempotent read/attach:
        # do not create or reset a task (or call a provider) in this path.
        for delay in (0, 0.02, 0.05, 0.10, 0.20):
            if delay:
                time.sleep(delay)
            try:
                task = _task_filter(
                    user_id=user.pk, connection_id=current.pk, news_id=current_news.pk,
                    source_digest=digest,
                ).first()
                if task is None:
                    continue
                if force and task.status not in {'queued', 'running'}:
                    break
                _recover_expired(task.pk, user_id=user.pk)
                task.refresh_from_db()
                if task.status == 'queued' and _snapshot_matches(task, current, current_news):
                    _dispatch_task(task.pk, task.generation)
                return _handle(task)
            except OperationalError:
                continue
        logger.info('ChatGPT translation task storage was busy (%s).', type(exc).__name__)
        raise SubscriptionError(
            '翻译任务暂时无法处理，请稍后重试。', 'task_storage_busy', 503,
        ) from None

    if shared_lease is not None and not attached_lease:
        _release_unattached_lease(shared_lease)
    if dispatch and handle_task is not None:
        _dispatch_task(handle_task.pk, handle_task.generation)
    return _handle(handle_task)


def _fail_queued_task(task_id, generation, *, error_code, error_message):
    now = timezone.now()
    with transaction.atomic():
        lease_snapshot = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, status='queued', run_token__isnull=True,
        ).values('shared_lease_task_id', 'shared_lease_token').first()
        if lease_snapshot is None:
            return False
        changed = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, status='queued', run_token__isnull=True,
        ).update(
            status='failed', error_code=error_code, error_message=error_message,
            finished_at=now, updated_at=now,
        )
        if changed and lease_snapshot['shared_lease_task_id'] is not None:
            TranslationLease(
                lease_snapshot['shared_lease_task_id'], lease_snapshot['shared_lease_token'],
            ).finish('failed')
        return bool(changed)


def _queued_task_snapshot(task_id, generation):
    task = ChatGPTTranslationTask.objects.select_related(
        'user', 'connection', 'ai_connection', 'news',
    ).filter(pk=task_id, generation=generation, status='queued').first()
    if task is None:
        return None
    if not task.user.is_active:
        raise SubscriptionError('本地账号已停用，翻译任务已停止。', 'inactive_user', 403)
    if task.ai_connection_id is not None:
        _validate_byok_task_snapshot(task)
        return task
    subscription._require_network_mode()
    if (
        task.connection.user_id != task.user_id or not task.connection.is_active or
        task.connection.needs_reauth or not task.connection.connected or
        task.connection.generation != task.connection_generation or
        task.connection.selected_model != task.model_slug
    ):
        raise subscription.ConnectionChangedError('订阅连接或模型已变化，旧任务已停止。')
    if not task.news.full_content or source_hash(task.news.full_content) != task.source_hash:
        raise SubscriptionError('原文已更新，旧任务已停止。', 'article_source_changed', 409)
    return task


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
        try:
            _fail_queued_task(
                task_id, generation,
                error_code='translation_dispatch_failed',
                error_message='翻译任务暂时无法启动，请重试。',
            )
        except Exception as finish_exc:
            logger.info('ChatGPT translation dispatch state was not saved (%s).', type(finish_exc).__name__)


def _lease_from_task(task):
    if task.shared_lease_task_id is None or task.shared_lease_token is None:
        return None
    return TranslationLease(task.shared_lease_task_id, task.shared_lease_token)


def _task_snapshot(task_id, generation, run_token, *, require_started=True):
    task = ChatGPTTranslationTask.objects.select_related(
        'user', 'connection', 'ai_connection', 'news',
    ).filter(
        pk=task_id, generation=generation, run_token=run_token, status='running',
    ).first()
    now = timezone.now()
    if task is None or task.lease_expires_at is None or task.lease_expires_at <= now:
        raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)
    if require_started and not task.provider_started:
        raise SubscriptionError('翻译任务尚未提交上游请求状态。', 'task_not_started', 409)
    if not task.user.is_active:
        raise SubscriptionError('本地账号已停用，翻译任务已停止。', 'inactive_user', 403)
    if task.ai_connection_id is not None:
        _validate_byok_task_snapshot(task)
        return task
    subscription._require_network_mode()
    connection = task.connection
    if (
        connection.user_id != task.user_id or not connection.is_active or
        connection.needs_reauth or not connection.connected or
        connection.generation != task.connection_generation or
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
        query = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', provider_started=False, lease_expires_at__gt=now,
            user__is_active=True,
        )
        if task.ai_connection_id is not None:
            query = query.filter(
                ai_connection_id=task.ai_connection_id,
                ai_connection__user_id=F('user_id'),
                ai_connection__is_enabled=True,
                ai_connection__is_deleted=False,
                ai_connection__credential_epoch=F('credential_epoch'),
                ai_connection__credential_version=F('credential_version'),
            )
        else:
            query = query.filter(
                connection__is_active=True,
                connection__generation=F('connection_generation'),
                connection__selected_model=F('model_slug'),
            )
        changed = query.update(provider_started=True, updated_at=now)
        if not changed:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)


def _append_delta(task_id, generation, run_token, delta):
    if not delta:
        return
    _task_snapshot(task_id, generation, run_token)
    with transaction.atomic():
        task = ChatGPTTranslationTask.objects.select_for_update().filter(
            pk=task_id, generation=generation, run_token=run_token, status='running',
        ).select_related('user', 'connection', 'ai_connection', 'news').first()
        if task is None:
            raise SubscriptionError('翻译任务已取消。', 'task_cancelled', 409)
        _task_snapshot(task_id, generation, run_token)
        now = timezone.now()
        query = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', provider_started=True, lease_expires_at__gt=now,
            user__is_active=True,
        )
        if task.ai_connection_id is not None:
            query = query.filter(
                ai_connection_id=task.ai_connection_id,
                ai_connection__user_id=F('user_id'),
                ai_connection__is_enabled=True,
                ai_connection__is_deleted=False,
                ai_connection__credential_epoch=F('credential_epoch'),
                ai_connection__credential_version=F('credential_version'),
            )
        else:
            query = query.filter(
                connection__is_active=True,
                connection__generation=F('connection_generation'),
                connection__selected_model=F('model_slug'),
            )
        updated = query.update(progress=Concat(F('progress'), Value(delta)), updated_at=now)
        if not updated:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)


@contextmanager
def _task_heartbeat(task_id, generation, run_token, shared_lease=None):
    stopped = threading.Event()
    ai_connection_id = ChatGPTTranslationTask.objects.filter(
        pk=task_id, generation=generation, run_token=run_token, status='running',
    ).values_list('ai_connection_id', flat=True).first()
    if shared_lease is not None and not shared_lease.current().exists():
        raise SharedTranslationError('共享翻译任务已过期，请重新开始。')

    def heartbeat():
        close_old_connections()
        try:
            while not stopped.wait(TASK_HEARTBEAT_SECONDS):
                now = timezone.now()
                try:
                    with transaction.atomic():
                        query = ChatGPTTranslationTask.objects.filter(
                            pk=task_id, generation=generation, run_token=run_token,
                            status='running', lease_expires_at__gt=now, user__is_active=True,
                        )
                        if ai_connection_id is not None:
                            query = query.filter(
                                ai_connection_id=ai_connection_id,
                                ai_connection__user_id=F('user_id'),
                                ai_connection__is_enabled=True,
                                ai_connection__is_deleted=False,
                                ai_connection__credential_epoch=F('credential_epoch'),
                                ai_connection__credential_version=F('credential_version'),
                            )
                        else:
                            query = query.filter(
                                connection__is_active=True,
                                connection__generation=F('connection_generation'),
                                connection__selected_model=F('model_slug'),
                            )
                        updated = query.update(lease_expires_at=now + TASK_LEASE_TTL, updated_at=now)
                        if not updated:
                            return
                        if shared_lease is not None:
                            extended = shared_lease.current().update(
                                expires_at=now + SHARED_LEASE_TTL, updated_at=now,
                            )
                            if not extended:
                                raise SharedTranslationError(
                                    '共享翻译任务已过期，请重新开始。',
                                )
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


def _save_byok_translation_result(task, text):
    connection = UserAIConnection.objects.select_for_update().filter(
        pk=task.ai_connection_id,
        user_id=task.user_id,
        is_enabled=True,
        is_deleted=False,
        credential_epoch=task.credential_epoch,
        credential_version=task.credential_version,
    ).first()
    if connection is None:
        raise BYOKTranslationError('execution_changed')
    news = News.objects.select_for_update().only('full_content').filter(pk=task.news_id).first()
    if news is None or source_hash(news.full_content) != task.source_hash:
        raise BYOKTranslationError('article_source_changed')
    if source_hash(task.source_snapshot) != task.source_hash:
        raise BYOKTranslationError('article_source_changed')
    config = UserAIModelConfig.objects.select_for_update().select_related('connection').filter(
        pk=task.model_config_id_snapshot,
        connection_id=connection.pk,
        connection__user_id=task.user_id,
        config_revision=task.config_revision,
        model_id=task.model_slug,
        catalog_version__gt='',
    ).first()
    if config is None:
        raise BYOKTranslationError('execution_changed')
    preset = get_model_preset(config.catalog_model_id, connection.provider_id)
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if (
        preset is None
        or config.catalog_version != preset['catalog_version']
        or config.model_id != preset['model_id']
        or config.proxy_model_alias != preset['proxy_model_alias']
        or connection.provider_id != task.provider_id_snapshot
        or connection.endpoint_profile != task.endpoint_profile_snapshot
        or connection.endpoint_profile_version != task.endpoint_profile_version
        or profile is None
        or profile['version'] != task.endpoint_profile_version
    ):
        raise BYOKTranslationError('execution_changed')
    if not isinstance(text, str) or not text.strip():
        raise BYOKTranslationError('empty_response')

    completed_at = timezone.now()
    record, _ = ChatGPTArticleTranslation.objects.update_or_create(
        user_id=task.user_id,
        ai_connection_id=connection.pk,
        news_id=task.news_id,
        defaults={
            'connection': None,
            'source_hash': task.source_hash,
            'model_slug': task.model_slug,
            'content': text,
            'completed_at': completed_at,
        },
    )
    return {
        'full_content_zh': record.content,
        'full_content_zh_fetched_at': record.completed_at.isoformat(),
        'full_content_zh_source': 'byok',
        'full_content_zh_scope': 'private',
        'model_source': {
            'provider': profile['provider_name'] if profile else connection.provider_id,
            'model': config.display_name,
        },
        'result_id': str(record.pk),
        'source_hash': task.source_hash,
    }


def _finalize_task(task_id, generation, run_token, text):
    now = timezone.now()
    with transaction.atomic():
        # This conditional UPDATE is deliberately the first write in the
        # transaction. On SQLite it also takes the write reservation before
        # publishing either private or public translation state.
        locked = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, run_token=run_token,
            status='running', provider_started=True, lease_expires_at__gt=now,
        ).update(updated_at=now)
        if not locked:
            raise SubscriptionError('翻译任务已取消或租约失效。', 'task_lease_lost', 409)
        task = ChatGPTTranslationTask.objects.select_related(
            'user', 'connection', 'ai_connection', 'news',
        ).get(pk=task_id)
        current = _task_snapshot(task_id, generation, run_token)
        if task.ai_connection_id is not None:
            payload = _save_byok_translation_result(task, text)
        else:
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
    if isinstance(exc, BYOKTranslationError):
        return str(exc.code)[:64], _byok_error_message(exc.code)[:255]
    return 'translation_failed', 'ChatGPT 全文翻译失败，请稍后重试。'


def _mark_failed(task_id, generation, run_token, exc):
    code, message = _safe_error(exc)
    now = timezone.now()
    try:
        with transaction.atomic():
            lease_snapshot = ChatGPTTranslationTask.objects.filter(
                pk=task_id, generation=generation, run_token=run_token,
                status='running', lease_expires_at__gt=now,
            ).values('shared_lease_task_id', 'shared_lease_token').first()
            if lease_snapshot is None:
                return False
            # CAS is the first write; a stale finally may not release a newer
            # run's shared lease or overwrite cancellation/success.
            changed = ChatGPTTranslationTask.objects.filter(
                pk=task_id, generation=generation, run_token=run_token,
                status='running', lease_expires_at__gt=now,
            ).update(
                status='failed', error_code=code, error_message=message,
                finished_at=now, run_token=None, lease_expires_at=None, updated_at=now,
            )
            if changed and lease_snapshot['shared_lease_task_id'] is not None:
                TranslationLease(
                    lease_snapshot['shared_lease_task_id'], lease_snapshot['shared_lease_token'],
                ).finish('failed')
            return bool(changed)
    except Exception as finish_exc:
        logger.info('ChatGPT translation failure state was not saved (%s).', type(finish_exc).__name__)
        return False

def _run_persistent_task(task_id, generation):
    close_old_connections()
    key = (str(task_id), int(generation))
    run_token = uuid.uuid4()
    claimed = False
    try:
        try:
            queued_task = _queued_task_snapshot(task_id, generation)
        except Exception as exc:
            code, message = _safe_error(exc)
            try:
                _fail_queued_task(
                    task_id, generation, error_code=code, error_message=message,
                )
            except Exception as finish_exc:
                logger.info('ChatGPT queued translation state was not saved (%s).', type(finish_exc).__name__)
            logger.info('ChatGPT article translation job ended before claim (%s).', type(exc).__name__)
            return
        if queued_task is None:
            return
        now = timezone.now()
        claim_query = ChatGPTTranslationTask.objects.filter(
            pk=task_id, generation=generation, status='queued',
            model_slug=queued_task.model_slug,
            user__is_active=True,
            news__full_content=queued_task.news.full_content,
            news__full_content__gt='',
        )
        if queued_task.ai_connection_id is not None:
            claim_query = claim_query.filter(
                connection__isnull=True,
                ai_connection_id=queued_task.ai_connection_id,
                credential_epoch=queued_task.credential_epoch,
                credential_version=queued_task.credential_version,
                ai_connection__user_id=F('user_id'),
                ai_connection__is_enabled=True,
                ai_connection__is_deleted=False,
                ai_connection__credential_epoch=F('credential_epoch'),
                ai_connection__credential_version=F('credential_version'),
                source_hash=queued_task.source_hash,
                source_snapshot=queued_task.source_snapshot,
            )
        else:
            claim_query = claim_query.filter(
                connection_id=queued_task.connection_id,
                connection_generation=queued_task.connection_generation,
                ai_connection__isnull=True,
                connection__user_id=F('user_id'),
                connection__is_active=True,
                connection__needs_reauth=False,
                connection__generation=F('connection_generation'),
                connection__selected_model=F('model_slug'),
                connection__encrypted_access_token__gt='',
                connection__encrypted_refresh_token__gt='',
            )
        claimed = claim_query.update(
            status='running', run_token=run_token, provider_started=False,
            started_at=now, lease_expires_at=now + TASK_LEASE_TTL,
            error_code='', error_message='', finished_at=None, updated_at=now,
        )
        if not claimed:
            return
        task = ChatGPTTranslationTask.objects.select_related(
            'user', 'connection', 'ai_connection', 'news',
        ).get(pk=task_id)
        shared_lease = _lease_from_task(task)
        _task_snapshot(task_id, generation, run_token, require_started=False)
        guard = _execution_guard(task_id, generation, run_token)
        with _task_heartbeat(task_id, generation, run_token, shared_lease):
            if task.ai_connection_id is not None:
                snapshot = _byok_snapshot_from_task(task)
                execution = prepare_byok_translation_execution(snapshot)
                _mark_provider_started(task_id, generation, run_token)
                guard()
                output = stream_byok_translation(
                    execution,
                    task.source_snapshot,
                    on_delta=lambda delta: _append_delta(task_id, generation, run_token, delta),
                    execution_guard=guard,
                )
            else:
                _mark_provider_started(task_id, generation, run_token)
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
        logger.info('ChatGPT article translation job ended without a saved result (%s).', type(exc).__name__)
        if claimed:
            _mark_failed(task_id, generation, run_token, exc)
        else:
            code, message = _safe_error(exc)
            try:
                _fail_queued_task(
                    task_id, generation, error_code=code, error_message=message,
                )
            except Exception as finish_exc:
                logger.info('ChatGPT queued translation state was not saved (%s).', type(finish_exc).__name__)
    finally:
        close_old_connections()
        with _jobs_lock:
            _dispatching.discard(key)

def _cancel_task_in_transaction(task_id, user_id, generation):
    with transaction.atomic():
        while True:
            snapshot = ChatGPTTranslationTask.objects.filter(
                pk=task_id, user_id=user_id,
            ).values(
                'generation', 'run_token', 'status',
                'shared_lease_task_id', 'shared_lease_token',
            ).first()
            if snapshot is None:
                return None, False
            if snapshot['generation'] != generation:
                raise SubscriptionError(
                    GENERATION_CHANGED_MESSAGE, 'task_generation_changed', 409,
                )
            if snapshot['status'] not in {'queued', 'running'}:
                task = ChatGPTTranslationTask.objects.filter(
                    pk=task_id, user_id=user_id, generation=generation,
                ).first()
                return task, False
            now = timezone.now()
            updated = ChatGPTTranslationTask.objects.filter(
                pk=task_id, user_id=user_id, generation=generation,
                run_token=snapshot['run_token'], status=snapshot['status'],
                status__in=['queued', 'running'],
            ).update(
                status='cancelled', error_code='cancelled',
                error_message='翻译任务已取消。', finished_at=now,
                run_token=None, lease_expires_at=None, updated_at=now,
            )
            if updated:
                if snapshot['shared_lease_task_id'] is not None:
                    TranslationLease(
                        snapshot['shared_lease_task_id'], snapshot['shared_lease_token'],
                    ).finish('failed')
                task = ChatGPTTranslationTask.objects.filter(
                    pk=task_id, user_id=user_id, generation=generation,
                ).first()
                return task, True
            # A queued worker may have claimed between the read and CAS. Read
            # the current generation/token and retry cancellation without ever
            # touching a lease from a newer force generation.


def cancel_task(task_id, *, user_id, generation):
    """Cancel only the requested generation and revoke only its stored lease snapshot."""
    if type(generation) is not int or not 1 <= generation <= 9223372036854775807:
        raise SubscriptionError('generation 必须是正整数。', 'invalid_generation', 400)
    try:
        return _cancel_task_in_transaction(task_id, user_id, generation)
    except OperationalError:
        raise SubscriptionError(
            '任务状态暂时不可用，请稍后重试。', 'task_storage_busy', 503,
        ) from None

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
