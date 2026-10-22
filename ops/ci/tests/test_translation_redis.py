"""The Redis wrapper keeps command failures and removes only its own resources."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class TranslationRedisWrapperTests(unittest.TestCase):
    def test_child_failure_keeps_exit_code_and_cleans_its_own_container_and_socket_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            docker = path / 'docker'
            docker.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
with open(os.environ['FAKE_DOCKER_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1]=='run': print('synthetic-container-id')
if sys.argv[1]=='exec': print('PONG')
''')
            docker.chmod(0o700)
            result_path = path / 'child.json'
            code = ('import os,json,sys;from pathlib import Path;'
                    'Path(sys.argv[1]).write_text(json.dumps(dict(socket=os.environ.get("TEST_TRANSLATION_REDIS_SOCKET"),'
                    'url=os.environ.get("TEST_TRANSLATION_REDIS_URL"))));sys.exit(7)')
            result = subprocess.run(['bash', 'ops/ci/with-translation-redis.sh', sys.executable,
                                     '-c', code, str(result_path)], cwd=ROOT,
                                    env={**os.environ, 'PATH': str(path) + os.pathsep + os.environ['PATH'],
                                         'TMPDIR': tmp, 'PYTHON_BIN': sys.executable,
                                         'TEST_TRANSLATION_REDIS_URL': 'must-not-be-used',
                                         'FAKE_DOCKER_LOG': str(path / 'docker.log')},
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 7, result.stderr)
            child = json.loads(result_path.read_text())
            self.assertIsNone(child['url'])
            self.assertFalse(Path(child['socket']).parent.exists())
            calls = [json.loads(line) for line in (path / 'docker.log').read_text().splitlines()]
            self.assertEqual(calls[-1], ['rm', '-f', 'synthetic-container-id'])
            run = calls[0]
            self.assertIn('--network', run)
            self.assertEqual(run[run.index('--network') + 1], 'none')
            self.assertEqual(run[run.index('--port') + 1], '0')
            self.assertNotIn('--privileged', run)
            self.assertNotIn('-p', run)
