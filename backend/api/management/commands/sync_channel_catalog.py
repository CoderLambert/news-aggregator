from django.core.management.base import BaseCommand
from api.services.channel_catalog import sync_channel_catalog


class Command(BaseCommand):
    help = 'Retired static catalog compatibility command; use rss_initialize for RSS defaults.'

    def handle(self, *args, **options):
        sync_channel_catalog()
        self.stdout.write(self.style.SUCCESS('旧静态目录已退役；请使用 rss_initialize 预览 RSS 默认来源。'))
