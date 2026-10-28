"""Standalone launcher regressions: python3 tests/backend/test_news_dev.py.

Only synthetic roots, loopback sockets and owned fake Node processes are used.
Direct unittest execution avoids loading Django or repository dotenv files.
"""
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
FAKE_NODE = r'''
import json, os, signal, socket, sys, time
from pathlib import Path
if sys.argv[1:] == ['--version']:
    print(os.environ.get('TEST_NODE_VERSION', 'v22.23.3'))
    sys.exit(0)
Path(os.environ['TEST_ARGS']).write_text(json.dumps({'argv': sys.argv[1:], 'cache': os.environ.get('NEWSHUB_DEV_CACHE_DIR')}))
if 'build' in sys.argv:
    sys.exit(int(os.environ.get('TEST_BUILD_EXIT', '0')))
if os.environ.get('TEST_START_FAIL'):
    sys.exit(7)
sock = socket.socket()
sock.bind((sys.argv[sys.argv.index('--host')+1], int(sys.argv[sys.argv.index('--port')+1])))
sock.listen()
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
while True: time.sleep(.05)
'''


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newshub-dev-test-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        (self.root / 'scripts').mkdir(parents=True)
        for name in ('news-dev', 'news_dev.py'):
            source = ROOT / 'scripts' / name
            if source.exists():
                shutil.copyfile(source, self.root / 'scripts' / name)
        self.vite = self.root / 'frontend/node_modules/vite/bin/vite.js'
        self.vite.parent.mkdir(parents=True)
        self.vite.write_text('// synthetic Vite placeholder, never executed\n')
        self.node = self.base / 'node'
        self.node.write_text(f'#!{sys.executable}\n' + FAKE_NODE)
        self.node.chmod(0o700)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        self.env = {
            'PATH': os.pathsep.join([str(Path(sys.executable).parent), '/usr/bin', '/bin']),
            'HOME': str(self.base), 'PYTHONDONTWRITEBYTECODE': '1',
            'NEWSHUB_DEV_NODE': str(self.node), 'NEWSHUB_DEV_PORT': str(self.port),
            'NEWSHUB_DEV_STATE_DIR': str(self.base / 'state'),
            'TEST_ARGS': str(self.base / 'args.json'),
        }
        self.spec = importlib.util.spec_from_file_location('synthetic_news_dev', self.root / 'scripts/news_dev.py')
        self.module = importlib.util.module_from_spec(self.spec) if self.spec else None
        if self.module and (self.root / 'scripts/news_dev.py').exists():
            self.spec.loader.exec_module(self.module)
        self.records = []

    def call(self, action, **changes):
        result = subprocess.run(['bash', str(self.root / 'scripts/news-dev'), action],
                                env=self.env | changes, text=True, capture_output=True, timeout=25)
        # Preserve original identities so tests that damage records still clean up only their own processes.
        for path in (self.base / 'state').glob('*/process.json'):
            try:
                record = json.loads(path.read_text())
                if self.module and self.module.owned(record):
                    self.records.append(record)
            except (ValueError, OSError):
                pass
        return result

    def record_path(self):
        return next((self.base / 'state').glob('*/process.json'))

    def tearDown(self):
        if self.module:
            for record in self.records:
                if self.module.owned(record):
                    self.module.terminate(record)
        self.temp.cleanup()

    def test_no_implicit_package_download(self):
        source = (self.root / 'scripts/news-dev').read_text()
        self.assertNotIn('npx', source)

    def test_start_health_stop_and_private_state(self):
        result = self.call('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.record_path()
        record = json.loads(path.read_text())
        args = json.loads((self.base / 'args.json').read_text())
        self.assertIn('--strictPort', args['argv'])
        self.assertEqual(args['argv'][args['argv'].index('--host')+1], '127.0.0.1')
        self.assertEqual(args['cache'], str(path.parent / 'vite-cache'))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.call('health').returncode, 0)
        self.assertEqual(self.call('start').returncode, 0)
        self.assertEqual(json.loads(path.read_text())['identity'], record['identity'])
        self.assertEqual(self.call('stop').returncode, 0)
        self.assertFalse(self.module.owned(record))
        self.assertFalse(path.exists())
        self.assertNotEqual(self.call('health').returncode, 0)

    def test_wrong_node_and_missing_dependency_fail_without_install(self):
        result = self.call('start', TEST_NODE_VERSION='v24.1.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Node 22', result.stderr)
        self.assertFalse((self.base / 'args.json').exists())
        self.vite.unlink()
        result = self.call('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no dependencies will be installed', result.stderr)
        self.assertFalse((self.base / 'args.json').exists())

    def test_port_conflict_does_not_start_or_stop_foreign_listener(self):
        with socket.socket() as foreign:
            foreign.bind(('127.0.0.1', self.port))
            foreign.listen()
            result = self.call('start')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unavailable', result.stderr)
            self.assertFalse((self.base / 'args.json').exists())
            with socket.create_connection(('127.0.0.1', self.port), timeout=1):
                pass

    def test_start_failure_has_no_success_record(self):
        result = self.call('start', TEST_START_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exited (7)', result.stderr)
        self.assertFalse(list((self.base / 'state').glob('*/process.json')))

    def test_stale_identity_never_signals_and_restart_fails_closed(self):
        self.assertEqual(self.call('start').returncode, 0)
        path = self.record_path()
        original = json.loads(path.read_text())
        stale = json.loads(path.read_text())
        stale['identity']['start'] = '0'
        path.write_text(json.dumps(stale))
        self.assertNotEqual(self.call('health').returncode, 0)
        self.assertNotEqual(self.call('stop').returncode, 0)
        self.assertNotEqual(self.call('restart').returncode, 0)
        self.assertTrue(self.module.owned(original))
        self.assertEqual(json.loads(path.read_text()), stale)
        path.write_text(json.dumps(original))
        self.assertEqual(self.call('stop').returncode, 0)

    def test_foreign_pid_record_cannot_stop_test_runner(self):
        self.assertEqual(self.call('start').returncode, 0)
        path = self.record_path()
        record = json.loads(path.read_text())
        record['identity'] = self.module.identity(os.getpid())
        path.write_text(json.dumps(record))
        result = self.call('stop')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no process was stopped', result.stderr)
        self.assertIsNotNone(self.module.identity(os.getpid()))

    def test_instances_do_not_share_state_or_stop_each_other(self):
        self.assertEqual(self.call('start').returncode, 0)
        first = json.loads(self.record_path().read_text())
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            second_port = str(probe.getsockname()[1])
        changes = {'NEWSHUB_DEV_INSTANCE': 'second', 'NEWSHUB_DEV_PORT': second_port}
        result = self.call('start', **changes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list((self.base / 'state').glob('*/process.json'))), 2)
        self.assertEqual(self.call('stop', **changes).returncode, 0)
        self.assertTrue(self.module.owns_listener(first))

    def test_worktrees_do_not_share_default_instance(self):
        self.assertEqual(self.call('start').returncode, 0)
        first = json.loads(self.record_path().read_text())
        other = self.base / 'another-source'
        shutil.copytree(self.root, other)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = str(probe.getsockname()[1])
        env = self.env | {'NEWSHUB_DEV_PORT': port}
        command = ['bash', str(other / 'scripts/news-dev')]
        try:
            result = subprocess.run(command + ['start'], env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list((self.base / 'state').glob('*/process.json'))), 2)
            result = subprocess.run(command + ['stop'], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(self.module.owns_listener(first))
        finally:
            subprocess.run(command + ['stop'], env=env, capture_output=True, timeout=15)

    def test_malformed_record_never_signals(self):
        self.assertEqual(self.call('start').returncode, 0)
        path = self.record_path()
        original = json.loads(path.read_text())
        for text in ('not-json', '{"identity": {"pid": 1, "argv": 9}}'):
            path.write_text(text)
            result = self.call('stop')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Invalid process record', result.stderr)
            self.assertTrue(self.module.owned(original))
        path.write_text(json.dumps(original))

    def test_log_symlink_cannot_modify_foreign_file(self):
        self.vite.unlink()
        self.assertNotEqual(self.call('start').returncode, 0)
        directory = next((self.base / 'state').iterdir())
        foreign = self.base / 'foreign.log'
        foreign.write_text('untouched')
        (directory / 'vite.log').symlink_to(foreign)
        self.vite.write_text('// synthetic')
        result = self.call('start')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(foreign.read_text(), 'untouched')
        self.assertFalse((self.base / 'args.json').exists())

    def test_restart_replaces_only_owned_process(self):
        self.assertEqual(self.call('start').returncode, 0)
        first = json.loads(self.record_path().read_text())
        self.assertEqual(self.call('restart').returncode, 0)
        second = json.loads(self.record_path().read_text())
        self.assertNotEqual(first['identity'], second['identity'])
        self.assertFalse(self.module.owned(first))
        self.assertTrue(self.module.owns_listener(second))

    def test_build_retains_exit_code_without_dev_server_flags(self):
        result = self.call('build', TEST_BUILD_EXIT='9')
        self.assertEqual(result.returncode, 9)
        argv = json.loads((self.base / 'args.json').read_text())['argv']
        self.assertEqual(argv[-1], 'build')
        self.assertNotIn('--host', argv)
        self.assertFalse((self.base / 'state').exists())

    def test_invalid_instance_and_port_fail_closed(self):
        for changes in ({'NEWSHUB_DEV_INSTANCE': '../other'}, {'NEWSHUB_DEV_PORT': '0'},
                        {'NEWSHUB_DEV_PORT': '65536'}, {'NEWSHUB_DEV_PORT': 'not-a-port'}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.call('start', **changes).returncode, 0)
        self.assertFalse((self.base / 'args.json').exists())

    def test_state_symlink_is_rejected(self):
        target = self.base / 'elsewhere'
        target.mkdir()
        (self.base / 'state').symlink_to(target, target_is_directory=True)
        self.assertNotEqual(self.call('start').returncode, 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_status_and_help_do_not_create_runtime_state(self):
        self.assertEqual(self.call('status').returncode, 0)
        self.assertEqual(self.call('help').returncode, 0)
        self.assertFalse((self.base / 'state').exists())
        self.assertFalse((self.root / 'logs').exists())


class ViteConfigTests(unittest.TestCase):
    """Load the actual config with inert plugin stubs; no build or package install."""
    @classmethod
    def setUpClass(cls):
        cls.node = os.environ.get('NEWSHUB_TEST_NODE22') or shutil.which('node')
        if not cls.node:
            raise RuntimeError('Set NEWSHUB_TEST_NODE22 to an existing Node 22 executable.')
        version = subprocess.run([cls.node, '--version'], capture_output=True, text=True, timeout=5)
        if version.returncode or not version.stdout.startswith('v22.'):
            raise RuntimeError('These config regressions require Node 22; no installation is attempted.')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newshub-vite-config-')
        self.root = Path(self.temp.name)
        (self.root / 'package.json').write_text('{"type":"module"}')
        shutil.copyfile(ROOT / 'frontend/vite.config.js', self.root / 'vite.config.js')
        for name in ('vite', '@vitejs/plugin-react', '@tailwindcss/vite'):
            package = self.root / 'node_modules' / name
            package.mkdir(parents=True)
            (package / 'package.json').write_text('{"type":"module","exports":"./index.js"}')
            (package / 'index.js').write_text('export const defineConfig = x => x;'
                                               if name == 'vite' else 'export default () => ({});')

    def tearDown(self):
        self.temp.cleanup()

    def config(self, **env):
        code = """
import config from './vite.config.js';
const proxy = config.server.proxy['/api'];
let callback;
proxy.configure({on: (event, fn) => { if (event === 'proxyRes') callback = fn; }});
const response = {headers: {'content-type':'text/event-stream', 'content-encoding':'gzip'}};
callback(response);
console.log(JSON.stringify({target:proxy.target, host:config.server.host, strict:config.server.strictPort,
 timeout:proxy.timeout, proxyTimeout:proxy.proxyTimeout, changeOrigin:proxy.changeOrigin,
 headers:response.headers, cacheDir:config.cacheDir}));
"""
        return subprocess.run([self.node, '--input-type=module', '-e', code], cwd=self.root,
                              env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root)} | env,
                              capture_output=True, text=True, timeout=10)

    def test_default_proxy_and_sse_contract_preserved(self):
        result = self.config()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['target'], 'http://127.0.0.1:9527')
        self.assertEqual(value['host'], '127.0.0.1')
        self.assertTrue(value['strict'])
        self.assertTrue(value['changeOrigin'])
        self.assertEqual((value['timeout'], value['proxyTimeout']), (180000, 180000))
        self.assertEqual(value['headers']['x-accel-buffering'], 'no')
        self.assertEqual(value['headers']['cache-control'], 'no-cache')
        self.assertNotIn('content-encoding', value['headers'])

    def test_configurable_loopback_origin_and_isolated_cache(self):
        for target in ('http://127.0.0.1:29527', 'http://localhost:29527', 'http://[::1]:29527'):
            with self.subTest(target=target):
                result = self.config(NEWSHUB_DEV_API_TARGET=target, NEWSHUB_DEV_CACHE_DIR=str(self.root / 'cache'))
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value['target'], target)
                self.assertEqual(value['cacheDir'], str(self.root / 'cache'))

    def test_remote_credentials_paths_and_invalid_origins_rejected(self):
        for target in ('', 'not-url', 'file:///tmp/test', 'https://example.com',
                       'http://user:password@localhost:9527', 'http://localhost:9527/api',
                       'http://localhost:9527/?x=y', 'http://localhost:9527/#fragment'):
            with self.subTest(target=target):
                result = self.config(NEWSHUB_DEV_API_TARGET=target)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must be a loopback HTTP(S) origin', result.stderr)


if __name__ == '__main__':
    unittest.main()
