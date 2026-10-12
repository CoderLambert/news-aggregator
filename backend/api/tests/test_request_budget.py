from datetime import timedelta
from email.utils import format_datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from django.utils import timezone

from api.models import RequestBudget
from api.services import request_budget as budget


@pytest.mark.django_db
def test_all_scopes_rollback_and_two_global_slots_are_shared():
    first = budget.claim_budget({'host:one.test': 0})
    with pytest.raises(budget.BudgetDeferred):
        budget.claim_budget({'host:one.test': 0, 'group:shared': 0})
    assert RequestBudget.objects.get(pk='global:1').lease_token == ''
    assert RequestBudget.objects.get(pk='group:shared').lease_token == ''
    second = budget.claim_budget({'host:two.test': 0})
    with pytest.raises(budget.BudgetDeferred):
        budget.claim_budget({'host:three.test': 0})
    budget.confirm_permit(first)
    budget.confirm_permit(second)
    budget.release_budget(first)
    third = budget.claim_budget({'host:three.test': 0})
    budget.confirm_permit(third)
    budget.release_budget(second)
    budget.release_budget(third)


@pytest.mark.django_db
def test_old_token_cannot_release_new_lease_or_erase_late_cooldown(monkeypatch):
    instant = timezone.now()
    monkeypatch.setattr(budget.timezone, 'now', lambda: instant)
    old = budget.claim_budget({'host:publisher.test': 0})
    instant += timedelta(seconds=31)
    new = budget.claim_budget({'host:publisher.test': 0})
    deadline = budget.record_response(old, 429, {'Retry-After': '120'})
    budget.release_budget(old)
    row = RequestBudget.objects.get(pk='host:publisher.test')
    assert row.lease_token == new.token and row.cooldown_until == deadline
    with pytest.raises(budget.BudgetDeferred):
        budget.confirm_permit(new)  # late 429 also blocks a claimed-but-unsent permit
    budget.release_budget(new)
    with pytest.raises(budget.BudgetDeferred):
        budget.claim_budget({'host:publisher.test': 0})


@pytest.mark.parametrize('header', ['60', 'bad', '-10', None])
def test_retry_after_invalid_or_seconds_are_never_earlier_than_conservative_floor(header):
    now = timezone.now()
    deadline = budget.retry_after_deadline(header, now=now)
    assert now + timedelta(seconds=60) <= deadline <= now + timedelta(seconds=65)


def test_retry_after_dates_preserve_far_future_and_reject_past():
    now = timezone.now()
    future = now.replace(microsecond=0) + timedelta(days=7)
    deadline = budget.retry_after_deadline(format_datetime(future, usegmt=True), now=now)
    assert future <= deadline <= future + timedelta(seconds=5)
    past = now - timedelta(hours=1)
    assert budget.retry_after_deadline(format_datetime(past, usegmt=True), now=now) >= now + timedelta(seconds=60)


@pytest.mark.django_db
def test_claim_clock_is_refreshed_after_first_writer_reservation(monkeypatch):
    fresh = timezone.now()
    calls = 0
    def clock():
        nonlocal calls
        calls += 1
        return fresh - timedelta(seconds=31) if calls == 1 else fresh
    monkeypatch.setattr(budget.timezone, 'now', clock)
    permit = budget.claim_budget({'host:publisher.test': 0})
    assert permit.expires_at == fresh + timedelta(seconds=30)
    budget.confirm_permit(permit)
    for row in RequestBudget.objects.filter(lease_token=permit.token):
        assert row.lease_expires_at == permit.expires_at


@pytest.mark.django_db
def test_release_interval_and_restart_keep_server_cooldown(monkeypatch):
    instant = timezone.now()
    monkeypatch.setattr(budget.timezone, 'now', lambda: instant)
    permit = budget.claim_budget({'host:publisher.test': 3})
    deadline = budget.record_response(permit, 503, {'Retry-After': '300'})
    budget.release_budget(permit)
    row = RequestBudget.objects.get(pk='host:publisher.test')
    assert row.next_allowed_at == instant + timedelta(seconds=3)
    assert row.cooldown_until == deadline
    instant += timedelta(seconds=30)
    with pytest.raises(budget.BudgetDeferred) as error:
        budget.claim_budget({'host:publisher.test': 3})
    assert error.value.retry_after_at == deadline


def test_jina_scopes_share_origin_and_credential_without_storing_a_secret():
    scopes = budget.scope_intervals('https://r.jina.ai/https://dev.to/team/article', logical_url='https://dev.to/team/article', authorization='Bearer synthetic-secret')
    assert scopes['host:r.jina.ai'] == 3
    assert scopes['host:dev.to'] == 1
    assert any(key.startswith('credential:jina:') for key in scopes)
    assert all('synthetic-secret' not in key for key in scopes)


def test_file_wal_multiprocess_global_host_limits_and_killed_owner_recovery(tmp_path):
    root = Path(__file__).resolve().parents[3]
    code = r'''
import django, json, multiprocessing as mp, time
from datetime import timedelta
from django.db import connection
from django.core.management import call_command
from django.utils import timezone

django.setup()
call_command('migrate', verbosity=0)
from api.services import request_budget as budget
from api.models import News, Source, Category
from api.services.full_content_status import claim_fetch, mark_failed, FetchLease
from api.services.article_fetcher.types import FullContentCandidate, FetchResult
from api.services.full_content_status import mark_success
with connection.cursor() as cursor:
    cursor.execute('PRAGMA journal_mode')
    assert cursor.fetchone()[0] == 'wal'
ctx = mp.get_context('fork')
lock, start = ctx.Lock(), ctx.Event()
counts = ctx.Array('i', [0, 0, 0, 0, 0])
connection.close()
def exercise(host):
    start.wait()
    for _ in range(5):
        while True:
            try:
                permit = budget.claim_budget({f'host:{host}.test': 0})
                break
            except budget.BudgetDeferred:
                time.sleep(.01)
        budget.confirm_permit(permit)
        with lock:
            counts[0] += 1
            counts[host + 1] += 1
            counts[3] = max(counts[3], counts[0])
            counts[4] = max(counts[4], counts[host + 1])
        time.sleep(.025)
        with lock:
            counts[0] -= 1
            counts[host + 1] -= 1
        budget.release_budget(permit)
    connection.close()
workers = [ctx.Process(target=exercise, args=(host,)) for host in (0,0,1,1)]
for worker in workers: worker.start()
start.set()
for worker in workers:
    worker.join(10)
    assert worker.exitcode == 0
assert counts[3] == 2 and counts[4] == 1
news = News.objects.create(title='Synthetic lease', url='https://dev.to/team/lease', content='Summary',
    source=Source.objects.create(name='Dev.to', url='https://dev.to'),
    category=Category.objects.create(name='Lease', slug='lease'), publish_time=timezone.now(),
    full_content_fetch_status='queued', full_content_next_attempt_at=timezone.now())
news_id = news.pk
connection.close()
queue = ctx.Queue()
def abandoned():
    current = News.objects.get(pk=news_id)
    lease = claim_fetch(current)
    permit = budget.claim_budget({'host:killed.test': 0})
    queue.put((lease, permit))
    time.sleep(30)
owner = ctx.Process(target=abandoned)
owner.start()
old_lease, old_permit = queue.get(timeout=5)
owner.terminate()
owner.join(5)
assert owner.exitcode is not None
# Controlled clock advance models expiry without changing production TTLs.
future = timezone.now() + timedelta(minutes=6)
budget.timezone.now = lambda: future
from api.services import full_content_status
full_content_status.tz_now = lambda: future
replacement_permit = budget.claim_budget({'host:killed.test': 0})
budget.release_budget(old_permit)
budget.confirm_permit(replacement_permit)
current = News.objects.get(pk=news_id)
replacement = claim_fetch(current)
assert replacement and replacement.claimed_at != old_lease.claimed_at
stale = News.objects.get(pk=news_id)
stale._full_content_snapshot = old_lease
body = FullContentCandidate('devto', '17', stale.url, 'https://dev.to/api/articles/17', None, stale.title,
    'article', 'body_markdown', 'markdown', 'full', 'A complete synthetic body.', None, None, future)
assert not mark_success(stale, FetchResult(ok=True, provider='devto', markdown=body.raw_content, candidate=body))
assert not mark_failed(stale, RuntimeError('stale failure'))
assert mark_success(current, FetchResult(ok=True, provider='devto', markdown=body.raw_content, candidate=body))
budget.release_budget(replacement_permit)
print(json.dumps({'global_max':counts[3], 'host_max':counts[4], 'wal':True, 'killed_owner_recovered':True}))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env={
        **os.environ, 'PYTHONPATH': str(root / 'backend'), 'DJANGO_ENV': 'development',
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings', 'RUN_MAIN': 'true',
        'DJANGO_DB_PATH': str(tmp_path / 'wal-budget.sqlite3'),
    }, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {'global_max': 2, 'host_max': 1, 'wal': True, 'killed_owner_recovered': True}


def test_file_database_busy_fails_closed_and_restores_connection_timeout(tmp_path):
    root = Path(__file__).resolve().parents[3]
    code = r'''
import django, sqlite3, time
from django.conf import settings
from django.core.management import call_command
from django.db import connection

django.setup()
call_command('migrate', verbosity=0)
from api.services import request_budget as budget
from api.models import RequestBudget
with connection.cursor() as cursor:
    cursor.execute('PRAGMA busy_timeout')
    original = cursor.fetchone()[0]
locker = sqlite3.connect(settings.DATABASES['default']['NAME'])
locker.execute('BEGIN IMMEDIATE')
started = time.monotonic()
try:
    budget.claim_budget({'host:locked.test':0})
    raise AssertionError('budget bypassed a locked database')
except budget.BudgetDeferred:
    assert time.monotonic() - started < 1
finally:
    locker.rollback()
    locker.close()
with connection.cursor() as cursor:
    cursor.execute('PRAGMA busy_timeout')
    assert cursor.fetchone()[0] == original == 30000
assert not RequestBudget.objects.exclude(lease_token='').exists()
permit = budget.claim_budget({'host:locked.test':0})
budget.confirm_permit(permit)
budget.release_budget(permit)
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env={
        **os.environ, 'PYTHONPATH': str(root / 'backend'), 'DJANGO_ENV': 'development',
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings', 'RUN_MAIN': 'true',
        'DJANGO_DB_PATH': str(tmp_path / 'busy.sqlite3'),
    }, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_retry_after_far_future_does_not_overflow_or_shorten():
    from datetime import datetime, timezone as utc_timezone
    now = timezone.now()
    last_second = datetime(9999, 12, 31, 23, 59, 59, tzinfo=utc_timezone.utc)
    assert budget.retry_after_deadline(format_datetime(last_second, usegmt=True), now=now) >= last_second
    assert budget.retry_after_deadline('9' * 100, now=now) == datetime.max.replace(tzinfo=utc_timezone.utc)


@pytest.mark.django_db
def test_success_resets_failure_streak_without_clearing_another_responses_cooldown(monkeypatch):
    instant = timezone.now()
    monkeypatch.setattr(budget.timezone, 'now', lambda: instant)
    first = budget.claim_budget({'host:publisher.test': 0})
    instant += timedelta(seconds=31)
    second = budget.claim_budget({'host:publisher.test': 0})
    deadline = budget.record_response(first, 429, {'Retry-After': '120'})
    budget.record_response(second, 200, {})
    row = RequestBudget.objects.get(pk='host:publisher.test')
    assert row.cooldown_until == deadline and row.consecutive_failures == 0
    assert row.lease_token == second.token


def test_dns_equivalent_idna_and_hostname_case_share_scope():
    assert budget.scope_intervals('https://bücher.example/article') == budget.scope_intervals('https://XN--BCHER-KVA.EXAMPLE./article')
