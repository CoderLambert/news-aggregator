"""Offline behavior checks for the content-keyed BYOK T00 CI cache."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT_SOURCE = Path(__file__).resolve().parents[1] / 'install-t00-deps.sh'


def executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)


class TestT00Cache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newshub-t00-test-')
        self.root = Path(self.temp.name)
        self.ops = self.root / 'ops/ci'
        self.ops.mkdir(parents=True)
        self.script = self.ops / 'install-t00-deps.sh'
        if SCRIPT_SOURCE.exists():
            shutil.copyfile(SCRIPT_SOURCE, self.script)
        tools = self.root / 'tools/byok_t00_probe'
        tools.mkdir(parents=True)
        self.sdk_lock = tools / 'requirements-sdk.lock'
        self.sdk_lock.write_text('openai==3.28.0\nanthropic==1.13.0\n')
        (tools / 'requirements-proxy.lock').write_text('litellm==1.105.0\n')
        (tools / 'prepare_proxy.py').write_text('# synthetic generator\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        executable(self.bin / 'node', '#!/bin/sh\necho v22.0.0\n')
        executable(self.bin / 'python3', r'''#!/usr/bin/env bash
set -eu
if [[ "$1" == -c ]]; then echo cpython-312-linux-x86_64; exit 0; fi
if [[ "$1" == -m && "$2" == venv ]]; then
    echo "venv:$3" >> "$TEST_INSTALL_LOG"
    mkdir -p "$3/bin"
    cat > "$3/bin/python" <<'PYSCRIPT'
#!/usr/bin/env bash
set -eu
prefix="$(cd "$(dirname "$0")/.." && pwd -P)"
if [[ "$1" == -m && "$2" == pip ]]; then
    if [[ "$3" == check ]]; then exit 0; fi
    if [[ "$3" == install ]]; then
        echo "install:$prefix" >> "$TEST_INSTALL_LOG"
        if [[ "${TEST_FAIL_ONCE:-0}" == 1 && ! -e "$TEST_INSTALL_LOG.failed" ]]; then
            touch "$TEST_INSTALL_LOG.failed"
            exit 89
        fi
        exit 0
    fi
fi
if [[ "$1" == -c ]]; then exit 0; fi
if [[ "$1" == *prepare_proxy.py ]]; then
    echo "prisma:$prefix" >> "$TEST_INSTALL_LOG"
    mkdir -p "$prefix/t00-prisma"
    printf '{}' > "$prefix/t00-prisma/runtime.json"
    printf 'synthetic' > "$prefix/t00-prisma/schema.prisma"
    exit 0
fi
exit 91
PYSCRIPT
    chmod +x "$3/bin/python"
    exit 0
fi
exit 92
''')
        self.out = self.root / 'output'
        self.log = self.root / 'calls'
        self.env = {**os.environ,
                    'PATH': f"{self.bin}:{os.environ['PATH']}",
                    'CI_T00_CACHE_ROOT': str(self.root / 'cache'),
                    'GITHUB_OUTPUT': str(self.out),
                    'TEST_INSTALL_LOG': str(self.log),
                    'HOME': str(self.root)}

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, **env):
        return subprocess.run(['bash', str(self.script)], cwd=self.root, env={**self.env, **env},
                              text=True, capture_output=True, timeout=30)

    def calls(self, prefix):
        if not self.log.exists():
            return []
        return [s for s in self.log.read_text().splitlines() if s.startswith(prefix)]

    def test_cache_hit_skips_install_and_changes_invalidate(self):
        first = self.run_script()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('MISS', first.stdout)
        self.assertEqual(len(self.calls('venv:')), 2)
        self.assertEqual(len(self.calls('install:')), 2)
        self.assertEqual(len(self.calls('prisma:')), 1)
        lines = self.out.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(Path(line.split('=', 1)[1]).is_file() for line in lines))
        second = self.run_script()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('HIT', second.stdout)
        self.assertEqual(len(self.calls('install:')), 2)
        self.sdk_lock.write_text('openai==3.29.0\nanthropic==1.13.0\n')
        third = self.run_script()
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertIn('MISS', third.stdout)
        self.assertEqual(len(self.calls('install:')), 4)

    def test_missing_prisma_manifest_invalidates_cache(self):
        self.assertEqual(self.run_script().returncode, 0)
        output = dict(line.split('=', 1) for line in self.out.read_text().splitlines())
        root = Path(output['proxy_python']).parent.parent
        (root / 't00-prisma/runtime.json').unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MISS', result.stdout)
        self.assertEqual(len(self.calls('prisma:')), 2)

    def test_incomplete_install_never_sets_ready(self):
        failed = self.run_script(TEST_FAIL_ONCE='1')
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(list((self.root / 'cache').glob('*/.ready')))
        recovered = self.run_script()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn('MISS', recovered.stdout)

    def test_refuses_symlink_cache_root_without_touching_target(self):
        target = self.root / 'protected'
        target.mkdir()
        (target / 'marker').write_text('preserve')
        link = self.root / 'cache-link'
        link.symlink_to(target, target_is_directory=True)
        result = self.run_script(CI_T00_CACHE_ROOT=str(link))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / 'marker').read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
