"""Dependency-free entry for the Pi-native builder's offline Node regressions."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class PiImageBuilderTests(unittest.TestCase):
    def test_native_builder_offline_contracts(self):
        node = os.environ.get('NEWSHUB_NODE_BINARY') or shutil.which('node')
        if not node:
            self.skipTest('Node 22 is required; no installation is performed')
        with tempfile.TemporaryDirectory(prefix='newshub-pi-offline-') as home:
            env = {'PATH': os.environ.get('PATH', ''), 'HOME': home, 'LANG': 'C.UTF-8'}
            version = subprocess.run([node, '--version'], env=env, text=True, capture_output=True, timeout=10)
            if version.returncode or not version.stdout.startswith('v22.'):
                self.skipTest('Use CI Node 22 or NEWSHUB_NODE_BINARY pointing to compatible Node 22')
            result = subprocess.run(
                [node, '--test', str(ROOT / '.pi/extensions/newshub-image-builder/tests/offline.test.mjs')],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('# fail 0', result.stdout)


if __name__ == '__main__':
    unittest.main()
