import fcntl
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError

from api.models import CrawlRun
from api.services.crawler_control import (
    claim_next_run,
    finish_run,
    get_crawler_settings,
    recover_interrupted_runs,
    schedule_due_batch,
    sync_crawler_targets,
    touch_worker,
)


SUMMARY_PATTERN = re.compile(
    r'爬虫汇总 source=(?P<source>\S+) '
    r'finish=(?P<finish>\S+) items=(?P<items>\d+) '
    r'responses=(?P<responses>\d+) errors=(?P<errors>\d+) '
    r'http=(?P<http>\S+)'
)


def parse_summary(log_path):
    try:
        with log_path.open('rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 1024 * 1024))
            text = handle.read().decode('utf-8', errors='replace')
    except OSError:
        return {}
    matches = list(SUMMARY_PATTERN.finditer(text))
    if not matches:
        return {}
    match = matches[-1]
    http_statuses = {}
    if match.group('http') != '-':
        for pair in match.group('http').split(','):
            code, separator, count = pair.partition(':')
            if separator and code.isdigit() and count.isdigit():
                http_statuses[code] = int(count)
    return {
        'finish_reason': match.group('finish'),
        'items': int(match.group('items')),
        'responses': int(match.group('responses')),
        'errors': int(match.group('errors')),
        'http_statuses': http_statuses,
    }


class Command(BaseCommand):
    help = '运行持久化爬虫调度与执行 Worker'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='只执行一次调度/领取循环后退出')

    def handle(self, *args, **options):
        project_root = Path(django_settings.BASE_DIR).parent
        log_root = Path(os.environ.get('CRAWLER_LOG_DIR', project_root / 'logs' / 'crawler'))
        log_root.mkdir(parents=True, exist_ok=True)
        lock_path = Path(os.environ.get('CRAWLER_WORKER_LOCK', log_root.parent / 'crawler-worker.lock'))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open('a+')
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CommandError('另一个 Crawler Worker 已持有项目锁。') from exc

        instance_id = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
        self.stopping = False
        self.active_process = None

        def stop_worker(_signum, _frame):
            self.stopping = True
            self._terminate_active_process()

        signal.signal(signal.SIGTERM, stop_worker)
        signal.signal(signal.SIGINT, stop_worker)

        sync_crawler_targets()
        get_crawler_settings()
        recovered = recover_interrupted_runs()
        if recovered:
            self.stdout.write(f'已标记 {recovered} 个中断任务为失败。')
        self.stdout.write(self.style.SUCCESS(f'Crawler Worker 已启动: {instance_id}'))

        poll_seconds = max(1.0, float(os.environ.get('CRAWLER_WORKER_POLL_SECONDS', '2')))
        while not self.stopping:
            touch_worker(instance_id)
            schedule_due_batch()
            run = claim_next_run()
            if run is not None:
                self._execute_run(run, instance_id, log_root)
            if options['once']:
                break
            time.sleep(poll_seconds)

        self._terminate_active_process()
        self.stdout.write('Crawler Worker 已停止。')

    def _execute_run(self, run, instance_id, log_root):
        log_path = log_root / f'{run.id}.log'
        relative_log_path = f'crawler/{run.id}.log'
        env = os.environ.copy()
        env['NEWS_CRAWL_ONLY'] = '1'
        env['PYTHONUNBUFFERED'] = '1'
        manage_py = Path(django_settings.BASE_DIR) / 'manage.py'
        command = [sys.executable, str(manage_py), 'crawl', run.target_id]
        cancelled = False
        interrupted = False
        exit_code = None
        try:
            with log_path.open('w', encoding='utf-8') as log_handle:
                self.active_process = subprocess.Popen(
                    command,
                    cwd=str(django_settings.BASE_DIR),
                    env=env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    text=True,
                )
                while self.active_process.poll() is None:
                    touch_worker(instance_id, run_id=run.id)
                    current_status = CrawlRun.objects.filter(pk=run.id).values_list('status', flat=True).first()
                    if current_status == 'cancel_requested':
                        cancelled = True
                        self._terminate_active_process()
                    elif self.stopping:
                        interrupted = True
                        self._terminate_active_process()
                    time.sleep(1)
                exit_code = self.active_process.returncode
        except Exception as exc:
            finish_run(
                run.id,
                status='failed',
                exit_code=exit_code,
                safe_error=f'Crawler Worker 无法执行任务：{type(exc).__name__}',
                log_path=relative_log_path,
            )
            return
        finally:
            self.active_process = None

        summary = parse_summary(log_path)
        if cancelled:
            status = 'cancelled'
            safe_error = '任务已按超级管理员请求停止。'
        elif interrupted:
            status = 'failed'
            safe_error = 'Crawler Worker 停止，任务被中断。'
        elif exit_code == 0 and summary:
            status = 'succeeded'
            safe_error = ''
        elif exit_code == 0:
            status = 'failed'
            safe_error = '爬虫退出但没有生成有效汇总。'
        else:
            status = 'failed'
            safe_error = f'爬虫进程退出码：{exit_code}'
        finish_run(
            run.id,
            status=status,
            exit_code=exit_code,
            summary=summary,
            safe_error=safe_error,
            log_path=relative_log_path,
        )

    def _terminate_active_process(self):
        process = self.active_process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass
