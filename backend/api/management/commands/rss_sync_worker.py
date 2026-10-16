"""Single RSS process: control and bounded incremental/retained synchronization."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Execute RSS controls, incremental sync and retained reconciliation.'
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--healthcheck', action='store_true')

    def handle(self, *args, **options):
        from api.rss.runtime import run
        self.stdout.write(run(once=options['once'], healthcheck=options['healthcheck'], control=True, sync=True))
