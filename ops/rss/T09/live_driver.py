"""Executed only inside the unique T09 Docker project with synthetic databases."""
import json
import os
from dataclasses import replace
import sqlite3
import subprocess
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.core.management import call_command
from django.db import connection, OperationalError
from django.utils import timezone
from api.models import Category, News, Source, FeedBinding, SourceFeedLink, SourcePublication, FeedSyncState
from api.rss.control_worker import ControlWorker
from api.rss.engine import EngineAdapter, EngineConfig, EngineError
from api.rss.operations import enqueue_operation
from api.rss.reconciliation import SyncWorker, acquire_lease, release_lease, reserve_lease
from api.rss.sync import commit_entry, prepare_page

config = replace(EngineConfig.from_environment(), read_timeout=0.5, connect_timeout=0.5, read_attempts=1)
adapter = EngineAdapter(config)
stage = os.environ['T09_STAGE']


def drain(task, predicate):
    end = time.monotonic() + 45
    while time.monotonic() < end:
        task.retry_at = 0
        task.tick()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(task.status())


def sync_until(predicate):
    control = ControlWorker(config)
    task = SyncWorker(control, config, page_size=1, incremental_seconds=0, reconcile_seconds=0, lookback=0)
    try:
        drain(task, predicate)
    finally:
        task.close()
        control.close()


if stage == 'bootstrap':
    call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
    Category.objects.create(name='Synthetic', slug='synthetic')
    source = Source.objects.create(name='T09 live', url='https://publisher.example:8443')
    SourcePublication.objects.create(source=source, owner='miniflux', publication='public', reading_policy='public_feed')
    binding = FeedBinding.objects.create(engine_instance_uuid=config.engine_instance_uuid, account_id=2,
        canonical_feed_url='https://publisher.example:8443/feed', desired_enabled=True)
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True, editorial_pin=True)
    enqueue_operation('register', actor=None, binding=binding, dedupe_key='synthetic-register')
    control = ControlWorker(config)
    assert control.run_once()
    control.close()
    assert len(adapter.list_entries(0, adapter.read_upper_bound())) == 4
    print(json.dumps({'engine_entries': 4, 'dedicated_collector': True}))
elif stage == 'initial':
    # Child commits one real engine response, then dies BEFORE cursor advancement.
    child = '''import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','newsaggregator.settings'); django.setup()
from api.rss.engine import EngineAdapter, EngineConfig
from api.rss.reconciliation import acquire_lease, reserve_lease
from api.rss.sync import prepare_page, commit_entry
c=EngineConfig.from_environment(); a=EngineAdapter(c); h=a.read_upper_bound()
l=acquire_lease(c.engine_instance_uuid,c.account_id)
p=a.list_entries(0,h,limit=1); f=prepare_page(p,instance_uuid=c.engine_instance_uuid,account_id=c.account_id)
p=a.list_entries(0,h,limit=1)
commit_entry(p[0],f[p[0].id],reserve=lambda:reserve_lease(l))
os._exit(73)
'''
    result = subprocess.run([sys.executable, '-c', child], capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stderr
    assert News.objects.count() == 1 and FeedSyncState.objects.get().new_cursor == 0
    # Synthetic clock expiration represents supervised restart after lease TTL.
    FeedSyncState.objects.update(lease_until=timezone.now())
    lease = acquire_lease(config.engine_instance_uuid, 2)
    upper = adapter.read_upper_bound()
    discovery = adapter.list_entries(0, upper, limit=1)
    fences = prepare_page(discovery, instance_uuid=config.engine_instance_uuid, account_id=2)
    candidate = adapter.list_entries(0, upper, limit=1)[0]
    connection.cursor().execute('PRAGMA busy_timeout=1')
    other = sqlite3.connect(connection.settings_dict['NAME'], timeout=0.01)
    other.execute('BEGIN IMMEDIATE')
    try:
        try:
            commit_entry(candidate, fences[candidate.id], reserve=lambda: reserve_lease(lease))
        except OperationalError:
            pass
        else:
            raise AssertionError('SQLite busy was not enforced')
    finally:
        other.rollback(); other.close()
        connection.cursor().execute('PRAGMA busy_timeout=30000')
    assert FeedSyncState.objects.get().new_cursor == 0
    # Actual HTTP response obtained, then deliberately lost before commit.
    actual = adapter.list_entries(0, upper, limit=1)
    assert actual and FeedSyncState.objects.get().new_cursor == 0
    release_lease(lease)
    sync_until(lambda: FeedSyncState.objects.get().last_complete_at is not None)
    assert News.objects.count() == 3 and FeedSyncState.objects.get().new_cursor == 4
    print(json.dumps({'killed_after_commit_exit': 73, 'busy_cursor_unchanged': True,
        'response_discard_replayed': True, 'new_cursor': 4, 'articles': 3}))
elif stage == 'outage':
    control = ControlWorker(config)
    task = SyncWorker(control, config, incremental_seconds=0, reconcile_seconds=0)
    before = FeedSyncState.objects.get().new_cursor
    try:
        drain(task, lambda: task.error_class is not None)
        assert not task.engine_ready and FeedSyncState.objects.get().new_cursor == before
        print(json.dumps({'engine_stopped': True, 'error_class': task.error_class, 'cursor_preserved': True}))
    finally:
        task.close(); control.close()
elif stage == 'reconcile':
    sync_until(lambda: News.objects.count() == 5 and
        News.objects.filter(full_content='Changed retained body from engine.').exists()
        and FeedSyncState.objects.get().new_cursor == 5
        and FeedSyncState.objects.get().reconciliation_last_complete_at is not None)
    assert News.objects.get(url='https://publisher.example:8443/old-date').publish_time.year == 1990
    print(json.dumps({'low_id_late_imported': True, 'old_body_updated': True, 'old_date_high_id_imported': True, 'articles': 5}))
elif stage == 'cleanup':
    before = FeedSyncState.objects.get().reconciliation_last_complete_at
    sync_until(lambda: FeedSyncState.objects.get().reconciliation_last_complete_at > before)
    assert News.objects.count() == 5 and FeedSyncState.objects.get().new_cursor == 5
    print(json.dumps({'engine_empty': adapter.read_upper_bound() == 0, 'local_articles_preserved': 5}))
assert 'api.services.embedding' not in sys.modules and 'scrapy' not in sys.modules
adapter.close()
