"""Offline contract checks for the private Docker self-hosted CI setup.

Run after installing the backend test requirements:
  python3 -m unittest discover -s ops/ci/tests -p 'test_*.py'
No GitHub token, Docker container or production data is used.
"""
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / ".github/workflows/ci.yml"
SMOKE = ROOT / ".github/workflows/ci-runner-smoke.yml"
COMPOSE = ROOT / "ops/ci/compose.yaml"
ENTRYPOINT = ROOT / "ops/ci/runner-entrypoint.sh"
MANAGE = ROOT / "ops/ci/manage.sh"
FRONT_DEPS = ROOT / "ops/ci/install-frontend-deps.sh"
BACK_DEPS = ROOT / "ops/ci/install-backend-deps.sh"
WATCH = ROOT / "ops/ci/watch.py"
WATCH_SERVICE = ROOT / "ops/ci/watch-service.sh"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class SelfHostedCIContract(unittest.TestCase):
    def test_workflow_uses_only_self_hosted_runner(self):
        wf = load(CI)
        self.assertEqual(
            set(wf["jobs"]),
            {"frontend", "backend-and-release-gates"},
        )
        self.assertEqual(
            wf["jobs"]["frontend"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-frontend"],
        )
        self.assertEqual(
            wf["jobs"]["backend-and-release-gates"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-ci"],
        )
        self.assertNotIn("needs", wf["jobs"]["frontend"])
        self.assertNotIn("needs", wf["jobs"]["backend-and-release-gates"])
        for job in wf["jobs"].values():
            self.assertIn("github.event.pull_request.head.repo.full_name", job["if"])
            self.assertTrue(any(
                "actions/checkout@" in step.get("uses", "")
                and step.get("with", {}).get("persist-credentials") is False
                for step in job["steps"]
            ))
        content = CI.read_text()
        self.assertNotIn("runs-on: ubuntu-latest", content)
        self.assertIn("branches: [main]", content)
        self.assertIn("cancel-in-progress: true", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("scripts/deploy/local-domain-smoke.sh", content)
        self.assertIn("docker image inspect alpine:3.22", content)
        self.assertIn("docker run --rm --pull=never", content)
        self.assertIn("CI_DIND_DNS_PRIMARY/SECONDARY", content)
        self.assertIn("backend/api/tests/", content)

    def test_manual_smoke_also_uses_only_dedicated_runner(self):
        wf = load(SMOKE)
        self.assertEqual(
            set(wf["jobs"]),
            {"runner-smoke-frontend", "runner-smoke-backend"},
        )
        self.assertEqual(
            wf["jobs"]["runner-smoke-frontend"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-frontend"],
        )
        self.assertEqual(
            wf["jobs"]["runner-smoke-backend"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-ci"],
        )
        for job in wf["jobs"].values():
            self.assertNotIn("needs", job)
        self.assertIn("unix:///ci-docker/docker.sock", SMOKE.read_text())
        self.assertIn('test -z "${DOCKER_HOST:-}"', SMOKE.read_text())

    def test_private_dind_and_bind_mount_paths(self):
        cfg = load(COMPOSE)
        svc = cfg["services"]
        self.assertTrue(svc["docker"]["privileged"])
        self.assertNotIn("ports", svc["docker"])
        # The outer Docker DNS 127.0.0.11 failed Docker Hub resolution on
        # the first real backend CI. Configure only isolated DinD DNS, both
        # for DinD itself and for child containers created by its dockerd.
        self.assertEqual(
            svc["docker"]["dns"],
            ["${CI_DIND_DNS_PRIMARY:-1.1.1.1}", "${CI_DIND_DNS_SECONDARY:-8.8.8.8}"],
        )
        dind_command = svc["docker"]["command"][0]
        # The Compose interpolation layer must preserve the shell variable.
        # A single $group would be eagerly expanded by Compose to empty.
        self.assertIn('--group="$$group"', dind_command)
        self.assertIn("--dns=${CI_DIND_DNS_PRIMARY:-1.1.1.1}", dind_command)
        self.assertIn("--dns=${CI_DIND_DNS_SECONDARY:-8.8.8.8}", dind_command)
        self.assertNotIn("dns", svc["runner"])
        self.assertNotIn("dns", svc["runner-frontend"])
        # Overriding image ENTRYPOINT in Compose suppresses its default CMD.
        # Without these explicit arguments upstream gosu prints its usage and
        # runner restarts forever even when registration files exist.
        for runner_name in ("runner", "runner-frontend"):
            self.assertEqual(
                svc[runner_name]["command"],
                ["./bin/Runner.Listener", "run", "--startuptype", "service"],
            )
        self.assertNotIn("ports", svc["runner"])
        self.assertNotIn("ports", svc["runner-frontend"])
        self.assertNotIn("privileged", svc["runner"])
        self.assertNotIn("privileged", svc["runner-frontend"])
        self.assertNotIn("/var/run/docker.sock", str(svc["runner"]["volumes"]))
        self.assertNotIn("/var/run/docker.sock", str(svc["docker"]["volumes"]))
        self.assertIn("runner-work:/ci-work/_work", svc["runner"]["volumes"])
        self.assertIn("runner-work:/ci-work/_work", svc["docker"]["volumes"])
        self.assertIn("frontend-work:/ci-frontend/_work", svc["runner-frontend"]["volumes"])
        self.assertIn("frontend-state:/runner/data", svc["runner-frontend"]["volumes"])
        self.assertNotIn("frontend-work:/ci-frontend/_work", svc["docker"]["volumes"])
        self.assertNotIn("runner-socket:/ci-docker", svc["runner-frontend"]["volumes"])
        self.assertNotIn("DOCKER_HOST", svc["runner-frontend"]["environment"])
        self.assertEqual(
            svc["runner-frontend"]["environment"]["RUNNER_NAME"],
            "omarchy-newshub-frontend",
        )
        self.assertEqual(
            svc["runner-frontend"]["environment"]["LABELS"], "newshub-frontend"
        )
        self.assertEqual(
            svc["runner-frontend"]["environment"]["RUNNER_WORKDIR"],
            "/ci-frontend/_work",
        )
        self.assertEqual(
            svc["runner-frontend"]["environment"]["TMPDIR"],
            "/ci-frontend/_work/.ci-tmp",
        )
        self.assertNotIn("RUNNER_TOKEN", svc["runner-frontend"]["environment"])
        env = svc["runner"]["environment"]
        self.assertEqual(env["DOCKER_HOST"], "unix:///ci-docker/docker.sock")
        self.assertEqual(env["TMPDIR"], "/ci-work/_work/.ci-tmp")
        self.assertEqual(env["RUNNER_NAME"], "omarchy-newshub")
        self.assertEqual(env["LABELS"], "newshub-ci")
        self.assertNotIn("RUNNER_TOKEN", env)
        self.assertNotIn("ACCESS_TOKEN", env)
        self.assertIn("runner-state:/runner/data", svc["runner"]["volumes"])

    def test_script_syntax(self):
        for script in (MANAGE, ENTRYPOINT, FRONT_DEPS, BACK_DEPS, WATCH_SERVICE):
            with self.subTest(file=script.name):
                result = subprocess.run(
                    ["bash", "-n", str(script)],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_host_scope_is_explicit(self):
        script = MANAGE.read_text()
        self.assertIn('PROJECT="newshub-ci"', script)
        self.assertIn("registration-token", script)
        self.assertIn("registration-token", ENTRYPOINT.read_text())
        self.assertIn("registration-token-frontend", script)
        self.assertIn("registration-token-frontend", COMPOSE.read_text())
        self.assertIn("runner-frontend", script)
        self.assertIn("require_idle", script)
        self.assertIn("confirm_both_online", script)
        self.assertIn('MANUAL_STOP_FLAG="$DATA_DIR/maintenance-disabled"', script)
        self.assertIn("watch-service.sh", script)
        self.assertNotIn("docker system prune", script)
        self.assertNotIn("docker volume prune", script)
        self.assertNotIn("down --volumes", script)

    def test_dependency_cache_is_persistent_and_keyed(self):
        ci = CI.read_text(encoding="utf-8")
        front = FRONT_DEPS.read_text(encoding="utf-8")
        back = BACK_DEPS.read_text(encoding="utf-8")
        cfg = load(COMPOSE)
        self.assertIn("bash ops/ci/install-frontend-deps.sh", ci)
        self.assertIn("bash ops/ci/install-backend-deps.sh", ci)
        self.assertNotIn("python3 -m venv --clear backend/venv", ci)
        self.assertNotIn("run: npm ci", ci)
        self.assertIn("package-lock.json", front)
        self.assertIn("sha256sum", front)
        self.assertIn("npm ci --prefix", front)
        self.assertIn("npm ls --prefix", front)
        self.assertIn("PLAYWRIGHT_PIN=\"1.62.0\"", back)
        self.assertIn("TORCH_PIN=\"2.14.1+cpu\"", back)
        self.assertIn("sha256sum", back)
        self.assertIn("pip check", back)
        self.assertIn("pip freeze", back)
        self.assertIn("npm_config_cache", cfg["services"]["runner-frontend"]["environment"])
        self.assertIn("PIP_CACHE_DIR", cfg["services"]["runner"]["environment"])
        self.assertIn("docker-data:/var/lib/docker", cfg["services"]["docker"]["volumes"])

    def test_boot_watchdog_is_safe_and_opt_in_for_linger(self):
        ci = CI.read_text(encoding="utf-8")
        watch = WATCH.read_text(encoding="utf-8")
        timer = WATCH_SERVICE.read_text(encoding="utf-8")
        script = MANAGE.read_text(encoding="utf-8")
        self.assertIn("OnStartupSec=2min", timer)
        self.assertIn("OnUnitActiveSec=5min", timer)
        self.assertIn("loginctl enable-linger", timer)
        self.assertIn('install -m 0600 "$CI_DIR/watch.py" "$DATA_DIR/bin/watch.py"', timer)
        self.assertIn('"$DATA_DIR"', timer)
        self.assertIn('label=com.docker.compose.project=', watch)
        self.assertIn('label=com.docker.compose.service=', watch)
        self.assertIn("maintenance-disabled", watch)
        self.assertIn("Runner.Worker", watch)
        self.assertIn("PERSISTENT_FAILURES = 3", watch)
        self.assertIn("COOLDOWN_SECONDS = 15 * 60", watch)
        self.assertIn('require_idle', script)
        self.assertNotIn("ubuntu-latest", ci)


if __name__ == "__main__":
    unittest.main()
