from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import CrawlerSettings


class Command(BaseCommand):
    help = '检查 Crawler Worker 心跳是否新鲜'

    def handle(self, *args, **options):
        settings = CrawlerSettings.objects.filter(pk=1).first()
        if settings is None or settings.worker_heartbeat_at is None:
            raise CommandError('Crawler Worker 尚未写入心跳。')
        if settings.worker_heartbeat_at < timezone.now() - timedelta(seconds=60):
            raise CommandError('Crawler Worker 心跳已过期。')
        self.stdout.write('ok')
