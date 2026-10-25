"""Offline build command/telemetry regressions; no Docker service or downloads."""
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "ops/ci/build-production.py"
SPEC = importlib.util.spec_from_file_location("build_production", SCRIPT)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
SHA = "a" * 40


class BuildMetricsTests(unittest.TestCase):
    def test_interleaved_cache_and_install_are_distinct_and_redacted(self):
        metrics = build.BuildMetrics()
        for line in [
            '#1 [runtime-base 4/11] RUN pip install "torch==2.14.1+cpu"',
            '#2 [frontend-build 4/6] RUN npm ci',
            '#1 1.5 Using cached private-package https://user:secret@example.invalid',
            '#2 CACHED',
            '#1 DONE 33.6s',
            '#3 [runtime-base 6/11] RUN pip install -r requirements.txt',
            '#3 0.5 Using cached wheel',
            '#3 DONE 63.1s',
            '#4 exporting to image',
            '#4 DONE 8.5s',
        ]:
            metrics.feed(line)
        report = metrics.result(sha=SHA, exit_code=0, wall_seconds=109)
        self.assertEqual(report['dependency_cache_hits'], 1)
        self.assertEqual(report['dependency_steps'], 3)
        self.assertEqual(report['wall_seconds'], 109)
        self.assertEqual(report['steps'][0]['seconds'], 33.6)
        self.assertNotIn('secret', json.dumps(report) + build.markdown(report))
        self.assertNotIn('example.invalid', json.dumps(report))

    def test_missing_terminal_and_failure_never_count_as_hit(self):
        metrics = build.BuildMetrics()
        for line in [
            '#1 [runtime-base 4/11] RUN pip install torch==1',
            '#2 [frontend-build 4/6] RUN npm ci',
            '#2 ERROR: sensitive error text',
            '#3 [frontend-build 5/6] COPY frontend/ ./',
            '#3 CANCELED',
        ]:
            metrics.feed(line)
        report = metrics.result(sha=SHA, exit_code=7, wall_seconds=2)
        self.assertEqual([s['status'] for s in report['steps']], ['incomplete', 'failed', 'cancelled'])
        self.assertEqual(report['dependency_cache_hits'], 0)
        self.assertNotIn('sensitive', json.dumps(report))
        self.assertIn('unknown', build.markdown(report))

    def run_build(self, root, exit_code=0, *, sha=SHA, host='unix:///ci-docker/docker.sock', image=None,
                  bad_report=False, bad_summary=False):
        binary = root / 'bin'
        binary.mkdir(exist_ok=True)
        docker = binary / 'docker'
        docker.write_text(
            f'#!{sys.executable}\n'
            'import json, os, pathlib, sys\n'
            'pathlib.Path(os.environ["CALLS"]).write_text(json.dumps(sys.argv[1:]))\n'
            'print("#1 [runtime-base 4/11] RUN pip install torch==1", flush=True)\n'
            'print("#1 CACHED", flush=True)\n'
            f'sys.exit({exit_code})\n'
        )
        docker.chmod(0o755)
        report = root / 'report.json'
        summary = root / 'summary.md'
        if bad_report:
            report.mkdir()
        if bad_summary:
            summary.mkdir()
        environment = {
            'PATH': str(binary), 'HOME': str(root), 'DOCKER_HOST': host,
            'CALLS': str(root / 'calls.json'), 'GITHUB_STEP_SUMMARY': str(summary),
            'HARNESS': str(root),
        }
        image = image if image is not None else f'newshub:ci-{sha}'
        result = subprocess.run(
            [sys.executable, str(SCRIPT), '--sha', sha, '--image', image, '--report', str(report)],
            cwd=root, env=environment, capture_output=True, text=True, timeout=10,
        )
        return result, report

    def test_real_cli_invokes_exact_target_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, report = self.run_build(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / 'calls.json').read_text()), [
                'build', '--progress=plain', '--target', 'production', '--build-arg',
                f'RELEASE_SHA={SHA}', '--tag', f'newshub:ci-{SHA}', '.',
            ])
            self.assertEqual(json.loads(report.read_text())['exit_code'], 0)
            self.assertIn('Dependency layer hits: 1/1', (root / 'summary.md').read_text())
            self.assertIn('#1 CACHED', result.stdout)

    def test_docker_failure_survives_reporting_failure(self):
        for bad_report in (False, True):
            with self.subTest(bad_report=bad_report), tempfile.TemporaryDirectory() as temp:
                result, report = self.run_build(Path(temp), 23, bad_report=bad_report)
                self.assertEqual(result.returncode, 23)
                if not bad_report:
                    self.assertEqual(json.loads(report.read_text())['exit_code'], 23)

    def test_reporting_failure_preserves_build_failure_and_fails_closed_on_success(self):
        for docker_status, expected_status in ((0, 1), (23, 23)):
            with self.subTest(docker_status=docker_status), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                result, report = self.run_build(root, docker_status, bad_summary=True)
                self.assertEqual(result.returncode, expected_status)
                self.assertIn('production build metrics could not be written', result.stderr)
                self.assertEqual(json.loads(report.read_text())['exit_code'], docker_status)

    def test_sigterm_is_forwarded_to_docker_process_group_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / 'bin'
            binary.mkdir()
            docker = binary / 'docker'
            docker.write_text(
                f'#!{sys.executable}\n'
                'import os, signal, subprocess, sys, time\n'
                'from pathlib import Path\n'
                'root = Path(os.environ["HARNESS"])\n'
                'child_code = """\n'
                'import os, signal, time\n'
                'from pathlib import Path\n'
                'root = Path(os.environ["HARNESS"])\n'
                'def stop(signum, _frame):\n'
                '    (root / "child.signal").write_text(str(signum))\n'
                '    raise SystemExit(0)\n'
                'signal.signal(signal.SIGTERM, stop)\n'
                '(root / "child.pid.tmp").write_text(str(os.getpid()))\n'
                '(root / "child.pid.tmp").replace(root / "child.pid")\n'
                'while True: time.sleep(0.02)\n'
                '"""\n'
                'def stop(signum, _frame):\n'
                '    (root / "docker.signal").write_text(str(signum))\n'
                '    child.wait(timeout=5)\n'
                '    raise SystemExit(128 + signum)\n'
                'signal.signal(signal.SIGTERM, stop)\n'
                '(root / "docker.pid.tmp").write_text(str(os.getpid()))\n'
                '(root / "docker.pid.tmp").replace(root / "docker.pid")\n'
                'child = subprocess.Popen([sys.executable, "-c", child_code])\n'
                'while True: time.sleep(0.02)\n'
            )
            docker.chmod(0o755)
            report = root / 'report.json'
            environment = {
                'PATH': str(binary), 'HOME': str(root), 'DOCKER_HOST': 'unix:///ci-docker/docker.sock',
                'HARNESS': str(root), 'GITHUB_STEP_SUMMARY': str(root / 'summary.md'),
            }
            process = subprocess.Popen(
                [sys.executable, str(SCRIPT), '--sha', SHA, '--image', f'newshub:ci-{SHA}',
                 '--report', str(report)],
                cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                deadline = time.monotonic() + 5
                # PID paths are atomically published only after complete writes.
                while time.monotonic() < deadline and not (
                    (root / 'docker.pid').exists() and (root / 'child.pid').exists()
                ) and process.poll() is None:
                    time.sleep(0.02)
                self.assertIsNone(process.poll(), 'wrapper exited before the fake build was ready')
                self.assertTrue((root / 'child.pid').exists(), 'fake Docker child did not start')
                child_pid = int((root / 'child.pid').read_text())
                process.send_signal(signal.SIGTERM)
                output, _ = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 143, output)
                self.assertEqual((root / 'docker.signal').read_text(), str(signal.SIGTERM))
                self.assertEqual((root / 'child.signal').read_text(), str(signal.SIGTERM))
                self.assertEqual(json.loads(report.read_text())['exit_code'], 143)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                docker_pid_file = root / 'docker.pid'

                def kill_and_wait_for_docker_group():
                    if not docker_pid_file.is_file():
                        return True
                    try:
                        docker_pgid = int(docker_pid_file.read_text())
                    except (OSError, ValueError):
                        return False
                    if docker_pgid <= 0:
                        return False
                    try:
                        os.killpg(docker_pgid, 0)
                    except ProcessLookupError:
                        return True
                    except PermissionError:
                        return False
                    try:
                        os.killpg(docker_pgid, signal.SIGKILL)
                    except ProcessLookupError:
                        return True
                    except PermissionError:
                        return False
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        try:
                            os.killpg(docker_pgid, 0)
                        except ProcessLookupError:
                            return True
                        except PermissionError:
                            return False
                        time.sleep(0.02)
                    return False

                group_clean = True
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        group_clean = kill_and_wait_for_docker_group()
                        process.kill()
                        process.communicate()
                group_clean = kill_and_wait_for_docker_group() and group_clean
                self.assertTrue(group_clean, 'fake Docker process group survived cleanup')

    def test_invalid_revision_image_and_host_socket_fail_before_docker(self):
        for args in (
            {'sha': 'not-a-sha'},
            {'image': 'newshub:latest'},
            {'host': 'unix:///var/run/docker.sock'},
        ):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                result, _ = self.run_build(root, **args)
                self.assertEqual(result.returncode, 2)
                self.assertFalse((root / 'calls.json').exists())


class BuildInputContractTests(unittest.TestCase):
    def test_external_images_are_digest_pinned_and_revision_is_late(self):
        text = (ROOT / 'Dockerfile').read_text()
        self.assertRegex(text.splitlines()[0], r'^# syntax=.*@sha256:[a-f0-9]{64}$')
        for line in text.splitlines():
            if line.startswith('FROM ') and not line.startswith('FROM runtime-base'):
                self.assertRegex(line, r'@sha256:[a-f0-9]{64}(?: AS .*)?$')
        production = text.split('FROM runtime-base AS production', 1)[1].split('FROM ', 1)[0]
        self.assertLess(production.index('groupadd'), production.index('ARG RELEASE_SHA'))
        self.assertLess(production.index('ARG RELEASE_SHA'), production.index('USER 10001:10001'))
        self.assertIn("grep -Eq '^[0-9a-f]{40}$'", production)
        # Source changes in the production runtime remain downstream of BOTH
        # expensive dependency installs; the earlier RSS stage has its own COPY.
        runtime_base = text.split(' AS runtime-base', 1)[1].split('\nFROM ', 1)[0]
        self.assertLess(runtime_base.index('"torch==${TORCH_VERSION}"'), runtime_base.index('COPY backend/ /app/backend/'))
        self.assertLess(runtime_base.index('pip install -r /app/backend/requirements.txt'), runtime_base.index('COPY backend/ /app/backend/'))
        self.assertNotIn('ARG RELEASE_SHA', runtime_base)
        frontend = text.split(' AS frontend-build', 1)[1].split('\nFROM ', 1)[0]
        self.assertLess(frontend.index('npm ci'), frontend.index('COPY frontend/ ./'))
        self.assertNotIn('ARG RELEASE_SHA', frontend)
        # Guard the approved Dockerfile's shell and JSON COPY/ADD forms.
        # New instruction forms require reviewing/extending this contract.
        for line in text.splitlines():
            if re.match(r'^\s*(COPY|ADD)\s', line):
                command = re.sub(r'^\s*(?:COPY|ADD)\s+(?:--\S+\s+)*', '', line)
                if command.startswith('['):
                    sources = json.loads(command)[:-1]
                else:
                    sources = command.split()[:-1]
                self.assertFalse(any(source.strip('\"\'') in ('.', './') for source in sources), line)

    def test_only_explicit_nonruntime_trees_are_excluded(self):
        patterns = (ROOT / '.dockerignore').read_text().splitlines()
        # An allowlist exception can reintroduce excluded inputs/secrets.
        # Review such changes explicitly instead of accepting a later override.
        self.assertFalse(any(line.strip().startswith('!') for line in patterns))
        for path in ('.worktrees/', '.agents/', '.pi/', 'docs/', 'tests/', 'backend/api/tests/', 'frontend/tests/'):
            self.assertIn(path, patterns)
        for path in ('backend/', 'frontend/', 'scripts/', '**/fixtures/', '**/migrations/', '**/static/', '**/templates/'):
            self.assertNotIn(path, patterns)
        # Existing secret and user-data exclusions must survive context tuning.
        for path in ('**/.env', '**/.env.*', '**/auth.json', '**/*.sqlite3', '**/*.key', '**/node_modules', '**/venv'):
            self.assertIn(path, patterns)


class BuildGuardNegativeTests(unittest.TestCase):
    def test_regressions_are_rejected_by_the_actual_build_contract(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        ignore = (ROOT / '.dockerignore').read_text()
        mutations = [
            ('floating base', re.sub(r'(FROM node:[^@\s]+)@sha256:[a-f0-9]{64}', r'\1', dockerfile), ignore,
             'test_external_images_are_digest_pinned_and_revision_is_late'),
            ('early backend source', dockerfile.replace('COPY backend/requirements.txt', 'COPY backend/ /app/backend/\nCOPY backend/requirements.txt', 1), ignore,
             'test_external_images_are_digest_pinned_and_revision_is_late'),
            ('early frontend source', dockerfile.replace('COPY frontend/package.json', 'COPY frontend/ ./\nCOPY frontend/package.json', 1), ignore,
             'test_external_images_are_digest_pinned_and_revision_is_late'),
            ('early revision', dockerfile.replace(' AS runtime-base\n', ' AS runtime-base\nARG RELEASE_SHA\n'), ignore,
             'test_external_images_are_digest_pinned_and_revision_is_late'),
            ('broad context', dockerfile + '\nCOPY . /app\n', ignore,
             'test_external_images_are_digest_pinned_and_revision_is_late'),
            ('broad JSON context', dockerfile + '\nCOPY [".", "/app"]\n', ignore,
             'test_external_images_are_digest_pinned_and_revision_is_late'),
            ('lost test exclusion', dockerfile, ignore.replace('backend/api/tests/\n', ''),
             'test_only_explicit_nonruntime_trees_are_excluded'),
            ('reintroduced test', dockerfile, ignore + '\n!backend/api/tests/example.py\n',
             'test_only_explicit_nonruntime_trees_are_excluded'),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Positive control: the guard must accept the approved input first.
            (root / 'Dockerfile').write_text(dockerfile)
            (root / '.dockerignore').write_text(ignore)
            with patch.dict(globals(), ROOT=root):
                BuildInputContractTests().test_external_images_are_digest_pinned_and_revision_is_late()
                BuildInputContractTests().test_only_explicit_nonruntime_trees_are_excluded()
            for name, changed_dockerfile, changed_ignore, method in mutations:
                with self.subTest(name=name):
                    (root / 'Dockerfile').write_text(changed_dockerfile)
                    (root / '.dockerignore').write_text(changed_ignore)
                    with patch.dict(globals(), ROOT=root), self.assertRaises(AssertionError):
                        getattr(BuildInputContractTests(), method)()


if __name__ == '__main__':
    unittest.main()
