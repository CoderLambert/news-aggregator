from django.core.management.base import BaseCommand, CommandError
from api.services.full_content_worker import worker_health


class Command(BaseCommand):
    help = 'Check shared full-content process ownership, database and loop heartbeat.'

    def handle(self, *args, **options):
        if not worker_health():
            raise CommandError('full_content_worker_unhealthy')
        self.stdout.write('ok')
