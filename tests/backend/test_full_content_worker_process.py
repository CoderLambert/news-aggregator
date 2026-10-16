"""Resident Worker lifecycle with independent processes and file SQLite WAL.

Each subprocess receives test-only database, lock and heartbeat paths. Socket
connects are forbidden and providers are synthetic; no publisher is contacted.
"""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from django.test import override_settings

from api.services.full_content_worker import worker_health


ROOT = Path(__file__).resolve().parents[2]
BOOT = r'''
import json, os, signal, socket, threading, time
from pathlib import Path
def forbidden_connect(*args, **kwargs):
    raise AssertionError('worker process test forbids publisher networking')
socket.socket.connect = forbidden_connect
import django
django.setup()
from django.conf import settings
from django.db import connection
from django.utils import timezone
assert settings.DJANGO_ENV == 'development'
assert str(settings.DATABASES['default']['NAME']) == os.environ['DJANGO_DB_PATH']
assert settings.FULL_CONTENT_WORKER_LOCK == os.environ['FULL_CONTENT_WORKER_LOCK']
assert settings.FULL_CONTENT_WORKER_HEARTBEAT == os.environ['FULL_CONTENT_WORKER_HEARTBEAT']
with connection.cursor() as cursor:
    cursor.execute('PRAGMA journal_mode')
    assert cursor.fetchone()[0] == 'wal'
from api.services.full_content_worker import WorkerRuntime
'''
RESIDENT = r'''
from api.management.commands import auto_fetch_full_content as command
# Exercise the actual heartbeat writer/thread at a short deterministic interval.
command.WorkerRuntime = lambda stop: WorkerRuntime(stop, heartbeat_interval=.05)
command.run_loop(interval=.05)
'''
HOLDER = r'''
from api.services.article_fetcher.execution import ExecutionStopped
stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
with WorkerRuntime(stop, heartbeat_interval=60) as runtime:
    while not stop.wait(.02):
        try:
            runtime.guard()
        except ExecutionStopped as error:
            # SIGTERM may arrive between the wait returning and guard().
            # A cancelled guard is the normal shutdown path; other failures
            # must still terminate this test subprocess with an error.
            if error.error_code != 'canceled' or not stop.is_set():
                raise
            break
'''
CREATE_NEWS = r'''
from api.models import News, Source, Category
news = News.objects.create(
    title='A synthetic queued worker article', url='https://dev.to/team/worker-test',
    content='Publisher summary', source=Source.objects.get_or_create(name='Dev.to', defaults={'url': 'https://dev.to'})[0],
    category=Category.objects.create(name='worker-test', slug='worker-test'),
    publish_time=timezone.now(), content_kind='article', full_content_fetch_status='queued',
    full_content_next_attempt_at=timezone.now(), full_content_retry_count=3, full_content_priority=7,
)
'''


class ProcessSandbox:
    def __init__(self, directory):
        self.directory = directory
        self.heartbeat = directory / 'shared' / 'heartbeat.json'
        self.lock = directory / 'shared' / 'worker.lock'
        self.database = directory / 'worker.sqlite3'
        self.processes = []
        self.environment = {
            **os.environ, 'PYTHONPATH': str(ROOT / 'backend'),
            'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings', 'DJANGO_ENV': 'development',
            'RUN_MAIN': 'true', 'NEWS_CRAWL_ONLY': '1',
            'DJANGO_DB_PATH': str(self.database),
            'FULL_CONTENT_WORKER_ENABLED': '0',
            'FULL_CONTENT_WORKER_LOCK': str(self.lock),
            'FULL_CONTENT_WORKER_HEARTBEAT': str(self.heartbeat),
        }

    def run(self, code, *, enabled=False, environment=None, cwd=ROOT, timeout=15):
        result = subprocess.run(
            [sys.executable, '-c', BOOT + code], cwd=cwd,
            env={**self.environment, 'FULL_CONTENT_WORKER_ENABLED': str(int(enabled)), **(environment or {})},
            capture_output=True, text=True, timeout=timeout,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    def start(self, code=RESIDENT, *, enabled=False):
        index = len(self.processes)
        stdout = self.directory / f'process-{index}.out'
        stderr = self.directory / f'process-{index}.err'
        with stdout.open('w') as output, stderr.open('w') as errors:
            process = subprocess.Popen(
                [sys.executable, '-c', BOOT + code], cwd=ROOT,
                env={**self.environment, 'FULL_CONTENT_WORKER_ENABLED': str(int(enabled))},
                stdout=output, stderr=errors, text=True,
            )
        process.test_output = (stdout, stderr)
        self.processes.append(process)
        return process

    def diagnostics(self, process):
        return '\n'.join(path.read_text() for path in process.test_output)

    def wait(self, predicate, *, process, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert process.poll() is None, self.diagnostics(process)
            if predicate():
                return
            time.sleep(.02)
        pytest.fail('worker did not reach the observed state: ' + self.diagnostics(process))

    def read_heartbeat(self):
        try:
            return json.loads(self.heartbeat.read_text())
        except (FileNotFoundError, ValueError):
            return None

    def ready(self, process):
        self.wait(lambda: (self.read_heartbeat() or {}).get('pid') == process.pid and worker_health(), process=process)
        return self.read_heartbeat()

    def stop(self, process):
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=45)
        assert time.monotonic() - started <= 45
        assert process.returncode == 0, self.diagnostics(process)

    def cleanup(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


@pytest.fixture(scope="module")
def migrated_worker_template(tmp_path_factory):
    """Build the SQLite schema once in a subprocess, never using the test DB."""
    template = ProcessSandbox(tmp_path_factory.mktemp("worker-schema"))
    template.run(
        "from django.core.management import call_command\n"
        "call_command('migrate', verbosity=0)\n"
        "from django.db import connection\n"
        "connection.close()\n"
    )
    return template.database


@pytest.fixture
def sandbox(tmp_path, migrated_worker_template):
    box = ProcessSandbox(tmp_path)
    # Consistent SQLite online backup includes any committed WAL contents.
    # Every test receives an independent database; no shared mutable SQLite
    # state, lock file, heartbeat, or worker process survives between cases.
    # Migrations and every ORM write still run only inside subprocesses.
    with closing(sqlite3.connect(migrated_worker_template.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(box.database)) as target:
            source.backup(target)
    with override_settings(
        FULL_CONTENT_WORKER_ENABLED=True,
        FULL_CONTENT_WORKER_LOCK=str(box.lock),
        FULL_CONTENT_WORKER_HEARTBEAT=str(box.heartbeat),
    ):
        try:
            yield box
        finally:
            box.cleanup()


def test_disabled_resident_stays_alive_refreshes_heartbeat_and_is_healthy(sandbox):
    process = sandbox.start(enabled=False)
    initial = sandbox.ready(process)
    sandbox.wait(lambda: (sandbox.read_heartbeat() or {}).get('timestamp', 0) > initial['timestamp'], process=process)

    payload = sandbox.read_heartbeat()
    assert payload['enabled'] is False
    assert payload['db_ok'] is True
    assert payload['owner'] == sandbox.lock.read_text().strip()
    assert worker_health()
    assert not worker_health(require_enabled=True)
    assert process.poll() is None
    sandbox.stop(process)
    assert not worker_health()  # A fresh heartbeat cannot outlive its lock holder.


def test_second_resident_refuses_shared_lock_even_with_other_temp_directory_and_cwd(sandbox):
    process = sandbox.start()
    initial = sandbox.ready(process)
    other = sandbox.directory / 'different-tmp'
    other.mkdir()
    environment = {**sandbox.environment, 'TMPDIR': str(other), 'TMP': str(other), 'TEMP': str(other)}
    refused = subprocess.run(
        [sys.executable, str(ROOT / 'backend' / 'manage.py'), 'auto_fetch_full_content', '--foreground'],
        cwd=other, env=environment, capture_output=True, text=True, timeout=10,
    )

    assert refused.returncode != 0
    assert 'full_content_worker_already_running' in refused.stderr
    assert sandbox.lock.read_text().strip() == initial['owner']
    assert process.poll() is None
    assert worker_health()
    sandbox.stop(process)


def test_stale_foreign_corrupt_and_stopped_heartbeats_are_unhealthy(sandbox):
    process = sandbox.start(HOLDER, enabled=True)
    original = sandbox.ready(process)
    bad_payloads = [
        {**original, 'timestamp': time.time() - 61},
        {**original, 'timestamp': time.time() + 120},
        {**original, 'owner': 'foreign-process-token'},
        {**original, 'loop_seen_at': time.time() - 91},
        {**original, 'db_ok': False},
    ]
    for payload in bad_payloads:
        sandbox.heartbeat.write_text(json.dumps(payload))
        assert not worker_health()
    sandbox.heartbeat.write_text('{not valid json')
    assert not worker_health()
    sandbox.heartbeat.write_text(json.dumps(original))
    assert worker_health(require_enabled=True)
    sandbox.stop(process)
    assert not worker_health()
    assert sandbox.heartbeat.exists()


@pytest.mark.parametrize('field', ['db_ok', 'enabled'])
def test_corrupt_boolean_health_fields_cannot_claim_database_or_enabled_health(sandbox, field):
    process = sandbox.start(HOLDER, enabled=True)
    original = sandbox.ready(process)
    sandbox.heartbeat.write_text(json.dumps({**original, field: 'false'}))

    assert not worker_health(require_enabled=True)
    sandbox.stop(process)


def test_enabled_empty_queue_is_healthy_without_any_publisher_fetch(sandbox):
    process = sandbox.start(enabled=True)
    payload = sandbox.ready(process)

    assert payload['enabled'] is True
    assert worker_health(require_enabled=True)
    report = sandbox.run("from api.models import News\nprint(json.dumps({'news': News.objects.count()}))\n")
    assert json.loads(report.strip().splitlines()[-1]) == {'news': 0}
    # The public health command reads the same shared heartbeat and ownership.
    health = subprocess.run(
        [sys.executable, str(ROOT / 'backend' / 'manage.py'), 'full_content_healthcheck'],
        cwd=ROOT, env=sandbox.environment, capture_output=True, text=True, timeout=10,
    )
    assert health.returncode == 0, health.stdout + health.stderr
    assert health.stdout.strip() == 'ok'
    sandbox.stop(process)


def test_sigterm_during_fake_fetch_returns_durable_task_to_queue_without_second_provider(sandbox):
    started = sandbox.directory / 'provider-started'
    canceled = sandbox.directory / 'provider-saw-stop'
    second = sandbox.directory / 'second-provider-started'
    script = CREATE_NEWS + r'''
from api.management.commands import auto_fetch_full_content as command
from api.services.article_fetcher.execution import current_execution, ExecutionStopped
from api.services.article_fetcher.types import FetchResult
from datetime import timedelta
from api.models import RequestBudget
class ControlledProvider:
    name = 'controlled_fake'
    def fetch(self, url, expected_title=None, summary=None):
        RequestBudget.objects.update_or_create(key='host:dev.to', defaults={
            'cooldown_until': timezone.now() + timedelta(minutes=10),
        })
        Path(os.environ['TEST_PROVIDER_STARTED']).write_text(str(news.pk))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                current_execution.get().check()
            except ExecutionStopped as error:
                assert error.error_code == 'canceled'
                Path(os.environ['TEST_PROVIDER_CANCELED']).write_text('canceled')
                # Returning an ordinary failed candidate exercises the post-
                # Provider cancellation fence, before another Provider starts.
                return FetchResult(False, self.name, error='body_empty', error_code='body_empty')
            time.sleep(.02)
        raise AssertionError('test did not send SIGTERM')
class ForbiddenSecondProvider:
    name = 'forbidden_second'
    def fetch(self, url, expected_title=None, summary=None):
        Path(os.environ['TEST_SECOND_PROVIDER']).write_text('started')
        raise AssertionError('second Provider ran after stop')
actual_execute = command.execute_one
command.execute_one = lambda news, guard=None: actual_execute(news, guard=guard, providers=[ControlledProvider(), ForbiddenSecondProvider()])
command.WorkerRuntime = lambda stop: WorkerRuntime(stop, heartbeat_interval=.05)
command.run_loop(interval=.05)
'''
    sandbox.environment.update(
        TEST_PROVIDER_STARTED=str(started), TEST_PROVIDER_CANCELED=str(canceled), TEST_SECOND_PROVIDER=str(second),
    )
    process = sandbox.start(script, enabled=True)
    sandbox.ready(process)
    sandbox.wait(started.exists, process=process)
    sandbox.stop(process)

    assert canceled.read_text() == 'canceled'
    assert not second.exists()
    assert not worker_health()
    report = sandbox.run(r'''
from api.models import News, RequestBudget
news = News.objects.get()
assert news.full_content_next_attempt_at is not None
cooldown = RequestBudget.objects.get(pk='host:dev.to').cooldown_until
assert news.full_content_next_attempt_at >= cooldown
print(json.dumps(dict(status=news.full_content_fetch_status, retries=news.full_content_retry_count,
    priority=news.full_content_priority, body=news.full_content, state=news.full_content_state)))
''')
    assert json.loads(report.strip().splitlines()[-1]) == {
        'status': 'queued', 'retries': 3, 'priority': 7, 'body': '', 'state': 'missing',
    }


def test_killed_holder_releases_process_lock_and_expired_database_leases_recover(sandbox):
    claimed = sandbox.directory / 'claimed'
    sandbox.environment['TEST_CLAIMED'] = str(claimed)
    script = r'''
from api.services.full_content_status import claim_fetch
from api.services.request_budget import claim_budget
stop = threading.Event()
with WorkerRuntime(stop, heartbeat_interval=.05) as runtime:
''' + '\n'.join('    ' + line for line in CREATE_NEWS.strip().splitlines()) + r'''
    lease = claim_fetch(news)
    assert lease
    permit = claim_budget({'host:killed-worker.test': 0})
    Path(os.environ['TEST_CLAIMED']).write_text(json.dumps({'news':news.pk, 'budget_token':permit.token}))
    while True:
        runtime.guard()
        time.sleep(.02)
'''
    process = sandbox.start(script)
    old_heartbeat = sandbox.ready(process)
    sandbox.wait(claimed.exists, process=process)
    process.kill()
    process.wait(timeout=5)
    assert process.returncode == -signal.SIGKILL
    assert not worker_health()

    replacement = sandbox.start()
    replacement_heartbeat = sandbox.ready(replacement)
    assert replacement_heartbeat['owner'] != old_heartbeat['owner']
    assert worker_health()
    report = sandbox.run(r'''
from datetime import timedelta
from api.models import News, RequestBudget
from api.services import full_content_status as tasks, request_budget as budget
old = json.loads(Path(os.environ['TEST_CLAIMED']).read_text())
news = News.objects.get(pk=old['news'])
assert news.full_content_fetch_status == 'fetching'
assert RequestBudget.objects.get(pk='host:killed-worker.test').lease_token == old['budget_token']
# Advance only these subprocess clocks to model expiry; production TTL stays intact.
future = timezone.now() + timedelta(minutes=6)
tasks.tz_now = lambda: future
budget.timezone.now = lambda: future
assert tasks.recover_stale_fetches() == 1
news.refresh_from_db()
assert news.full_content_fetch_status == 'queued'
assert news.full_content_retry_count == 3 and news.full_content_priority == 7
new_lease = tasks.claim_fetch(news)
assert new_lease
permit = budget.claim_budget({'host:killed-worker.test': 0})
assert permit.token != old['budget_token']
budget.confirm_permit(permit)
budget.release_budget(permit)
assert tasks.release_fetch_claim(news)
print(json.dumps({'process_lock_recovered': True, 'task_lease_recovered': True, 'budget_recovered': True}))
''')
    assert json.loads(report.strip().splitlines()[-1]) == {
        'process_lock_recovered': True, 'task_lease_recovered': True, 'budget_recovered': True,
    }
    assert replacement.poll() is None
    assert worker_health()
    sandbox.stop(replacement)
