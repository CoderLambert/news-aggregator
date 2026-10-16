"""Single-process ORM shell. No engine requests, ingestion, or model imports."""
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
import time

from django.conf import settings
from django.core.management.base import CommandError
from django.db import close_old_connections


def probe():
    if os.environ.get('NEWSHUB_RUNTIME_ROLE') != 'rss_sync':
        raise CommandError('rss_runtime requires NEWSHUB_RUNTIME_ROLE=rss_sync.')
    from api.rss.models import FeedSyncState
    FeedSyncState.objects.count()
    return {'role': 'rss_sync', 'mode': 'orm_shell', 'orm_available': True,
            'sync_ready': False, 'worker_integrated': False}


def run(*, once=False, healthcheck=False):
    status = probe()
    if once:
        return json.dumps(status, sort_keys=True)
    root = Path(os.environ.get('RSS_RUNTIME_DIR', '/var/lib/newshub/rss-runtime'))
    heartbeat = root / 'heartbeat.json'
    if healthcheck:
        try:
            state = json.loads(heartbeat.read_text())
            age = time.time() - state['timestamp']
            if state['role'] != 'rss_sync' or state['mode'] != 'orm_shell' or not 0 <= age <= 60:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError('RSS ORM shell heartbeat is missing or stale.') from None
        return json.dumps(status, sort_keys=True)

    root.mkdir(parents=True, exist_ok=True)
    lock_path = Path(settings.DATABASES['default']['NAME']).parent / '.rss-sync.lock'
    with lock_path.open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CommandError('Another rss-sync process owns this SQLite directory.') from None
        stopped = threading.Event()
        previous = {number: signal.signal(number, lambda *_: stopped.set())
                    for number in (signal.SIGTERM, signal.SIGINT)}
        try:
            while not stopped.is_set():
                status = probe()
                temporary = root / 'heartbeat.tmp'
                temporary.write_text(json.dumps({**status, 'timestamp': time.time()}))
                temporary.replace(heartbeat)
                close_old_connections()
                stopped.wait(20)
        finally:
            heartbeat.unlink(missing_ok=True)
            for number, handler in previous.items():
                signal.signal(number, handler)
    return json.dumps({**status, 'stopped': True}, sort_keys=True)
