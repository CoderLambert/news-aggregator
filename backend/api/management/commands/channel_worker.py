"""Dedicated worker with persistent task leases and observable process liveness."""
import json
import os
from pathlib import Path
import signal
import time
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from api.services.channel_topics import refresh_profiles
from api.services.channel_ai import claim_next, execute_job, enqueue_site_sources, process_incremental_subscriptions


def heartbeat(*, activation_paused=False):
    path = os.environ.get('CHANNEL_WORKER_HEARTBEAT', '')
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.' + str(os.getpid()) + '.tmp')
    temporary.write_text(json.dumps({
        'pid': os.getpid(), 'time': time.time(),
        'activation_paused': activation_paused,
    }), encoding='utf-8')
    temporary.replace(target)


class Command(BaseCommand):
    help = 'Process channel metadata, authorized AI proposals, and new-subscription grouping.'
    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--interval', type=float, default=5)
    def handle(self, *args, **options):
        running = True
        def stop(*_args):
            nonlocal running
            running = False
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        activation_paused = os.environ.get('NEWSHUB_ACTIVATION_PAUSED') == '1'
        while running:
            close_old_connections()
            try:
                heartbeat(activation_paused=activation_paused)
                if not activation_paused and settings.PUBLIC_SITE_MODE == 'full':
                    refresh_profiles()
                    process_incremental_subscriptions()
                    if settings.PUBLIC_AI_ENABLED:
                        enqueue_site_sources()
                        job = claim_next()
                        if job:
                            execute_job(job)
                heartbeat(activation_paused=activation_paused)
            except Exception as exc:
                self.stderr.write('channel_worker: ' + type(exc).__name__)
                if options['once']:
                    raise
            if options['once']:
                break
            # Split sleeping so a clean stop does not wait for a long interval.
            until = time.monotonic() + max(2, min(60, options['interval']))
            while running and time.monotonic() < until:
                time.sleep(.5)
