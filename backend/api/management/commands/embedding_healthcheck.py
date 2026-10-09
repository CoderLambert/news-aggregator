from django.core.management.base import BaseCommand, CommandError

from api.services.search_index_control import get_search_index_settings, index_worker_is_online


class Command(BaseCommand):
    help = '检查语义索引 Worker 心跳'

    def handle(self, *args, **options):
        settings = get_search_index_settings()
        if not index_worker_is_online(settings):
            raise CommandError('Embedding Worker 心跳已过期。')
        self.stdout.write('ok')
