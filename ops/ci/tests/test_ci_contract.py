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


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class SelfHostedCIContract(unittest.TestCase):
    def test_workflow_uses_only_self_hosted_runner(self):
        wf = load(CI)
        self.assertEqual(
            set(wf["jobs"]),
            {"frontend", "backend-and-release-gates"},
        )
        for job in wf["jobs"].values():
            self.assertEqual(
                job["runs-on"], ["self-hosted", "linux", "x64", "newshub-ci"]
            )
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
        self.assertIn("backend/api/tests/", content)

    def test_manual_smoke_also_uses_only_dedicated_runner(self):
        wf = load(SMOKE)
        job = wf["jobs"]["runner-smoke"]
        self.assertEqual(
            job["runs-on"], ["self-hosted", "linux", "x64", "newshub-ci"]
        )
        self.assertIn("unix:///ci-docker/docker.sock", SMOKE.read_text())

    def test_private_dind_and_bind_mount_paths(self):
        cfg = load(COMPOSE)
        svc = cfg["services"]
        self.assertTrue(svc["docker"]["privileged"])
        self.assertNotIn("ports", svc["docker"])
        self.assertNotIn("ports", svc["runner"])
        self.assertNotIn("privileged", svc["runner"])
        self.assertNotIn("/var/run/docker.sock", str(svc["runner"]["volumes"]))
        self.assertNotIn("/var/run/docker.sock", str(svc["docker"]["volumes"]))
        self.assertIn("runner-work:/ci-work/_work", svc["runner"]["volumes"])
        self.assertIn("runner-work:/ci-work/_work", svc["docker"]["volumes"])
        env = svc["runner"]["environment"]
        self.assertEqual(env["DOCKER_HOST"], "unix:///ci-docker/docker.sock")
        self.assertEqual(env["TMPDIR"], "/ci-work/_work/.ci-tmp")
        self.assertEqual(env["RUNNER_NAME"], "omarchy-newshub")
        self.assertEqual(env["LABELS"], "newshub-ci")
        self.assertNotIn("RUNNER_TOKEN", env)
        self.assertNotIn("ACCESS_TOKEN", env)
        self.assertIn("runner-state:/runner/data", svc["runner"]["volumes"])

    def test_script_syntax(self):
        for script in (MANAGE, ENTRYPOINT):
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
        self.assertNotIn("docker system prune", script)
        self.assertNotIn("docker volume prune", script)
        self.assertNotIn("down --volumes", script)


if __name__ == "__main__":
    unittest.main()
