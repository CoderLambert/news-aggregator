import time

from django.core.management.base import BaseCommand, CommandError

from api.services.search_index import synchronize_search_index
from api.services.search_index_control import (
    claim_next_index_run,
    finish_index_run,
    get_search_index_settings,
    index_worker_is_online,
    queue_search_index_run,
)


class Command(BaseCommand):
    help = '排队执行语义索引增量同步或全量重建'

    def add_arguments(self, parser):
        parser.add_argument('--rebuild', action='store_true', help='构建新 collection 并在校验后切换')
        parser.add_argument('--wait', action='store_true', help='等待 Worker 完成任务')
        parser.add_argument('--timeout', type=int, default=1800, help='等待超时秒数')

    def handle(self, *args, **options):
        mode = 'rebuild' if options['rebuild'] else 'sync'
        run, created = queue_search_index_run(trigger='manual', mode=mode)
        if run is None:
            raise CommandError('无法创建索引任务。')
        if created:
            self.stdout.write(f'已创建索引任务 {run.id} mode={run.mode}')
        else:
            self.stdout.write(f'已有活动索引任务 {run.id} status={run.status}')
        if not options['wait']:
            return

        if created and not index_worker_is_online(get_search_index_settings()):
            claimed = claim_next_index_run()
            if claimed and claimed.pk == run.pk:
                try:
                    synchronize_search_index(claimed.pk)
                except Exception as exc:
                    finish_index_run(
                        claimed.pk,
                        status='failed',
                        error_code='index_sync_failed',
                        error_message='索引同步失败。',
                    )
                    raise CommandError(
                        f'索引同步失败: {type(exc).__name__}'
                    ) from exc
                else:
                    finish_index_run(claimed.pk, status='succeeded')

        deadline = time.monotonic() + max(1, options['timeout'])
        while time.monotonic() < deadline:
            run.refresh_from_db()
            if run.status == 'succeeded':
                self.stdout.write(self.style.SUCCESS(
                    f'索引同步完成: vectors={run.vector_count_after} '
                    f'upserted={run.upserted_count} deleted={run.deleted_count}'
                ))
                return
            if run.status in {'failed', 'cancelled'}:
                raise CommandError(
                    f'索引任务结束: status={run.status} code={run.safe_error_code or "unknown"}'
                )
            time.sleep(1)
        raise CommandError('等待索引任务超时；任务仍保留在后台。')
