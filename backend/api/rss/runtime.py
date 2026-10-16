"""Single RSS process: optional ORM probe or control plus bounded synchronization."""
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
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


def run(*, once=False, healthcheck=False, control=False, sync=False):
    status = probe()
    control = sync or control or os.environ.get('RSS_CONTROL_WORKER_ENABLED') == '1'
    if once and not control:
        return json.dumps(status, sort_keys=True)
    root = Path(os.environ.get('RSS_RUNTIME_DIR', '/var/lib/newshub/rss-runtime'))
    heartbeat = root / 'heartbeat.json'
    if healthcheck:
        try:
            state = json.loads(heartbeat.read_text())
            age = time.time() - state['timestamp']
            if (state['role'] != 'rss_sync' or state['mode'] not in {'orm_shell', 'control_worker', 'sync_worker'}
                    or (control and state['mode'] not in {'control_worker', 'sync_worker'})
                    or (sync and state['mode'] != 'sync_worker')
                    or state.get('control_stalled') or state.get('sync_read_stalled') or not 0 <= age <= 60):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise CommandError('RSS ORM shell heartbeat is missing or stale.') from None
        return json.dumps({**status, 'mode': state['mode'],
            'control_worker_integrated': state['mode'] in {'control_worker', 'sync_worker'},
            'worker_integrated': state['mode'] == 'sync_worker', 'sync_ready': state.get('engine_ready', False)}, sort_keys=True)

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
        worker = None
        synchronizer = None
        try:
            if control:
                from api.rss.control_worker import ControlWorker
                from api.rss.engine import EngineConfig, EngineError
                try:
                    worker = ControlWorker(EngineConfig.from_environment())
                except EngineError as error:
                    raise CommandError(error.code) from None
                status.update(mode='control_worker', control_worker_integrated=True)
                if sync:
                    from api.rss.reconciliation import SyncWorker
                    synchronizer = SyncWorker(worker, worker.config)
                if once and not sync:
                    return json.dumps({**status, 'processed': worker.run_once()}, sort_keys=True)
            stall_limit = float(os.environ.get('RSS_CONTROL_STALL_SECONDS', '120'))
            if not 1 <= stall_limit <= 3600:
                raise CommandError('RSS_CONTROL_STALL_SECONDS must be between 1 and 3600.')
            last_import = last_seed = 0
            started = time.monotonic()
            while not stopped.is_set():
                status = {**probe(), **({'mode': 'control_worker', 'control_worker_integrated': True,
                    **worker.tick()} if worker else {})}
                if synchronizer:
                    status.update(mode='sync_worker', worker_integrated=True,
                        engine_instance_uuid=str(worker.config.engine_instance_uuid),
                        account_id=worker.config.account_id, **synchronizer.tick())
                    status['sync_ready'] = status['engine_ready']
                    status['sync_read_stalled'] = status['sync_read_age_seconds'] >= stall_limit
                    now = time.monotonic()
                    if now - last_import >= 10:
                        from api.rss.opml import process_imports
                        process_imports(limit=10)
                        last_import = now
                    if now - last_seed >= 86400:
                        from api.rss.directory import import_pinned_seed
                        import_pinned_seed()
                        last_seed = now
                if worker and (status['control_age_seconds'] >= stall_limit or status.get('sync_read_stalled')):
                    # Terminate the process, including blocked HTTP threads. Docker
                    # restart policy handles the nonzero exit; remote result remains
                    # unknown and expired leases reconcile rather than reissue.
                    sys.stderr.write('rss-control-stalled: terminating process for supervised recovery\n')
                    sys.stderr.flush()
                    os._exit(75)
                temporary = root / 'heartbeat.tmp'
                temporary.write_text(json.dumps({**status, 'timestamp': time.time()}))
                temporary.replace(heartbeat)
                close_old_connections()
                if once and synchronizer:
                    if not status['initial_sync']:
                        return json.dumps(status, sort_keys=True)
                    if time.monotonic() - started >= 120:
                        raise CommandError('RSS initial synchronization did not complete within 120 seconds.')
                stopped.wait(0.05 if once else (1 if worker else 20))
        finally:
            if synchronizer:
                synchronizer.close()
            if worker:
                worker.close()
            heartbeat.unlink(missing_ok=True)
            for number, handler in previous.items():
                signal.signal(number, handler)
    return json.dumps({**status, 'stopped': True}, sort_keys=True)
