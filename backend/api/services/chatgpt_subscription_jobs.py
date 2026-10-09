"""Per-user/account full-article streaming jobs for subscription translations."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from django.db import close_old_connections

from api.models import ChatGPTSubscriptionConnection, News
from api.services.chatgpt_subscription import (
    SubscriptionError,
    save_completed_translation,
    source_hash,
    stream_full_translation,
)
from api.services.shared_translations import keep_lease_alive, result_payload

logger = logging.getLogger(__name__)


class ChatGPTTranslationJob:
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
            self._condition.wait(timeout=timeout)
            return len(self.text)


_jobs: dict[tuple, ChatGPTTranslationJob] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chatgpt-translation')
_JOB_TTL_SECONDS = 30 * 60


def _job_key(user_id, connection_id, news_id, source_digest):
    return (int(user_id), str(connection_id), int(news_id), source_digest)


def _gc_jobs() -> None:
    now = time.time()
    for key, job in list(_jobs.items()):
        if job.done and now - job.started_at > _JOB_TTL_SECONDS:
            _jobs.pop(key, None)


def get_job(user_id, connection_id, news_id, source_digest=None):
    with _jobs_lock:
        _gc_jobs()
        if source_digest is not None:
            return _jobs.get(_job_key(user_id, connection_id, news_id, source_digest))
        prefix = (int(user_id), str(connection_id), int(news_id))
        return next((job for key, job in _jobs.items() if key[:3] == prefix and not job.done), None)


def _run_job(job, *, user_id, connection_id, news_id, source_digest, generation, model_slug, article_markdown, shared_lease):
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
            shared_lease.finish('failed')  # CAS leaves successful/replaced leases untouched.
        close_old_connections()


def start_or_get_job(user, connection: ChatGPTSubscriptionConnection, news: News, *, shared_lease=None):
    source_digest = source_hash(news.full_content)
    key = _job_key(user.pk, connection.pk, news.pk, source_digest)
    with _jobs_lock:
        _gc_jobs()
        existing = _jobs.get(key)
        if existing and not existing.done and (
            shared_lease is None or getattr(existing, 'shared_lease', None) == shared_lease
        ):
            return existing
        if not connection.selected_model:
            raise SubscriptionError('请先在订阅设置中选择可见模型。')
        job = ChatGPTTranslationJob(key)
        job.shared_lease = shared_lease
        _jobs[key] = job
        _executor.submit(
            _run_job,
            job,
            user_id=user.pk,
            connection_id=connection.pk,
            news_id=news.pk,
            source_digest=source_digest,
            generation=connection.generation,
            model_slug=connection.selected_model,
            article_markdown=news.full_content,
            shared_lease=shared_lease,
        )
        return job
