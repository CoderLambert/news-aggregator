import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings as django_settings


class SearchIndexExecutionLockUnavailable(Exception):
    pass


def search_index_execution_lock_path():
    default_path = (
        Path(django_settings.BASE_DIR).parent
        / 'logs'
        / 'embedding-worker.lock'
    )
    return Path(os.environ.get('SEARCH_INDEX_WORKER_LOCK', default_path))


@contextmanager
def acquire_search_index_execution_lock(*, blocking=False):
    """Hold the single execution lease shared by the Worker and CLI."""
    lock_path = search_index_execution_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open('a+')
    operation = fcntl.LOCK_EX
    if not blocking:
        operation |= fcntl.LOCK_NB
    try:
        fcntl.flock(lock_handle.fileno(), operation)
    except BlockingIOError as exc:
        lock_handle.close()
        raise SearchIndexExecutionLockUnavailable() from exc
    try:
        yield lock_path
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()
