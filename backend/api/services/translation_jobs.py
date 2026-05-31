"""In-process background translation job manager.

Decouples the LLM streaming work from the HTTP request lifecycle so that
clients refreshing/closing the SSE connection does NOT kill the underlying
translation. The worker thread continues consuming the LLM stream and
persists progress to the DB; subsequent HTTP requests (re-open, refresh,
poll) attach to the same in-memory job and stream its accumulated output.

Public API:
    start_or_get_job(news_id, prompt, on_save) -> Job
    get_job(news_id) -> Job | None

Each Job exposes:
    .text           current accumulated text
    .done           bool — worker finished (success or error)
    .error          str  — error message if any
    .wait_for_update(last_len, timeout) -> int — block until len(text) > last_len
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TranslationJob:
    def __init__(self, news_id: int):
        self.news_id = news_id
        self.text = ''
        self.done = False
        self.error: Optional[str] = None
        self.started_at = time.time()
        self._cond = threading.Condition()

    def _append(self, chunk: str) -> None:
        with self._cond:
            self.text += chunk
            self._cond.notify_all()

    def _finish(self, error: Optional[str] = None) -> None:
        with self._cond:
            self.done = True
            self.error = error
            self._cond.notify_all()

    def wait_for_update(self, last_len: int, timeout: float = 1.0) -> int:
        """Block (up to `timeout` s) until len(self.text) > last_len or done.
        Returns the new length.
        """
        with self._cond:
            if len(self.text) > last_len or self.done:
                return len(self.text)
            self._cond.wait(timeout=timeout)
            return len(self.text)


# news_id -> Job (only one active per article)
_jobs: dict[int, TranslationJob] = {}
_jobs_lock = threading.Lock()

# Max age before a finished job is forgotten
_JOB_TTL_SECONDS = 60 * 30


def _gc_jobs() -> None:
    now = time.time()
    stale = [
        nid for nid, j in _jobs.items()
        if j.done and (now - j.started_at) > _JOB_TTL_SECONDS
    ]
    for nid in stale:
        _jobs.pop(nid, None)


def get_job(news_id: int) -> Optional[TranslationJob]:
    with _jobs_lock:
        return _jobs.get(news_id)


def start_or_get_job(
    news_id: int,
    prompt: str,
    on_save: Callable[[str, bool], None],
    save_every_chars: int = 500,
) -> TranslationJob:
    """Return existing in-flight job for this news_id, or start a new one.

    on_save(current_text, is_final) is called from the worker thread to
    persist progress to the DB. It receives:
      - current_text: accumulated translation so far
      - is_final:     True only on the final save after the stream ends OK
    """
    with _jobs_lock:
        _gc_jobs()
        existing = _jobs.get(news_id)
        if existing and not existing.done:
            logger.info(f"Attaching to existing translation job for news {news_id}")
            return existing

        job = TranslationJob(news_id)
        _jobs[news_id] = job

    def _worker() -> None:
        # Import here to avoid Django app-loading order surprises
        from api.services.llm_translator import _call_llm_stream

        last_saved_len = 0
        try:
            for chunk in _call_llm_stream(prompt):
                if not chunk:
                    continue
                # Detect provider-level errors flowing through the stream.
                # Old format: "Error: ..." | New format: "抱歉，AI 服务暂时不可用..."
                is_error = (
                    chunk.startswith('Error:')
                    or chunk.startswith('抱歉，AI 服务暂时不可用')
                )
                if is_error and not job.text:
                    job._finish(error=chunk)
                    return

                job._append(chunk)

                if len(job.text) - last_saved_len >= save_every_chars:
                    try:
                        on_save(job.text, False)
                        last_saved_len = len(job.text)
                    except Exception as save_err:
                        logger.warning(f"Progress save failed (news={news_id}): {save_err}")

            # Stream finished normally — final save
            if job.text and not job.text.startswith(('Error:', '抱歉，AI 服务暂时不可用')):
                try:
                    on_save(job.text, True)
                except Exception as save_err:
                    logger.error(f"Final save failed (news={news_id}): {save_err}")
                job._finish()
            else:
                job._finish(error=job.text or '翻译返回为空')
        except Exception as e:
            logger.exception(f"Translation worker crashed (news={news_id})")
            job._finish(error=str(e))

    t = threading.Thread(target=_worker, name=f"translate-{news_id}", daemon=True)
    t.start()
    return job
