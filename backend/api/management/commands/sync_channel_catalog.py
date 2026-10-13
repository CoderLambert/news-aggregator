from django.core.management.base import BaseCommand
from api.services.channel_catalog import sync_channel_catalog


class Command(BaseCommand):
    help = 'Initialize missing supported channels without changing existing sources or subscriptions.'

    def handle(self, *args, **options):
        sync_channel_catalog()
        self.stdout.write(self.style.SUCCESS('频道目录已同步。'))
