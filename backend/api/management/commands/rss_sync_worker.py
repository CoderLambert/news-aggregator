"""Single RSS process: control execution now, incremental synchronization in T09."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Execute persistent RSS controls; full synchronization remains not ready.'
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--healthcheck', action='store_true')

    def handle(self, *args, **options):
        from api.rss.runtime import run
        self.stdout.write(run(once=options['once'], healthcheck=options['healthcheck'], control=True))
