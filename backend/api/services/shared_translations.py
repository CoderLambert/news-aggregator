"""Completed public copies and fenced, cross-process translation leases."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import logging
import threading
import time
import uuid

from django.db import close_old_connections, transaction
from django.db.models import Q
from django.http import StreamingHttpResponse
from api.translation_sse import translation_sse_records
from django.utils import timezone

from api.models import News, SharedArticleTranslation, SharedArticleTranslationTask
from api.services.stored_readers import article_snapshot, require_current

logger = logging.getLogger(__name__)
TARGET_LANGUAGE = 'zh-CN'
TRANSLATION_VERSION = 'article-v1'
LEASE_TTL = timedelta(seconds=90)
MAX_RUN_TIME = timedelta(minutes=30)
# Limits include all users, processes, and active leased tasks in the same
# production SQLite database. A deliberate capacity rejection never starts LLM IO.
MAX_CONCURRENT_TRANSLATIONS = 2
MAX_CONCURRENT_PER_USER = 1


class SharedTranslationError(Exception):
    pass


class SharedTranslationBusy(SharedTranslationError):
    """Capacity denied before any provider call; a caller may try later."""

    retry_after_seconds = 30


def source_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def cache_key(news_id, digest):
    return dict(news_id=news_id, source_hash=digest, target_language=TARGET_LANGUAGE,
                translation_version=TRANSLATION_VERSION)


def get_shared_translation(news, user=None, *, stored=None):
    stored = stored or article_snapshot(news, user)
    require_current(user if user is not None else getattr(news, '_rss_access_user', None), stored)
    if stored.scope != 'full':
        return None
    return SharedArticleTranslation.objects.filter(
        **cache_key(news.pk, stored.canonical_hash),
    ).first()


def task_is_running(news, user=None, *, stored=None):
    stored = stored or article_snapshot(news, user)
    require_current(user if user is not None else getattr(news, '_rss_access_user', None), stored)
    if stored.scope != 'full':
        return False
    now = timezone.now()
    return SharedArticleTranslationTask.objects.filter(
        **cache_key(news.pk, stored.canonical_hash), status='running',
        expires_at__gt=now, started_at__gt=now - MAX_RUN_TIME,
    ).exists()


@dataclass(frozen=True)
class TranslationLease:
    task_id: int
    token: uuid.UUID

    def current(self):
        now = timezone.now()
        return SharedArticleTranslationTask.objects.filter(
            pk=self.task_id, lease_token=self.token, status='running',
            expires_at__gt=now, started_at__gt=now - MAX_RUN_TIME,
        )

    def finish(self, status):
        self.current().update(status=status, updated_at=timezone.now())


def claim_task(news, *, user_id=None, stored=None):
    """Select one generator and enforce SQLite-wide active-work quotas.

    An initial write reserves SQLite's database writer lock before counting
    active leases, so simultaneous requests for distinct articles cannot both
    observe an empty global budget. No network/model calls occur under this lock.
    """
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first() if user_id else None
    current = article_snapshot(news, user)
    if current.scope != 'full' or (stored is not None and current != stored):
        raise SharedTranslationError('full_content_not_ready')
    stored = current
    digest = stored.canonical_hash
    if get_shared_translation(news, user, stored=stored) is not None:
        return None
    task, _ = SharedArticleTranslationTask.objects.get_or_create(**cache_key(news.pk, digest))
    now = timezone.now()
    token = uuid.uuid4()
    with transaction.atomic():
        # Unlike select_for_update(), an UPDATE obtains an actual SQLite writer
        # reservation; use a short transaction across admission and CAS.
        SharedArticleTranslationTask.objects.filter(pk=task.pk).update(updated_at=now)
        active = SharedArticleTranslationTask.objects.filter(
            status='running', expires_at__gt=now, started_at__gt=now - MAX_RUN_TIME)
        if active.filter(pk=task.pk).exists():
            return None
        if active.count() >= MAX_CONCURRENT_TRANSLATIONS:
            raise SharedTranslationBusy('同时处理的文章翻译过多，请稍后重试。')
        if user_id is not None and active.filter(initiated_by_id=user_id).count() >= MAX_CONCURRENT_PER_USER:
            raise SharedTranslationBusy('您当前已有文章翻译正在处理，请稍后重试。')
        won = SharedArticleTranslationTask.objects.filter(pk=task.pk).filter(
            ~Q(status='running') | Q(expires_at__lte=now) | Q(started_at__lte=now - MAX_RUN_TIME),
        ).update(status='running', lease_token=token, initiated_by_id=user_id,
                 started_at=now, expires_at=now + LEASE_TTL, updated_at=now)
    if not won:
        return None
    lease = TranslationLease(task.pk, token)
    # The previous owner may have completed between our initial read and CAS.
    if get_shared_translation(news, user, stored=stored) is not None:
        lease.finish('succeeded')
        return None
    return lease


@contextmanager
def keep_lease_alive(lease):
    if lease is None:
        yield
        return
    if not lease.current().exists():
        raise SharedTranslationError('共享翻译任务已过期，请重新开始。')
    stopped = threading.Event()

    def heartbeat():
        close_old_connections()
        try:
            while not stopped.wait(20):
                now = timezone.now()
                try:
                    updated = lease.current().filter(started_at__gt=now - MAX_RUN_TIME).update(
                        expires_at=now + LEASE_TTL, updated_at=now,
                    )
                    if not updated:
                        return
                except Exception:
                    # A transient DB lock must not extend or resurrect an expired lease.
                    logger.warning('Shared translation heartbeat failed; lease may expire.')
                finally:
                    close_old_connections()
        finally:
            close_old_connections()

    worker = threading.Thread(target=heartbeat, daemon=True, name='translation-lease')
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=2)


def publish_translation(*, news_id, digest, text, provider, model_slug='', lease=None):
    """Publish only a whole result. First valid publication wins permanently."""
    if not text.strip():
        raise SharedTranslationError('本次翻译没有返回完整结果。')
    with transaction.atomic():
        if lease is not None and not lease.current().update(
            status='succeeded', updated_at=timezone.now(),
        ):
            raise SharedTranslationError('共享翻译任务已过期，请重新开始。')
        # Versioned records are immutable history; current readers select by hash.
        # Do not overwrite News compatibility fields or a newer source version.
        record, _ = SharedArticleTranslation.objects.get_or_create(
            **cache_key(news_id, digest),
            defaults=dict(content=text, provider=provider, model_slug=model_slug,
                          completed_at=timezone.now()),
        )
        current_text = News.objects.filter(pk=news_id).values_list('full_content', flat=True).get()
        stale = source_hash(current_text) != digest
    if stale:
        # The immutable old-hash result remains history; it is never a current result.
        raise SharedTranslationError('原文已更新，旧译文已保存为历史，请重新翻译。')
    return record


def result_payload(record, scope='shared'):
    return {
        'full_content_zh': record.content,
        'full_content_zh_fetched_at': record.completed_at.isoformat(),
        'full_content_zh_source': getattr(record, 'provider', 'chatgpt'),
        'full_content_zh_scope': scope,
    }


def sse_response(stream):
    response = StreamingHttpResponse(stream, content_type='text/event-stream')
    response['Cache-Control'] = 'private, no-store'
    response['X-Accel-Buffering'] = 'no'
    return response


def completed_response(record, scope='shared', *, user=None, stored=None):
    def stream():
        if stored is not None:
            require_current(user, stored, full=True)
            if scope == 'private':
                from api.services.chatgpt_subscription import active_connection_for_user
                connection = active_connection_for_user(user)
                if connection is None or connection.pk != record.connection_id:
                    raise SharedTranslationError('翻译连接已变化。')
        yield from translation_sse_records(result_payload(record, scope), event='complete')
    return sse_response(stream())


def error_response(message, *, error_code=''):
    data = json.dumps({'error': message, **({'error_code': error_code} if error_code else {})}, ensure_ascii=False)
    return sse_response(iter([f'data: {data}\n\n']))


def waiting_response(news, user=None, *, stored=None):
    """Other readers see only the completed public copy, never private chunks."""
    stored = stored or article_snapshot(news, user)
    digest = stored.canonical_hash
    key = cache_key(news.pk, digest)

    def stream():
        try:
            deadline = time.monotonic() + MAX_RUN_TIME.total_seconds()
            while time.monotonic() < deadline:
                require_current(user, stored, full=True)
                record = SharedArticleTranslation.objects.filter(**key).first()
                if record is not None:
                    yield from translation_sse_records(result_payload(record), event='complete')
                    return
                task = SharedArticleTranslationTask.objects.filter(**key).first()
                now = timezone.now()
                if (task is None or task.status != 'running' or task.expires_at <= now
                        or task.started_at <= now - MAX_RUN_TIME):
                    message = '共享译文生成失败或已超时，请重试。'
                    break
                yield 'data: {"waiting_shared":true}\n\n'
                time.sleep(1)
            else:
                message = '等待共享译文超时，请重试。'
            yield f'data: {json.dumps({"error": message}, ensure_ascii=False)}\n\n'
        except GeneratorExit:
            return
        except Exception:
            yield 'data: {"error":"原文或读取权限已变化。"}\n\n'

    return sse_response(stream())
