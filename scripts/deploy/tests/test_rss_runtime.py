"""Runtime boundary tests use only temporary SQLite databases and subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def runtime_env(directory):
    return {**os.environ, 'PYTHONPATH': str(ROOT / 'backend'),
            'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
            'DJANGO_ENV': 'production', 'DJANGO_DEBUG': '0',
            'DJANGO_SECRET_KEY': 'synthetic-t02-ORM-only-key-abcdefghijklmnopqrstuvwxyz-0123456789',
            'WAITRESS_TRUSTED_PROXY': '127.0.0.1',
            'DJANGO_DB_PATH': str(directory / 'synthetic.sqlite3'),
            'CHATGPT_DEPLOYMENT_INSTANCE_FILE': str(directory / 'deployment-id'),
            'RSS_RUNTIME_DIR': str(directory / 'runtime'),
            'NEWSHUB_RUNTIME_ROLE': 'rss_sync', 'RUN_MAIN': '',
            'NEWS_CRAWL_ONLY': '0'}


def test_orm_shell_never_attempts_heavy_imports_or_url_checks(tmp_path):
    code = '''
import importlib.abc, json, sys
attempted=[]
blocked=('torch', 'sentence_transformers', 'chromadb', 'scrapy', 'feedparser',
         'playwright', 'trafilatura', 'newspaper', 'api.services.embedding',
         'api.urls', 'newsaggregator.urls')
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            attempted.append(fullname)
            raise ImportError('forbidden heavy import')
sys.meta_path.insert(0, Guard())
import django
django.setup()
from django.core.management import call_command
call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
call_command('rss_runtime', once=True)
assert not attempted, attempted
assert not any(name in sys.modules for name in blocked)
'''
    result = subprocess.run([sys.executable, '-c', code], env=runtime_env(tmp_path),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout.splitlines()[-1])
    assert status['orm_available'] and status['sync_ready'] is False
    assert status['worker_integrated'] is False


def test_runtime_refuses_missing_role(tmp_path):
    env = runtime_env(tmp_path)
    env['NEWSHUB_RUNTIME_ROLE'] = ''
    env['RUN_MAIN'] = 'true'
    result = subprocess.run([sys.executable, str(ROOT / 'backend/manage.py'),
        'rss_runtime', '--once'], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'requires NEWSHUB_RUNTIME_ROLE=rss_sync' in result.stderr


def test_runtime_health_requires_live_heartbeat(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'backend/manage.py'),
        'rss_runtime', '--healthcheck'], env=runtime_env(tmp_path),
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
