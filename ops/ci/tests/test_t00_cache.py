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
                    'HOME': str(self.root),
                    'PIP_CACHE_DIR': str(self.root / 'downloads/pip')}

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, *args, **env):
        return subprocess.run(['bash', str(self.script), *args], cwd=self.root, env={**self.env, **env},
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
        self.assertFalse(list((self.root / 'cache').glob('*/.newshub-ready')))
        self.assertFalse((self.root / 'cache/.current-key').exists())
        recovered = self.run_script()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn('MISS', recovered.stdout)

    def test_status_is_read_only_and_cache_only_needs_no_actions_output(self):
        status = self.run_script('--status', GITHUB_OUTPUT='')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn('CACHE_KIND=t00', status.stdout)
        self.assertIn('STATUS=MISSING', status.stdout)
        self.assertFalse((self.root / 'cache').exists())
        self.assertFalse((self.root / 'downloads').exists())
        self.assertFalse(self.out.exists())

        warmed = self.run_script('--cache-only', GITHUB_OUTPUT='')
        self.assertEqual(warmed.returncode, 0, warmed.stderr)
        cache = self.root / 'cache'
        key = (cache / '.current-key').read_text().strip()
        self.assertEqual((cache / key / '.newshub-ready').read_text().strip(), key)
        before = self.log.read_text()
        hit = self.run_script('--status', GITHUB_OUTPUT='')
        self.assertEqual(hit.returncode, 0, hit.stderr)
        self.assertIn('STATUS=HIT', hit.stdout)
        self.assertEqual(self.log.read_text(), before)
        self.assertFalse(self.out.exists())

    def test_legacy_ready_marker_is_migrated_without_reinstalling(self):
        self.assertEqual(self.run_script().returncode, 0)
        cache = self.root / 'cache'
        key = (cache / '.current-key').read_text().strip()
        entry = cache / key
        (entry / '.newshub-ready').rename(entry / '.ready')
        (entry / '.prisma-sha256').unlink()
        before = self.log.read_text()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('HIT', result.stdout)
        self.assertEqual(self.log.read_text(), before)
        self.assertTrue((entry / '.newshub-ready').is_file())
        self.assertTrue((entry / '.prisma-sha256').is_file())

    def test_modified_prisma_manifest_invalidates_cache(self):
        self.assertEqual(self.run_script().returncode, 0)
        output = dict(line.split('=', 1) for line in self.out.read_text().splitlines())
        root = Path(output['proxy_python']).parent.parent
        (root / 't00-prisma/runtime.json').write_text('corrupt')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MISS', result.stdout)
        self.assertEqual(len(self.calls('prisma:')), 2)

    def test_unified_gc_preserves_current_and_limits_successful_history(self):
        maintenance = SCRIPT_SOURCE.parent / 'cache-maintenance.py'
        for version in range(4):
            self.sdk_lock.write_text(f'openai==3.{version}.0\n')
            result = self.run_script()
            self.assertEqual(result.returncode, 0, result.stderr)
        cache = self.root / 'cache'
        current = (cache / '.current-key').read_text().strip()
        self.assertEqual(len(list(cache.glob('*/.newshub-ready'))), 4)
        planned = subprocess.run(
            [os.sys.executable, str(maintenance), 'gc', '--root', str(cache)],
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertIn('WOULD_REMOVE', planned.stdout)
        self.assertEqual(len(list(cache.glob('*/.newshub-ready'))), 4)
        cleaned = subprocess.run(
            [os.sys.executable, str(maintenance), 'gc', '--root', str(cache), '--execute'],
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertTrue((cache / current / '.newshub-ready').is_file())
        self.assertLessEqual(len(list(cache.glob('*/.newshub-ready'))), 3)
        self.assertTrue(Path(self.env['PIP_CACHE_DIR']).is_dir())

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
