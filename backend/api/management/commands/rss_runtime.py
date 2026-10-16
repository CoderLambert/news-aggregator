"""Lightweight ORM runtime shell; synchronization is connected in T08/T09."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the RSS ORM shell (sync_ready=false until the worker is integrated)."
    requires_system_checks = []  # URL checks import unrelated AI/crawler modules.
    requires_migrations_checks = False

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--once', action='store_true', help='Probe ORM only; do not run a daemon.')
        mode.add_argument('--healthcheck', action='store_true', help='Check ORM and shell heartbeat, not synchronization readiness.')

    def handle(self, *args, **options):
        from api.rss.runtime import run
        self.stdout.write(run(once=options['once'], healthcheck=options['healthcheck']))
