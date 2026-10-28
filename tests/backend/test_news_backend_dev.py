"""Standalone isolated-backend regressions; no project conftest or live data."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BackendEntryTests(unittest.TestCase):
    def test_dev_help_no_legacy_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'backend/newsaggregator').mkdir(parents=True)
            for name in ('news-server', 'news_dev.py', 'news_backend_dev.py'):
                source = ROOT / 'scripts' / name
                if source.exists():
                    shutil.copyfile(source, root / 'scripts' / name)
            for source in (ROOT / 'backend/newsaggregator').glob('dev_*.py'):
                shutil.copyfile(source, root / 'backend/newsaggregator' / source.name)
            result = subprocess.run(['bash', str(root / 'scripts/news-server'), 'dev', 'help'],
                                    env={'PATH': f'{Path(sys.executable).parent}:/usr/bin:/bin', 'HOME': tmp},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('init', result.stdout)
            self.assertFalse((root / 'logs').exists())


FAKE_MANAGE = r'''
import json, os, signal, socket, sqlite3, subprocess, sys, time
from pathlib import Path
state = Path(os.environ['NEWSHUB_DEV_RUNTIME'])
if 'migrate' in sys.argv:
    with sqlite3.connect(os.environ['DJANGO_DB_PATH']) as db:
        db.execute('create table if not exists synthetic (id integer)')
    sys.exit(0)
if os.environ.get('RUN_MAIN') != 'true':
    while True:
        child = subprocess.run([sys.executable, '-B', *sys.argv], env=dict(os.environ, RUN_MAIN='true'))
        if child.returncode != 3: sys.exit(0)
(state / 'environment.json').write_text(json.dumps(dict(os.environ)))
(state / 'child.pid').write_text(str(os.getpid()))
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Django WSGIServer contract.
sock.bind(('127.0.0.1', int(os.environ['NEWSHUB_DEV_BACKEND_PORT'])))
sock.listen()
while True: time.sleep(.05)
'''


class BackendIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newshub-backend-unit-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'backend/newsaggregator').mkdir(parents=True)
        (self.root / 'ops/ci').mkdir(parents=True)
        for name in ('news-server', 'news_dev.py', 'news_backend_dev.py'):
            shutil.copyfile(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        shutil.copyfile(ROOT / 'backend/newsaggregator/dev_runtime.py',
                        self.root / 'backend/newsaggregator/dev_runtime.py')
        (self.root / 'backend/manage.py').write_text(FAKE_MANAGE)
        # Only these lifecycle tests use a synthetic dependency checker.
        (self.root / 'ops/ci/check-backend-lock.py').write_text('raise SystemExit(0)\n')
        (self.root / '.env').write_text('LEAK_DOTENV=synthetic-sentinel\n')
        (self.root / 'backend/.env').write_text('LEAK_BACKEND_DOTENV=synthetic-sentinel\n')
        (self.root / 'backend/db.sqlite3').write_text('foreign-db-do-not-open')
        spec = importlib.util.spec_from_file_location('fixture_dev_runtime',
                                                     self.root / 'backend/newsaggregator/dev_runtime.py')
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.api, self.ui = self.free_port(), self.free_port()
        self.env = {'PATH': f'{Path(sys.executable).parent}:/usr/bin:/bin', 'HOME': str(self.base),
                    'PYTHONDONTWRITEBYTECODE': '1', 'NEWSHUB_DEV_PYTHON': sys.executable,
                    'NEWSHUB_DEV_STATE_DIR': str(self.base / 'state'),
                    'NEWSHUB_DEV_BACKEND_PORT': str(self.api), 'NEWSHUB_DEV_FRONTEND_PORT': str(self.ui)}
        self.records = {}

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def call(self, action, **changes):
        result = subprocess.run(['bash', str(self.root / 'scripts/news-server'), 'dev', action],
                                env=self.env | changes, capture_output=True, text=True, timeout=65)
        if result.returncode == 0 and action in {'start', 'restart'}:
            for path in (self.base / 'state').glob('*/backend/process.json'):
                self.records[path] = (json.loads(path.read_text()), changes)
        return result

    def prepare(self):
        result = self.call('init')
        self.assertEqual(result.returncode, 0, result.stderr)
        return next((self.base / 'state').glob('*/backend'))

    def tearDown(self):
        for path, (record, changes) in self.records.items():
            if path.exists():
                path.write_text(json.dumps(record))
                result = self.call('stop', **changes)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.temp.cleanup()

    def test_explicit_init_start_health_stop_preserves_only_synthetic_db(self):
        self.assertNotEqual(self.call('start').returncode, 0)
        directory = self.prepare()
        self.assertEqual(self.call('start').returncode, 0)
        first = json.loads((directory / 'process.json').read_text())
        self.assertEqual(self.call('health').returncode, 0)
        self.assertEqual(self.call('start').returncode, 0)
        self.assertEqual(json.loads((directory / 'process.json').read_text()), first)
        self.assertNotEqual(self.call('init').returncode, 0)
        self.assertEqual(self.call('stop').returncode, 0)
        self.assertNotEqual(self.call('health').returncode, 0)
        self.assertTrue((directory / 'db.sqlite3').exists())
        self.assertEqual((self.root / 'backend/db.sqlite3').read_text(), 'foreign-db-do-not-open')
        self.assertFalse((self.root / 'logs').exists())
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        # Frontend and backend share the same private state base.
        self.assertEqual((self.base / 'state').stat().st_mode & 0o777, 0o700)
        self.assertEqual((directory / 'db.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_environment_whitelist_drops_keys_paths_and_reload_flags(self):
        directory = self.prepare()
        result = self.call('start', OPENAI_API_KEY='synthetic-secret', AI_BYOK_GATEWAY_URL='http://example.invalid',
                           TRANSLATION_REDIS_URL='redis://example.invalid', RUN_MAIN='true',
                           PYTHONPATH='/untrusted', PUBLIC_AI_ENABLED='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads((directory / 'environment.json').read_text())
        for key in ('OPENAI_API_KEY', 'AI_BYOK_GATEWAY_URL', 'TRANSLATION_REDIS_URL',
                    'LEAK_DOTENV', 'LEAK_BACKEND_DOTENV'):
            self.assertNotIn(key, env)
        self.assertEqual(env['NEWSHUB_SKIP_DOTENV'], '1')
        self.assertEqual(env['NEWS_CRAWL_ONLY'], '1')
        self.assertEqual(env['PUBLIC_AI_ENABLED'], '0')
        self.assertEqual(env['AI_BYOK_ENABLED'], '0')
        self.assertEqual(env['CHATGPT_AUTH_MODE'], 'disabled')
        self.assertEqual(env['DJANGO_CSRF_TRUSTED_ORIGINS'],
                         f'http://127.0.0.1:{self.ui},http://127.0.0.1:{self.api}')
        for key in self.runtime.PATH_VARIABLES:
            self.assertTrue(Path(env[key]).is_relative_to(directory))
        # Two PIDs prove the inherited RUN_MAIN=true was dropped at launch.
        record = json.loads((directory / 'process.json').read_text())
        self.assertNotEqual(record['identity']['pid'], int((directory / 'child.pid').read_text()))
        self.assertNotIn('RUN_MAIN', self.runtime.environment(directory, self.api, self.ui))

    def test_wrong_data_path_and_reserved_ports_fail_without_touching_data(self):
        for changes in ({'DJANGO_DB_PATH': str(self.root / 'backend/db.sqlite3')},
                        {'CHROMA_DATA_DIR': '/somewhere'}, {'NEWSHUB_DEV_BACKEND_PORT': '9527'},
                        {'NEWSHUB_DEV_BACKEND_PORT': '19527'}, {'NEWSHUB_DEV_BACKEND_PORT': '0'},
                        {'NEWSHUB_DEV_BACKEND_PORT': str(self.ui)}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.call('init', **changes).returncode, 0)
        self.assertFalse(list((self.base / 'state').glob('*/backend/db.sqlite3')))

    def test_state_inside_git_or_symlink_is_rejected(self):
        (self.root / '.git').mkdir()
        for location in (str(self.root / 'state'), 'relative-state'):
            self.assertNotEqual(self.call('init', NEWSHUB_DEV_STATE_DIR=location).returncode, 0)
        (self.base / 'linked').symlink_to(self.root)
        self.assertNotEqual(self.call('init', NEWSHUB_DEV_STATE_DIR=str(self.base / 'linked/state')).returncode, 0)
        self.assertFalse((self.root / 'state').exists())

    def test_missing_or_partial_interpreter_refuses_before_migration(self):
        self.assertNotEqual(self.call('init', NEWSHUB_DEV_PYTHON='/missing/python').returncode, 0)
        (self.root / 'ops/ci/check-backend-lock.py').write_text('raise SystemExit(1)\n')
        result = self.call('init')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No installation attempted', result.stderr)
        self.assertFalse(list((self.base / 'state').glob('*/backend/db.sqlite3')))

    def test_port_conflict_leaves_foreign_listener_alive(self):
        self.prepare()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', self.api))
            sock.listen()
            result = self.call('start')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unavailable', result.stderr)
            with socket.create_connection(('127.0.0.1', self.api), timeout=1):
                pass
        self.assertFalse(list((self.base / 'state').glob('*/backend/process.json')))

    def test_recent_owned_connection_time_wait_does_not_block_restart(self):
        self.prepare()
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', self.api))
            listener.listen()
            with socket.create_connection(('127.0.0.1', self.api), timeout=1) as client:
                conn, _ = listener.accept()
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
                self.assertEqual(client.recv(1), b'')
        result = self.call('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call('health').returncode, 0)

    def test_foreign_symlink_hardlink_and_bad_marker_refuse_adoption(self):
        directory = self.prepare()
        marker = (directory / 'instance.json').read_text()
        original = directory / 'db.sqlite3'
        original.unlink()
        original.symlink_to(self.root / 'backend/db.sqlite3')
        self.assertNotEqual(self.call('init').returncode, 0)
        original.unlink()
        (self.root / 'backend/db.sqlite3').chmod(0o600)
        os.link(self.root / 'backend/db.sqlite3', original)
        self.assertNotEqual(self.call('init').returncode, 0)
        original.unlink()
        value = json.loads(marker)
        value['root'] = '/another/worktree'
        (directory / 'instance.json').write_text(json.dumps(value))
        self.assertNotEqual(self.call('init').returncode, 0)
        (directory / 'instance.json').unlink()
        (directory / 'db.sqlite3').write_text('unowned database')
        self.assertNotEqual(self.call('init').returncode, 0)
        self.assertEqual((directory / 'db.sqlite3').read_text(), 'unowned database')

    def test_stale_and_foreign_records_never_signal(self):
        directory = self.prepare()
        self.assertEqual(self.call('start').returncode, 0)
        path = directory / 'process.json'
        original = path.read_text()
        record = json.loads(original)
        record['identity']['start'] = '0'
        path.write_text(json.dumps(record))
        for action in ('health', 'stop', 'restart'):
            self.assertNotEqual(self.call(action).returncode, 0)
        with socket.create_connection(('127.0.0.1', self.api), timeout=1):
            pass
        path.write_text(original)
        self.assertEqual(self.call('health').returncode, 0)

    def test_restart_and_parallel_instances_have_independent_children(self):
        directory = self.prepare()
        self.assertEqual(self.call('start').returncode, 0)
        old_parent = json.loads((directory / 'process.json').read_text())['identity']['pid']
        old_child = int((directory / 'child.pid').read_text())
        self.assertEqual(self.call('restart').returncode, 0)
        self.assertNotEqual(json.loads((directory / 'process.json').read_text())['identity']['pid'], old_parent)
        self.assertFalse(Path(f'/proc/{old_child}').exists())
        second = {'NEWSHUB_DEV_INSTANCE': 'second', 'NEWSHUB_DEV_BACKEND_PORT': str(self.free_port())}
        self.assertEqual(self.call('init', **second).returncode, 0)
        self.assertEqual(self.call('start', **second).returncode, 0)
        self.assertEqual(self.call('stop', **second).returncode, 0)
        self.assertEqual(self.call('health').returncode, 0)

    def test_copied_record_cannot_stop_another_instance(self):
        first = self.prepare()
        self.assertEqual(self.call('start').returncode, 0)
        changes = {'NEWSHUB_DEV_INSTANCE': 'second', 'NEWSHUB_DEV_BACKEND_PORT': str(self.free_port())}
        self.assertEqual(self.call('init', **changes).returncode, 0)
        self.assertEqual(self.call('start', **changes).returncode, 0)
        second = next(p for p in (self.base / 'state').glob('*/backend') if p != first)
        path = second / 'process.json'
        original = path.read_text()
        path.write_text((first / 'process.json').read_text())
        result = self.call('stop', **changes)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('another instance', result.stderr)
        self.assertEqual(self.call('health').returncode, 0)
        with socket.create_connection(('127.0.0.1', int(changes['NEWSHUB_DEV_BACKEND_PORT'])), timeout=1):
            pass
        path.write_text(original)

    def test_concurrent_start_stop_serializes_without_orphans(self):
        directory = self.prepare()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.call, ['start', 'start']))
        self.assertTrue(all(result.returncode == 0 for result in results))
        child = int((directory / 'child.pid').read_text())
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.call, ['stop', 'stop']))
        self.assertTrue(all(result.returncode == 0 for result in results))
        self.assertFalse(Path(f'/proc/{child}').exists())
        self.assertFalse((directory / 'process.json').exists())

    def test_io_guard_blocks_outbound_and_unrelated_subprocesses(self):
        code = (f'import sys,socket,subprocess; sys.path.insert(0,{str(self.root / "backend")!r}); '
                'from newsaggregator.dev_runtime import install_io_guard; install_io_guard(29527); '
                'socket.create_connection(("127.0.0.1", 1),timeout=1)')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('External I/O is disabled', result.stderr)
        code = code.rsplit('; ', 1)[0] + '; subprocess.run(["/bin/true"])'
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Only Django autoreload', result.stderr)
        code = code.rsplit('; ', 1)[0] + f'; open({str(self.root / ".env")!r}).read()'
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Dotenv file access is disabled', result.stderr)


class RealProfileTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('django'), 'Complete CI-lock Python environment required')
    def test_real_settings_never_load_dotenv_or_inherit_credentials(self):
        with tempfile.TemporaryDirectory(prefix='newshub-profile-test-') as tmp:
            directory = Path(tmp)
            marker = directory / 'instance.json'
            marker.write_text(json.dumps({'kind': 'newshub-isolated-backend-v1', 'root': str(ROOT),
                                          'directory': tmp, 'id': '00000000-0000-0000-0000-000000000006',
                                          'secret': 'task6-synthetic-secret-' * 4}))
            marker.chmod(0o600)
            code = f"""
import sys, os
sys.path.insert(0, {str(ROOT / 'backend')!r})
from pathlib import Path
import dotenv
original_exists = Path.exists
Path.exists = lambda self: True if self.name == '.env' else original_exists(self)
def forbidden(*args, **kwargs):
    raise AssertionError('dotenv was consulted')
dotenv.load_dotenv = forbidden
import newsaggregator.dev_settings as settings
assert 'OPENAI_API_KEY' not in os.environ
assert 'TRANSLATION_REDIS_URL' not in os.environ
assert 'RUN_MAIN' not in os.environ
assert settings.DATABASES['default']['NAME'] == Path({tmp!r}) / 'db.sqlite3'
assert settings.PUBLIC_AI_ENABLED is False
assert settings.AI_BYOK_ENABLED is False
assert settings.CHATGPT_AUTH_MODE == 'disabled'
assert settings.FULL_CONTENT_WORKER_ENABLED is False
assert settings.CORS_ALLOW_ALL_ORIGINS is False
assert settings.CSRF_TRUSTED_ORIGINS == ['http://127.0.0.1:25173', 'http://127.0.0.1:29527']
assert str(settings.CHATGPT_DEPLOYMENT_INSTANCE_FILE).startswith({tmp!r})
assert 'DJANGO_AUTORELOAD_ENV' not in os.environ
print('isolated real settings PASS')
"""
            env = {'PATH': '/usr/bin:/bin', 'NEWSHUB_DEV_RUNTIME': tmp,
                   'NEWSHUB_DEV_BACKEND_PORT': '29527', 'NEWSHUB_DEV_FRONTEND_PORT': '25173',
                   'OPENAI_API_KEY': 'synthetic-poison', 'TRANSLATION_REDIS_URL': 'redis://example.invalid',
                   'DJANGO_DB_PATH': '/must/not/open.sqlite3', 'PUBLIC_AI_ENABLED': '1',
                   'DJANGO_AUTORELOAD_ENV': 'true'}
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code], env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('isolated real settings PASS', result.stdout)
            self.assertFalse((directory / 'db.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
