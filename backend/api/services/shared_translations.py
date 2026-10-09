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
from django.utils import timezone

from api.models import News, SharedArticleTranslation, SharedArticleTranslationTask

logger = logging.getLogger(__name__)
TARGET_LANGUAGE = 'zh-CN'
TRANSLATION_VERSION = 'article-v1'
LEASE_TTL = timedelta(seconds=90)
MAX_RUN_TIME = timedelta(minutes=30)


class SharedTranslationError(Exception):
    pass


def source_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def cache_key(news_id, digest):
    return dict(news_id=news_id, source_hash=digest, target_language=TARGET_LANGUAGE,
                translation_version=TRANSLATION_VERSION)


def get_shared_translation(news):
    if not news.full_content:
        return None
    return SharedArticleTranslation.objects.filter(
        **cache_key(news.pk, source_hash(news.full_content)),
    ).first()


def task_is_running(news):
    now = timezone.now()
    return SharedArticleTranslationTask.objects.filter(
        **cache_key(news.pk, source_hash(news.full_content)), status='running',
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


def claim_task(news):
    """An atomic CAS, rather than a process lock, elects exactly one generator."""
    digest = source_hash(news.full_content)
    if get_shared_translation(news) is not None:
        return None
    task, _ = SharedArticleTranslationTask.objects.get_or_create(**cache_key(news.pk, digest))
    now = timezone.now()
    token = uuid.uuid4()
    won = SharedArticleTranslationTask.objects.filter(pk=task.pk).filter(
        ~Q(status='running') | Q(expires_at__lte=now) | Q(started_at__lte=now - MAX_RUN_TIME),
    ).update(status='running', lease_token=token, started_at=now,
             expires_at=now + LEASE_TTL, updated_at=now)
    if not won:
        return None
    lease = TranslationLease(task.pk, token)
    # The previous owner may have completed between our initial read and CAS.
    if get_shared_translation(news) is not None:
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
        news = News.objects.select_for_update().only('full_content').get(pk=news_id)
        if source_hash(news.full_content) != digest:
            raise SharedTranslationError('原文已更新，旧译文没有发布，请重新翻译。')
        record, _ = SharedArticleTranslation.objects.get_or_create(
            **cache_key(news_id, digest),
            defaults=dict(content=text, provider=provider, model_slug=model_slug,
                          completed_at=timezone.now()),
        )
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
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


def completed_response(record, scope='shared'):
    data = json.dumps(result_payload(record, scope), ensure_ascii=False)
    return sse_response(iter([f'event: complete\ndata: {data}\n\n']))


def error_response(message):
    data = json.dumps({'error': message}, ensure_ascii=False)
    return sse_response(iter([f'data: {data}\n\n']))


def waiting_response(news):
    """Other readers see only the completed public copy, never private chunks."""
    digest = source_hash(news.full_content)
    key = cache_key(news.pk, digest)

    def stream():
        try:
            deadline = time.monotonic() + MAX_RUN_TIME.total_seconds()
            while time.monotonic() < deadline:
                current_source = News.objects.values_list('full_content', flat=True).get(pk=news.pk)
                if source_hash(current_source) != digest:
                    message = '原文已更新，请重新开始翻译。'
                    break
                record = SharedArticleTranslation.objects.filter(**key).first()
                if record is not None:
                    data = json.dumps(result_payload(record), ensure_ascii=False)
                    yield f'event: complete\ndata: {data}\n\n'
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

    return sse_response(stream())
