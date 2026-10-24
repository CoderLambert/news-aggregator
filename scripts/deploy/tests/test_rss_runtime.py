"""Runtime boundary tests use only temporary SQLite databases and subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[3]


def runtime_env(directory):
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'backend'),
            'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
            'DJANGO_ENV': 'production', 'DJANGO_DEBUG': '0',
            'DJANGO_SECRET_KEY': 'synthetic-t02-ORM-only-key-abcdefghijklmnopqrstuvwxyz-0123456789',
            'WAITRESS_TRUSTED_PROXY': '127.0.0.1',
            'DJANGO_DB_PATH': str(directory / 'synthetic.sqlite3'),
            'CHATGPT_DEPLOYMENT_INSTANCE_FILE': str(directory / 'deployment-id'),
            'RSS_RUNTIME_DIR': str(directory / 'runtime'),
            'NEWSHUB_RUNTIME_ROLE': 'rss_sync', 'RUN_MAIN': '',
            'NEWS_CRAWL_ONLY': '0'}
    env.pop('PYTEST_CURRENT_TEST', None)
    return env


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
    migration = subprocess.run([sys.executable, str(ROOT / 'backend/manage.py'),
        'migrate', '--noinput', '--skip-checks'], env=runtime_env(tmp_path),
        capture_output=True, text=True, timeout=60)
    assert migration.returncode == 0, migration.stderr
    result = subprocess.run([sys.executable, str(ROOT / 'backend/manage.py'),
        'rss_runtime', '--healthcheck'], env=runtime_env(tmp_path),
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'heartbeat is missing or stale' in result.stderr


def test_activation_pause_does_not_construct_or_poll_rss_engine(tmp_path):
    import importlib.util
    from types import ModuleType, SimpleNamespace
    django = ModuleType('django')
    django_conf = ModuleType('django.conf')
    django_conf.settings = SimpleNamespace()
    django_core = ModuleType('django.core')
    django_management = ModuleType('django.core.management')
    django_base = ModuleType('django.core.management.base')
    django_base.CommandError = type('CommandError', (Exception,), {})
    django_db = ModuleType('django.db')
    django_db.close_old_connections = lambda: None
    original = {name: sys.modules.get(name) for name in (
        'django', 'django.conf', 'django.core', 'django.core.management',
        'django.core.management.base', 'django.db')}
    try:
        sys.modules.update({
            'django': django, 'django.conf': django_conf, 'django.core': django_core,
            'django.core.management': django_management,
            'django.core.management.base': django_base, 'django.db': django_db,
        })
        spec = importlib.util.spec_from_file_location(
            'isolated_rss_runtime', ROOT / 'backend/api/rss/runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.probe = lambda: {'role': 'rss_sync', 'mode': 'orm_shell',
                                'orm_available': True, 'sync_ready': False,
                                'worker_integrated': False}
        os.environ['NEWSHUB_ACTIVATION_PAUSED'] = '1'
        status = json.loads(module.run(once=True, control=True, sync=True))
    finally:
        os.environ.pop('NEWSHUB_ACTIVATION_PAUSED', None)
        for name, value in original.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    assert status['mode'] == 'activation_paused'


def test_optional_overlay_has_private_pg_scoped_secrets_and_loopback_api():
    config = yaml.safe_load((ROOT / 'compose.rss.prod.yaml').read_text())
    services = config['services']
    assert set(services) == {'app', 'rss-db', 'miniflux', 'rss-sync'}
    assert all(services[name]['profiles'] == ['rss'] for name in ('rss-db', 'miniflux', 'rss-sync'))
    assert services['app']['volumes'] == ['rss-runtime-data:/var/lib/newshub/rss-runtime:ro']
    assert set(services['app']['environment']) == {'RSS_ENGINE_INSTANCE_UUID', 'RSS_ENGINE_ACCOUNT_ID', 'RSS_RUNTIME_DIR', 'RSS_FULL_CONTENT_ENABLED'}
    assert services['app']['environment']['RSS_FULL_CONTENT_ENABLED'] == '${RSS_FULL_CONTENT_ENABLED:-1}'
    assert 'secrets' not in services['app']
    assert 'ports' not in services['rss-db']
    assert config['networks']['rss-db-net']['internal'] is True
    engine = services['miniflux']
    assert engine['ports'] == ['127.0.0.1:${RSS_ENGINE_PORT:-18080}:8080']
    assert engine['environment']['FETCHER_ALLOW_PRIVATE_NETWORKS'] == '0'
    for name in ('CLEANUP_ARCHIVE_READ_DAYS', 'CLEANUP_ARCHIVE_UNREAD_DAYS'):
        assert engine['environment'][name] == '90'
    for name in ('rss-db', 'miniflux'):
        assert '@sha256:' in services[name]['image']
    sync = services['rss-sync']
    assert sync['command'] == ['python', '/app/backend/manage.py', 'rss_sync_worker']
    assert sync['secrets'] == ['rss_engine_token']
    assert set(sync['volumes']) == {'db-data:/var/lib/newshub/db', 'rss-runtime-data:/var/lib/newshub/rss-runtime'}
    assert sync['environment']['NEWSHUB_RUNTIME_ROLE'] == 'rss_sync'
    assert sync['environment']['RSS_FULL_CONTENT_ENABLED'] == services['app']['environment']['RSS_FULL_CONTENT_ENABLED']
    assert 'env_file' not in sync and 'ports' not in sync
    assert sync['read_only'] and sync['cap_drop'] == ['ALL']
    # No replacement of host app, BYOK gateway, legacy workers, or channel overlay.
    base = yaml.safe_load((ROOT / 'compose.prod.yaml').read_text())['services']
    assert base['app']['network_mode'] == 'host'
    assert base['app']['secrets'] == ['ai_byok_gateway_project_key']
    assert set(base) == {'app', 'migrate', 'indexer'}
    workspace = yaml.safe_load((ROOT / 'compose.workspace.prod.yaml').read_text())
    assert workspace['services']['channel-worker']['network_mode'] == 'host'


def test_rss_image_is_an_independent_target_with_its_own_lock():
    dockerfile = (ROOT / 'Dockerfile').read_text()
    lightweight = dockerfile.split(' AS rss-sync', 1)[1].split('\nFROM ', 1)[0]
    assert 'requirements-rss.lock' in lightweight
    assert 'backend/requirements.txt' not in lightweight
    assert 'frontend' not in lightweight and 'torch' not in lightweight.lower()
    assert 'USER 10001:10001' in lightweight
    assert dockerfile.rstrip().endswith('USER root')
    requirements = (ROOT / 'backend/requirements-rss.lock').read_text().splitlines()
    pins = [line for line in requirements if line and not line.startswith('#')]
    assert all('==' in line and '>=' not in line for line in pins)
    assert not any(word in '\n'.join(pins).lower() for word in ('torch', 'scrapy', 'feedparser', 'playwright', 'chromadb'))


def test_postgres_readiness_waits_for_tcp_before_starting_engine():
    """The bootstrap server accepts Unix sockets before TCP is available."""
    import shlex
    services = yaml.safe_load((ROOT / 'compose.rss.prod.yaml').read_text())['services']
    command = shlex.split(services['rss-db']['healthcheck']['test'][1])
    assert '-h' in command, 'Unix bootstrap readiness must not start Miniflux'
    assert command[command.index('-h') + 1] in {'127.0.0.1', 'localhost'}
    assert services['miniflux']['depends_on']['rss-db']['condition'] == 'service_healthy'


def test_application_defaults_full_content_on_with_explicit_opt_out(tmp_path):
    for value, expected in ((None, True), ('0', False), ('1', True)):
        env = runtime_env(tmp_path)
        env.pop('RSS_FULL_CONTENT_ENABLED', None)
        if value is not None:
            env['RSS_FULL_CONTENT_ENABLED'] = value
        result = subprocess.run([sys.executable, '-c',
            'from newsaggregator.settings import RSS_FULL_CONTENT_ENABLED; print(RSS_FULL_CONTENT_ENABLED)'],
            env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(expected)
