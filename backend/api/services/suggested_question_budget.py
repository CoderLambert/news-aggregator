"""Bounded, user-owned suggested question calls, without a new task platform.

SQLite's existing AuthRateBucket+AuthSecurityLock provides a process-wide
hard cap on starts; the local semaphore keeps synchronous model IO from
occupying an unbounded number of web threads in one process.
"""
from contextlib import contextmanager
from threading import BoundedSemaphore

from api.services.account_security import _reserve_buckets

# Conservative starting budgets. These count attempted calls, not provider
# tokens or costs; the UI makes no guarantees about a provider's billing.
USER_PER_DAY = 20
GLOBAL_PER_DAY = 120
USER_REFRESH_PER_HOUR = 4
MAX_INFLIGHT_PER_PROCESS = 2
_slots = BoundedSemaphore(MAX_INFLIGHT_PER_PROCESS)


class SuggestionCapacityBusy(Exception):
    retry_after = 15


@contextmanager
def reserve_suggestion_generation(user_id: int, *, news_id: int, revision: int, force: bool = False):
    if not _slots.acquire(blocking=False):
        raise SuggestionCapacityBusy()
    try:
        specs = [
            ('suggestion_user_daily', str(user_id), USER_PER_DAY, 86400),
            ('suggestion_global_daily', 'all', GLOBAL_PER_DAY, 86400),
            # The first user to start this article revision owns a short
            # generation window. Other accounts cannot start a duplicate
            # paid request while the cache is still being populated.
            ('suggestion_article_revision', f'{news_id}:{revision}', 1, 120),
        ]
        if force:
            specs.append(('suggestion_user_refresh', str(user_id), USER_REFRESH_PER_HOUR, 3600))
        # Atomic durable reservation before billable network IO.
        _reserve_buckets(specs)
        yield
    finally:
        _slots.release()
