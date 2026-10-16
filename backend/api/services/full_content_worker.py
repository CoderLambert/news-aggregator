"""Single process ownership, observable liveness and fair durable task polling."""
from collections import deque
from contextlib import AbstractContextManager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from django.conf import settings
from django.db import close_old_connections, connection
from django.utils import timezone

from api.models import News
from api.services.full_content_status import claim_fetch, mark_success, mark_failed, release_fetch_claim, fetch_eligibility
from api.services.article_fetcher.execution import ExecutionStopped


class WorkerAlreadyRunning(RuntimeError):
    pass


def worker_health(*, require_enabled=False, max_age=60):
    """A fresh heartbeat must belong to the process holding the shared flock."""
    if require_enabled and not settings.FULL_CONTENT_WORKER_ENABLED:
        return False
    try:
        with open(settings.FULL_CONTENT_WORKER_HEARTBEAT, 'r') as stream:
            payload = json.loads(stream.read(4097))
        if (not isinstance(payload, dict) or type(payload.get('version')) is not int or payload['version'] != 1 or
                payload.get('db_ok') is not True or type(payload.get('enabled')) is not bool or
                type(payload.get('timestamp')) not in {int, float} or
                type(payload.get('loop_seen_at')) not in {int, float} or
                type(payload.get('owner')) is not str):
            return False
        age = time.time() - payload['timestamp']
        if not (0 <= age <= max_age and payload['db_ok'] and
                0 <= time.time() - payload['loop_seen_at'] <= 90):
            return False
        if require_enabled and payload['enabled'] is not True:
            return False
        with open(settings.FULL_CONTENT_WORKER_LOCK, 'r+') as lock:
            if lock.read(256).strip() != payload['owner']:
                return False
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(lock, fcntl.LOCK_UN)
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False


class WorkerRuntime(AbstractContextManager):
    def __init__(self, stop_event, *, heartbeat_interval=10):
        self.stop_event = stop_event
        self.interval = heartbeat_interval
        self.owner = uuid.uuid4().hex
        self.loop_seen_at = time.time()
        self.closed = threading.Event()
        self.lock = None

    def __enter__(self):
        path = Path(settings.FULL_CONTENT_WORKER_LOCK)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = path.open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            raise WorkerAlreadyRunning('full_content_worker_already_running') from None
        self.lock.seek(0)
        self.lock.truncate()
        self.lock.write(self.owner)
        self.lock.flush()
        try:
            self.heartbeat()
        except Exception:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None
            raise
        self.thread = threading.Thread(target=self._heartbeats, name='full-content-heartbeat', daemon=True)
        self.thread.start()
        return self

    def heartbeat(self):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                db_ok = cursor.fetchone() == (1,)
        except Exception:
            db_ok = False
        finally:
            close_old_connections()
        path = Path(settings.FULL_CONTENT_WORKER_HEARTBEAT)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(version=1, owner=self.owner, pid=os.getpid(), timestamp=time.time(),
                       loop_seen_at=self.loop_seen_at, enabled=settings.FULL_CONTENT_WORKER_ENABLED, db_ok=db_ok)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', delete=False) as stream:
                temporary = stream.name
                json.dump(payload, stream)
                stream.flush()
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _heartbeats(self):
        while not self.closed.wait(self.interval):
            try:
                self.heartbeat()
            except OSError:
                # A write failure makes freshness expire; never claim healthy.
                pass

    def guard(self):
        self.loop_seen_at = time.time()
        if self.stop_event.is_set():
            raise ExecutionStopped('canceled')

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < end:
            self.loop_seen_at = time.time()
            self.stop_event.wait(min(self.interval, max(0, end - time.monotonic())))

    def __exit__(self, *args):
        self.closed.set()
        self.thread.join(timeout=1)
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()


class FairQueue:
    def __init__(self):
        self.sources = deque()

    def due(self, limit=10):
        limit = max(1, min(10, limit))
        query = News.objects.filter(full_content_next_attempt_at__lte=timezone.now(),
            full_content_fetch_status__in=('queued', 'rate_limited', 'network_error', 'failed'),
            full_content_retry_count__lt=5).select_related('source', 'category')
        present = set(query.order_by().values_list('source_id', flat=True).distinct())
        self.sources = deque(key for key in self.sources if key in present)
        self.sources.extend(sorted(present - set(self.sources)))
        result, selected, urgent_sources = [], set(), set()
        # Reader initiated work must not sit behind a large automatic
        # backfill. Preserve source fairness by taking at most one urgent item
        # per source in a single selection pass.
        for row in query.filter(full_content_priority=10).order_by(
                '-full_content_priority', 'full_content_next_attempt_at', 'pk')[:limit * 4]:
            if row.source_id in urgent_sources:
                continue
            selected.add(row.pk)
            urgent_sources.add(row.source_id)
            result.append(row)
            if row.source_id in self.sources:
                while self.sources[0] != row.source_id:
                    self.sources.rotate(-1)
                self.sources.rotate(-1)
            if len(result) >= limit:
                return result
        exhausted = set()
        while self.sources and len(result) < limit and len(exhausted) < len(self.sources):
            key = self.sources[0]
            self.sources.rotate(-1)
            if key in urgent_sources:
                exhausted.add(key)
                continue
            row = query.filter(source_id=key).exclude(pk__in=selected).order_by('-full_content_priority', 'full_content_next_attempt_at', 'pk').first()
            if row is None:
                exhausted.add(key)
            else:
                selected.add(row.pk)
                result.append(row)
        return result


def execute_one(news, *, guard=None, providers=None):
    from api.services.article_fetcher import fetch_article_markdown
    from api.services.article_fetch_monitor import record_persistence_outcome
    if guard:
        guard()
    rejection = fetch_eligibility(news)
    if rejection:
        from api.rss.legacy_fencing import legacy_news_queryset
        legacy_news_queryset(News.objects.filter(pk=news.pk, url=news.url, full_content_revision=news.full_content_revision,
                            full_content_fetch_status__in=('queued', 'rate_limited', 'network_error', 'failed'),
                            full_content_next_attempt_at__lte=timezone.now())).update(
            full_content_fetch_status='unsupported', full_content_next_attempt_at=None,
            full_content_error_code=rejection)
        return None
    if not claim_fetch(news):
        return None
    try:
        from api.services.body_access import body_fetch_scope
        with body_fetch_scope(news):
            result = fetch_article_markdown(news.url, expected_title=news.title, summary=news.content,
                                           news=news, providers=providers, execution_guard=guard)
        if guard:
            guard()
        with body_fetch_scope(news):
            committed = mark_success(news, result)
        if committed:
            record_persistence_outcome(getattr(result, 'fetch_event_id', None), 'noop' if getattr(news, '_full_content_commit_outcome', '') == 'noop' else 'committed')
            return result
        record_persistence_outcome(getattr(result, 'fetch_event_id', None), 'rejected' if getattr(news, '_full_content_commit_outcome', '') == 'rejected' else 'persistence_conflict')
        # Rejected validation or lost revision must not leave an owned task hung.
        if getattr(news, '_full_content_snapshot', None):
            mark_failed(news, ExecutionStopped('body_mismatch'), status='validation_failed')
        return None
    except ExecutionStopped as error:
        record_persistence_outcome(getattr(error, 'fetch_event_id', None), 'not_attempted', logical_outcome=error.error_code)
        if error.error_code == 'canceled':
            release_fetch_claim(news)
        elif error.error_code != 'superseded':
            mark_failed(news, error)
        return None
    except Exception as error:
        record_persistence_outcome(getattr(error, 'fetch_event_id', None), 'not_attempted', logical_outcome=getattr(error, 'error_code', '') or 'failed')
        mark_failed(news, error)
        return None
