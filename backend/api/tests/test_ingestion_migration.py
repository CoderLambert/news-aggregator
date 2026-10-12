"""Migration acceptance in fresh, file-backed databases, outside pytest's memory DB."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('historical', [False, True])
def test_ingestion_migration_preserves_data_and_does_not_enqueue(tmp_path, historical):
    database = tmp_path / 'migration.sqlite3'
    code = '''
import django
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

django.setup()
old = [('api', '0035_article_fetch_monitoring')]
new = [('api', '0036_news_ingestion_contract')]
executor = MigrationExecutor(connection)
executor.migrate(old)
apps = executor.loader.project_state(old).apps
if HISTORICAL:
    Source = apps.get_model('api', 'Source')
    Category = apps.get_model('api', 'Category')
    News = apps.get_model('api', 'News')
    source = Source.objects.create(name='Synthetic publisher', url='https://example.test')
    category = Category.objects.create(name='Migration', slug='migration')
    user = apps.get_model('auth', 'User').objects.create(username='migration')
    for i, body in enumerate(['Stored body', ' \\t\\n\\r\\v\\f ', '', '\\u3000\\xa0']):
        news = News.objects.create(
            title='Synthetic', url=f'https://example.test/{i}', source=source,
            category=category, content='Summary', publish_time=timezone.now(),
            full_content=body, full_content_zh='历史译文',
            full_content_fetch_status='success', suggested_questions=['Original question'],
        )
        apps.get_model('api', 'Favorite').objects.create(news=news, user=user, type='bookmark')
        apps.get_model('api', 'ChatSession').objects.create(news=news, user=user, messages=[{'content':'History'}])
    apps.get_model('api', 'CrawlerSettings').objects.create(pk=1, scheduler_enabled=False)
    apps.get_model('api', 'CrawlerTarget').objects.create(spider_name='leiphone', enabled=False)
executor = MigrationExecutor(connection)
executor.migrate(new)
apps = executor.loader.project_state(new).apps
News = apps.get_model('api', 'News')
assert News.objects.filter(full_content_next_attempt_at__isnull=False).count() == 0
assert apps.get_model('api', 'FeedState').objects.count() == 0
assert apps.get_model('api', 'RequestBudget').objects.count() == 0
assert apps.get_model('api', 'NewsSourceItem').objects.count() == 0
if HISTORICAL:
    rows = list(News.objects.order_by('pk'))
    assert [(r.full_content_state, r.full_content_revision) for r in rows] == [('legacy',1),('missing',0),('missing',0),('missing',0)]
    assert [r.full_content for r in rows] == ['Stored body', ' \\t\\n\\r\\v\\f ', '', '\\u3000\\xa0']
    assert all(r.full_content_zh == '历史译文' and r.suggested_questions == ['Original question'] for r in rows)
    assert apps.get_model('api', 'Favorite').objects.count() == 4
    assert apps.get_model('api', 'ChatSession').objects.count() == 4
    assert not apps.get_model('api', 'CrawlerSettings').objects.get(pk=1).scheduler_enabled
    assert not apps.get_model('api', 'CrawlerTarget').objects.get(spider_name='leiphone').enabled
else:
    assert News.objects.count() == 0
with connection.cursor() as cursor:
    cursor.execute('PRAGMA journal_mode')
    assert cursor.fetchone()[0] == 'wal'
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='news_content_due_idx'")
    assert cursor.fetchone() is not None
'''
    root = Path(__file__).resolve().parents[3]
    env = {
        **os.environ, 'DJANGO_ENV': 'development', 'RUN_MAIN': 'true',
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_DB_PATH': str(database), 'PYTHONPATH': str(root / 'backend'),
    }
    result = subprocess.run(
        [sys.executable, '-c', f'HISTORICAL={historical!r}\n' + code],
        cwd=root, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
