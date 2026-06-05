"""In-process background research job manager.

Mirrors the translation_jobs.py pattern: decouples the agent loop from the
HTTP request lifecycle so client disconnects do NOT kill the running agent.
The worker thread continues executing tools and persisting progress; SSE
requests re-attach to the same in-memory job to stream accumulated events.

Public API:
    start_or_get_research_job(session_id, session, user_query) -> ResearchJob
    get_research_job(session_id) -> ResearchJob | None

Each ResearchJob exposes:
    .events         list of (event_type, data) tuples
    .done           bool — worker finished (success or error)
    .error          str  — error message if any
    .push_event(event_type, data) — called by the agent loop
    .wait_for_events(last_index, timeout) -> int — block until new events arrive
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class ResearchJob:
    """Tracks a running research agent loop and its event stream."""

    def __init__(self, session_id: UUID | str):
        self.session_id = str(session_id)
        self.events: list[tuple[str, dict]] = []
        self.done = False
        self.error: Optional[str] = None
        self.started_at = time.time()
        self._cond = threading.Condition()

    def push_event(self, event_type: str, data: dict) -> None:
        """Append an event and wake up any SSE consumer waiting for it."""
        with self._cond:
            self.events.append((event_type, data))
            self._cond.notify_all()

    def _finish(self, error: Optional[str] = None) -> None:
        """Mark the job as done (optionally with error)."""
        with self._cond:
            self.done = True
            self.error = error
            self._cond.notify_all()

    def wait_for_events(self, last_index: int, timeout: float = 1.0) -> int:
        """Block (up to `timeout` s) until new events beyond last_index or done.

        Returns the current total number of events.
        """
        with self._cond:
            if len(self.events) > last_index or self.done:
                return len(self.events)
            self._cond.wait(timeout=timeout)
            return len(self.events)


# session_id -> ResearchJob (only one active per session)
_jobs: dict[str, ResearchJob] = {}
_jobs_lock = threading.Lock()

# Max age before a finished job is forgotten
_JOB_TTL_SECONDS = 60 * 30


def _gc_jobs() -> None:
    """Remove finished jobs older than TTL."""
    now = time.time()
    stale = [
        sid for sid, j in _jobs.items()
        if j.done and (now - j.started_at) > _JOB_TTL_SECONDS
    ]
    for sid in stale:
        _jobs.pop(sid, None)


def get_research_job(session_id: UUID | str) -> Optional[ResearchJob]:
    """Get an existing research job by session ID."""
    with _jobs_lock:
        return _jobs.get(str(session_id))


def start_or_get_research_job(session_id: UUID | str, session, user_query: str, local_only: bool = False) -> ResearchJob:
    """Return existing in-flight job for this session, or start a new one.

    Args:
        session_id: The ResearchSession UUID.
        session: The ResearchSession model instance (will be mutated by the agent loop).
        user_query: The user's research question.
        local_only: When True, restrict to local news database only (no web search).

    Returns:
        A ResearchJob instance whose events can be polled via wait_for_events().
    """
    sid = str(session_id)

    with _jobs_lock:
        _gc_jobs()
        existing = _jobs.get(sid)
        if existing and not existing.done:
            logger.info('Attaching to existing research job for session %s', sid[:8])
            return existing

        job = ResearchJob(sid)
        _jobs[sid] = job

    def _worker() -> None:
        from .agent_loop import run_agent_loop

        try:
            run_agent_loop(session, user_query, job.push_event, local_only=local_only)
        except Exception as e:
            logger.exception('Research worker crashed (session=%s)', sid[:8])
            job.push_event('error', {'message': str(e)})
        finally:
            job._finish()

    t = threading.Thread(target=_worker, name=f'research-{sid[:8]}', daemon=True)
    t.start()
    return job
