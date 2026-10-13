"""Dedicated channel worker: persistent leases, no web-process threads."""
import signal
import time
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from api.services.channel_topics import refresh_profiles
from api.services.channel_ai import claim_next, execute_job, enqueue_site_sources, process_incremental_subscriptions


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
        while running:
            close_old_connections()
            try:
                if settings.PUBLIC_SITE_MODE == 'full':
                    refresh_profiles()
                    process_incremental_subscriptions()
                    if settings.PUBLIC_AI_ENABLED:
                        enqueue_site_sources()
                        job = claim_next()
                        if job:
                            execute_job(job)
            except Exception as exc:
                self.stderr.write('channel_worker: ' + type(exc).__name__)
                if options['once']:
                    raise
            if options['once']:
                break
            time.sleep(max(2, options['interval']))
