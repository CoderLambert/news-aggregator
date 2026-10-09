import os
import socket
import time
import uuid

from django.core.management.base import BaseCommand, CommandError

from api.services.search_index import cleanup_recovered_index_runs, synchronize_search_index
from api.services.search_index_control import (
    claim_next_index_run,
    finish_index_run,
    queue_search_index_run,
    recover_interrupted_index_runs,
)
from api.services.search_index_lock import (
    SearchIndexExecutionLockUnavailable,
    acquire_search_index_execution_lock,
)


class Command(BaseCommand):
    help = '排队执行语义索引增量同步或全量重建'

    def add_arguments(self, parser):
        parser.add_argument('--rebuild', action='store_true', help='构建新 collection 并在校验后切换')
        parser.add_argument('--wait', action='store_true', help='等待 Worker 完成任务')
        parser.add_argument('--timeout', type=int, default=1800, help='等待超时秒数')

    def handle(self, *args, **options):
        mode = 'rebuild' if options['rebuild'] else 'sync'
        instance_id = f'cli:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
        try:
            with acquire_search_index_execution_lock():
                recovered = recover_interrupted_index_runs(
                    recovery_owner_id=instance_id,
                    force=True,
                )
                cleanup_recovered_index_runs(recovered)
                run, created = self._queue(mode)
                self._describe(run, created)
                if not options['wait']:
                    return
                claimed = claim_next_index_run(instance_id)
                if claimed is None or claimed.pk != run.pk:
                    raise CommandError('无法取得索引任务执行权。')
                self._execute_inline(claimed, instance_id)
                self._wait_for_run(run, options['timeout'])
                return
        except SearchIndexExecutionLockUnavailable:
            # A live Worker or another CLI owns execution. Queue work and wait
            # for that owner instead of creating a second executor.
            run, created = self._queue(mode)
            self._describe(run, created)
            if options['wait']:
                self._wait_for_run(run, options['timeout'])

    def _queue(self, mode):
        run, created = queue_search_index_run(trigger='manual', mode=mode)
        if run is None:
            raise CommandError('无法创建索引任务。')
        return run, created

    def _describe(self, run, created):
        if created:
            self.stdout.write(f'已创建索引任务 {run.id} mode={run.mode}')
        else:
            self.stdout.write(f'已有活动索引任务 {run.id} status={run.status}')

    def _execute_inline(self, run, instance_id):
        try:
            synchronize_search_index(run.pk)
        except Exception as exc:
            finish_index_run(
                run.pk,
                instance_id=instance_id,
                status='failed',
                error_code='index_sync_failed',
                error_message='索引同步失败。',
            )
            raise CommandError(f'索引同步失败: {type(exc).__name__}') from exc
        finish_index_run(
            run.pk,
            instance_id=instance_id,
            status='succeeded',
        )

    def _wait_for_run(self, run, timeout):
        deadline = time.monotonic() + max(1, timeout)
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
