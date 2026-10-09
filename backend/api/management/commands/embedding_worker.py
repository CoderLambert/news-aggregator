import logging
import os
import signal
import socket
import time
import uuid

from django.core.management.base import BaseCommand, CommandError

from api.services.search_index import (
    SearchIndexCancelled,
    cleanup_recovered_index_runs,
    synchronize_search_index,
)
from api.services.search_index_control import (
    claim_next_index_run,
    finish_index_run,
    get_search_index_settings,
    index_run_cancel_requested,
    queue_search_index_run,
    recover_interrupted_index_runs,
    schedule_due_index_run,
    touch_index_worker,
)
from api.services.search_index_lock import (
    SearchIndexExecutionLockUnavailable,
    acquire_search_index_execution_lock,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '运行持久化语义索引同步 Worker'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='只执行一个调度循环后退出')

    def handle(self, *args, **options):
        instance_id = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
        self.stopping = False

        def stop_worker(_signum, _frame):
            self.stopping = True

        signal.signal(signal.SIGTERM, stop_worker)
        signal.signal(signal.SIGINT, stop_worker)

        try:
            with acquire_search_index_execution_lock():
                self._run_locked(instance_id, options)
        except SearchIndexExecutionLockUnavailable as exc:
            raise CommandError('另一个索引执行者已持有项目锁。') from exc

    def _run_locked(self, instance_id, options):
        settings = get_search_index_settings()
        recovered = recover_interrupted_index_runs(
            recovery_owner_id=instance_id,
            force=True,
        )
        cleaned = cleanup_recovered_index_runs(recovered)
        if recovered:
            self.stdout.write(
                f'已立即恢复 {len(recovered)} 个中断任务，清理 {cleaned} 个候选索引。'
            )

        if settings.enabled:
            queue_search_index_run(trigger='startup', mode='sync')
        if settings.next_run_at is None:
            schedule_due_index_run()
        self.stdout.write(self.style.SUCCESS(f'Embedding Worker 已启动: {instance_id}'))

        poll_seconds = max(1.0, float(os.environ.get('SEARCH_INDEX_WORKER_POLL_SECONDS', '2')))
        while not self.stopping:
            touch_index_worker(instance_id)
            schedule_due_index_run()
            run = claim_next_index_run(instance_id)
            if run is not None:
                self._execute_run(run, instance_id)
            if options['once']:
                break
            time.sleep(poll_seconds)

        touch_index_worker(instance_id)
        self.stdout.write('Embedding Worker 已停止。')

    def _execute_run(self, run, instance_id):
        def heartbeat():
            touch_index_worker(instance_id, run_id=run.id)

        def cancelled():
            return self.stopping or index_run_cancel_requested(run.id)

        try:
            synchronize_search_index(
                run.id,
                heartbeat=heartbeat,
                cancel_requested=cancelled,
            )
        except SearchIndexCancelled:
            if self.stopping:
                finish_index_run(
                    run.id,
                    instance_id=instance_id,
                    status='failed',
                    error_code='worker_interrupted',
                    error_message='索引 Worker 停止，任务可安全重试。',
                )
            else:
                finish_index_run(
                    run.id,
                    instance_id=instance_id,
                    status='cancelled',
                )
        except Exception as exc:
            logger.exception('Search index run %s failed with %s', run.id, type(exc).__name__)
            finish_index_run(
                run.id,
                instance_id=instance_id,
                status='failed',
                error_code='index_sync_failed',
                error_message='索引同步失败，可从管理控制台重试。',
            )
        else:
            finish_index_run(
                run.id,
                instance_id=instance_id,
                status='succeeded',
            )
