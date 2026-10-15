"""Resident executor for explicit durable tasks, including disabled liveness."""
import logging
import signal
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from api.services.full_content_status import recover_stale_fetches
from api.services.full_content_worker import FairQueue, WorkerRuntime, WorkerAlreadyRunning, execute_one

logger = logging.getLogger(__name__)
_stop_event = threading.Event()


def _signal_handler(signum, frame):
    _stop_event.set()


def _fetch_one(news, providers_chain=None):
    return execute_one(news, providers=providers_chain)


def _get_pending():
    """Compatibility helper: pending without task intent is never runnable."""
    return FairQueue().due()


def run_loop(*, stop_event=None, interval=10, batch_limit=10):
    stop = stop_event if stop_event is not None else _stop_event
    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[number] = signal.signal(number, lambda *_: stop.set())
    queue = FairQueue()
    try:
        with WorkerRuntime(stop) as runtime:
            while not stop.is_set():
                runtime.loop_seen_at = time.time()
                if settings.FULL_CONTENT_WORKER_ENABLED:
                    close_old_connections()
                    try:
                        recover_stale_fetches()
                        # Re-read the queue after every article so an article
                        # opened by a reader can run immediately after the
                        # current network request instead of waiting for a
                        # stale preselected batch.
                        for _ in range(batch_limit):
                            if stop.is_set():
                                break
                            pending = queue.due(1)
                            if not pending:
                                break
                            news = pending[0]
                            execute_one(news, guard=runtime.guard)
                    except Exception:
                        logger.exception('full_content_worker_iteration_failed')
                    finally:
                        close_old_connections()
                runtime.wait(interval)
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)


class Command(BaseCommand):
    help = 'Run the resident full-content Worker; disabled mode still writes health heartbeats.'

    def add_arguments(self, parser):
        parser.add_argument('--foreground', action='store_true', help='Compatibility option; always a foreground process.')

    def handle(self, *args, **options):
        try:
            run_loop()
        except WorkerAlreadyRunning as error:
            raise CommandError(str(error)) from None
