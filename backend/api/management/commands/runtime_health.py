"""Print the read-only runtime health snapshot and fail if an enabled check is down."""
import json

from django.core.management.base import BaseCommand, CommandError

from api.services.runtime_health import runtime_health_snapshot


class Command(BaseCommand):
    help = 'Check configured NewsHub runtime services without invoking providers or mutating state.'

    def handle(self, *args, **options):
        snapshot = runtime_health_snapshot()
        self.stdout.write(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        if not snapshot['ready']:
            raise CommandError('One or more configured runtime services are unavailable.')
