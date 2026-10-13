"""Legacy bounded enqueue alias; provider choice belongs to the resident Worker."""
from api.management.commands.fetch_full_content import Command as EnqueueCommand
from django.conf import settings
from django.core.management.base import CommandError


class Command(EnqueueCommand):
    help = 'Compatibility alias for bounded full-content enqueue; no independent Scrapy execution.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--sleep', type=float, default=0, help='Legacy option; Worker handles scheduling')
        parser.add_argument('--progress-every', type=int, default=10, help='Legacy option')

    def handle(self, *args, **options):
        if settings.DJANGO_ENV == 'production':
            raise CommandError('Use fetch_full_content to enqueue tasks for the resident Worker.')
        return super().handle(*args, **options)
