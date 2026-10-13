"""Verify the catalog initialization against both empty and historical databases."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('historical', [False, True])
def test_channel_migration_keeps_existing_data_without_subscribing_users(tmp_path, historical):
    root = Path(__file__).resolve().parents[3]
    code = '''
import django
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

django.setup()
old = [('api', '0038_content_task_creation_time')]
new = [('api', '0040_initialize_channel_catalog')]
executor = MigrationExecutor(connection)
executor.migrate(old)
apps = executor.loader.project_state(old).apps
if HISTORICAL:
    source = apps.get_model('api', 'Source').objects.create(name='OpenAI Blog', url='https://example.test/preserved', language='zh')
    user = apps.get_model('auth', 'User').objects.create(username='existing-reader')
    category = apps.get_model('api', 'Category').objects.create(name='Technology', slug='tech')
    news = apps.get_model('api', 'News').objects.create(title='Preserved', content='Stored content', url='https://example.test/story',
        source=source, category=category, publish_time=timezone.now())
    apps.get_model('api', 'Favorite').objects.create(user=user, news=news, type='bookmark')
    source_id, news_id = source.pk, news.pk
executor = MigrationExecutor(connection)
executor.migrate(new)
apps = executor.loader.project_state(new).apps
assert apps.get_model('api', 'Source').objects.filter(name='WebKit').exists()
assert apps.get_model('api', 'Source').objects.filter(name='DeepMind').exists()
assert not apps.get_model('api', 'Source').objects.filter(name='Reuters').exists()
for name in ['ChannelSubscription', 'ChannelGroup', 'ChannelGroupMember', 'NewsPreference']:
    assert apps.get_model('api', name).objects.count() == 0
if HISTORICAL:
    source = apps.get_model('api', 'Source').objects.get(pk=source_id)
    assert source.url == 'https://example.test/preserved' and source.language == 'zh'
    assert apps.get_model('api', 'News').objects.get(pk=news_id).content == 'Stored content'
    assert apps.get_model('api', 'Favorite').objects.count() == 1
    assert apps.get_model('auth', 'User').objects.filter(username='existing-reader').exists()
else:
    assert apps.get_model('api', 'News').objects.count() == 0
'''
    env = {**os.environ, 'DJANGO_ENV': 'development', 'RUN_MAIN': 'true',
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings', 'DJANGO_DB_PATH': str(tmp_path / 'channels.sqlite3'),
        'PYTHONPATH': str(root / 'backend')}
    result = subprocess.run([sys.executable, '-c', f'HISTORICAL={historical!r}\n' + code],
        cwd=root, env=env, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
