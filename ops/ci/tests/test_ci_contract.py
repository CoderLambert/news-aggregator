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
CHECK_LOCK = ROOT / "ops/ci/check-backend-lock.py"
CACHE_SUMMARY = ROOT / "ops/ci/cache-summary.sh"
CI_LOCK = ROOT / "backend/requirements-ci.lock"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class SelfHostedCIContract(unittest.TestCase):
    def test_workflow_uses_only_self_hosted_runner(self):
        wf = load(CI)
        self.assertEqual(
            set(wf["jobs"]),
            {"changes", "dev-frontend", "dev-backend", "frontend", "backend-and-release-gates", "merge-gate"},
        )
        self.assertEqual(
            wf["jobs"]["frontend"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-frontend"],
        )
        self.assertEqual(
            wf["jobs"]["backend-and-release-gates"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-ci"],
        )
        self.assertEqual(
            wf["jobs"]["changes"]["runs-on"],
            ["self-hosted", "linux", "x64", "newshub-frontend"],
        )
        self.assertIn(
            "github.event.pull_request.head.repo.full_name",
            wf["jobs"]["changes"]["if"],
        )
        self.assertNotIn("!github.event.pull_request.draft", wf["jobs"]["changes"]["if"])
        self.assertIn("github.event.pull_request.draft", wf["jobs"]["dev-frontend"]["if"])
        self.assertIn("github.event.pull_request.draft", wf["jobs"]["dev-backend"]["if"])
        for stage in ("frontend", "backend-and-release-gates"):
            self.assertIn("!github.event.pull_request.draft", wf["jobs"][stage]["if"])
        for event in ("ready_for_review", "converted_to_draft", "synchronize"):
            self.assertIn(event, yaml.load(CI.read_text(), Loader=yaml.BaseLoader)["on"]["pull_request"]["types"])
        self.assertEqual(wf["jobs"]["changes"]["steps"][0]["with"]["fetch-depth"], 0)
        route = wf["jobs"]["changes"]["steps"][-1]
        self.assertIn("change_scope.py", route["run"])
        self.assertIn("CI_BEFORE_SHA", route["env"])
        self.assertIn("CI_BASE_SHA", route["env"])
        self.assertIn("CI_HEAD_SHA", route["env"])
        for name in ("CI_PR_BEFORE_SHA", "CI_PR_ACTION", "CI_DEV_MODE"):
            self.assertIn(name, route["env"])
        # Trigger-level ignore: docs/metadata-only PRs do not start a Runner.
        # Mixed changes still run: GitHub skips only when ALL paths are ignored.
        # BaseLoader preserves the YAML key 'on' rather than coercing it to True.
        events = yaml.load(CI.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["on"]
        push_ignore = events["push"]["paths-ignore"]
        pr_ignore = events["pull_request"]["paths-ignore"]
        self.assertEqual(push_ignore, pr_ignore)
        self.assertEqual(set(push_ignore), {
            "docs/**",
            "README.md",
            "TESTING.md",
            "DEVLOG.md",
            "CHANGELOG.md",
            "frontend/README.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "SECURITY.md",
            "LICENSE",
            "LICENSE.md",
            "NOTICE",
            "NOTICE.md",
            ".github/ISSUE_TEMPLATE/**",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/PULL_REQUEST_TEMPLATE/**",
            ".github/FUNDING.yml",
        })
        for event in ("push", "pull_request"):
            self.assertNotIn("paths", events[event])
        self.assertNotIn("paths-ignore", events.get("workflow_dispatch") or {})
        self.assertNotIn("**/*.md", push_ignore)
        self.assertNotIn(".github/**", push_ignore)
        self.assertNotIn("ops/ci/**", push_ignore)
        for name, scope in (
            ("frontend", "frontend"),
            ("backend-and-release-gates", "backend"),
        ):
            job = wf["jobs"][name]
            self.assertEqual(job["needs"], "changes")
            self.assertIn("!cancelled()", job["if"])
            self.assertIn("github.event_name == 'workflow_dispatch'", job["if"])
            self.assertIn(f"needs.changes.outputs.{scope}", job["if"])
        for name, job in wf["jobs"].items():
            # The result-only merge gate has no need to download PR code.
            if name == "merge-gate":
                self.assertFalse(any("uses" in step for step in job["steps"]))
                continue
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
        self.assertIn("docker build --file ops/ci/g1-probe.Dockerfile", content)
        self.assertIn("LOCAL_DOMAIN_G1_PROBE_IMAGE: newshub:ci-g1-probe", content)
        probe_text = (ROOT / "ops/ci/g1-probe.Dockerfile").read_text(encoding="utf-8")
        smoke_text = (ROOT / "scripts/deploy/local-domain-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("playwright==1.62.0", probe_text)
        self.assertIn("local_domain_acceptance.py", probe_text)
        self.assertIn('G1_PROBE_IMAGE_ID="$(docker image inspect', smoke_text)
        self.assertIn('--network "container:$gateway_id"', smoke_text)
        self.assertIn('--pull=never', smoke_text)
        self.assertIn('--read-only --cap-drop=ALL', smoke_text)
        self.assertIn('target=/smoke/ca.crt,readonly', smoke_text)
        self.assertIn("docker image inspect alpine:3.22", content)
        self.assertIn("docker run --rm --pull=never", content)
        self.assertIn("CI_DIND_DNS_PRIMARY/SECONDARY", content)
        self.assertIn("backend/api/tests/", content)
        # Draft jobs do not run whole frontend/backend matrices or paid SDK
        # probes, G1, release images, or any production action.
        dev_front = wf["jobs"]["dev-frontend"]
        dev_back = wf["jobs"]["dev-backend"]
        self.assertEqual(dev_front["needs"], "changes")
        self.assertEqual(dev_back["needs"], "changes")
        self.assertEqual(dev_front["runs-on"], ["self-hosted", "linux", "x64", "newshub-frontend"])
        self.assertEqual(dev_back["runs-on"], ["self-hosted", "linux", "x64", "newshub-ci"])
        dev_front_runs = "\n".join(step.get("run", "") for step in dev_front["steps"])
        dev_back_runs = "\n".join(step.get("run", "") for step in dev_back["steps"])
        for line in ("npm run typecheck", "npm run lint", "install-frontend-deps.sh"):
            self.assertIn(line, dev_front_runs)
        for forbidden in ("npm run test:run", "npm run build", "local-domain-smoke.sh", "docker build"):
            self.assertNotIn(forbidden, dev_front_runs + dev_back_runs)
        for required in ("install-backend-deps.sh", "--maxfail=1", "unittest discover"):
            self.assertIn(required, dev_back_runs)
        for forbidden in ("benchmark-xdist.sh", "tools/byok_t00_probe", "docker pull", "--target production"):
            self.assertNotIn(forbidden, dev_front_runs + dev_back_runs)
        # Fail-closed final gate explicitly checks success of each selected
        # full job; skipped/missing selected tests cannot count as PASS.
        gate = wf["jobs"]["merge-gate"]
        self.assertEqual(set(gate["needs"]), {"changes", "frontend", "backend-and-release-gates"})
        self.assertIn("always()", gate["if"])
        self.assertIn("!github.event.pull_request.draft", gate["if"])
        self.assertIn("needs.frontend.result", str(gate["steps"]))
        self.assertIn("needs.backend-and-release-gates.result", str(gate["steps"]))
        self.assertIn("true:success|false:skipped", gate["steps"][0]["run"])
        frontend_steps = wf["jobs"]["frontend"]["steps"]
        frontend_fast = next(i for i, step in enumerate(frontend_steps)
                             if step["name"] == "Fast cross-stack syntax preflight")
        frontend_deps = next(i for i, step in enumerate(frontend_steps)
                             if step["name"].startswith("Restore installed frontend deps"))
        self.assertLess(frontend_fast, frontend_deps)
        self.assertIn("python3 -m compileall", frontend_steps[frontend_fast]["run"])
        self.assertNotIn("docker", frontend_steps[frontend_fast]["run"].lower())
        backend_steps = wf["jobs"]["backend-and-release-gates"]["steps"]
        t00_step = next(step for step in backend_steps
                        if step["name"] == "Verify BYOK T00 isolated SDK and Proxy contracts")
        t00_run = t00_step["run"]
        self.assertIn("tools/byok_t00_probe/probe.py", t00_run)
        self.assertIn("unittest discover -s ops/shared-litellm-proxy/tests -p 'test_provider_key_guard.py'", t00_run)
        self.assertIn("tools/byok_t00_probe/t04_django_localproxy.py", t00_run)
        self.assertIn("env -i", t00_run)
        self.assertIn("DJANGO_ENV=production", t00_run)
        # pytest-django imports settings before function-level overrides run.
        # Keep the isolated bootstrap valid without relaxing production hosts.
        self.assertIn("DJANGO_ALLOWED_HOSTS=news.lambert.host ", t00_run)
        self.assertNotIn("DJANGO_ALLOWED_HOSTS=testserver", t00_run)
        self.assertIn('T00_PROXY_PYTHON="$t00_env/proxy/bin/python"', t00_run)
        self.assertIn('CHROMA_DATA_DIR="$t00_env/chroma"', t00_run)
        self.assertIn('TTS_CACHE_DIR="$t00_env/tts"', t00_run)
        self.assertIn('trap \'rm -rf "$t00_env"\' EXIT', t00_run)
        self.assertNotIn("|| true", t00_run)
        self.assertNotIn("continue-on-error", str(t00_step))
        t04_source = (ROOT / "tools/byok_t00_probe/t04_django_localproxy.py").read_text(
            encoding="utf-8",
        )
        self.assertNotIn("pytest.skip", t04_source)
        self.assertNotIn("skipif", t04_source)
        self.assertNotIn("tools/byok_t00_probe/t04_django_localproxy.py",
                         dev_front_runs + dev_back_runs)
        security_fast = next(i for i, step in enumerate(backend_steps)
                             if step["name"] == "Fast backend security regressions")
        full_suite = next(i for i, step in enumerate(backend_steps)
                          if step["name"] == "Run backend and offline deployment tests")
        self.assertLess(security_fast, full_suite)
        self.assertIn("--maxfail=1", backend_steps[security_fast]["run"])
        # Retiring an implementation must not leave either CI stage pointing
        # at a deleted security module (pytest exits before collecting tests).
        for job in ("dev-backend", "backend-and-release-gates"):
            security = next(step for step in wf["jobs"][job]["steps"]
                            if step["name"] == "Fast backend security regressions")
            paths = [word for word in security["run"].split()
                     if word.endswith(".py")]
            self.assertTrue(paths)
            for path in paths:
                self.assertTrue((ROOT / path).is_file(), f"{job}: missing {path}")
        # Default backend tests must invoke the same previously validated
        # hybrid as the opt-in benchmark, with only one CI round.
        self.assertEqual(backend_steps[full_suite]["run"], "bash ops/ci/benchmark-xdist.sh")
        self.assertEqual(backend_steps[full_suite]["env"]["CI_XDIST_REPEATS"], "1")
        hybrid = (ROOT / "ops/ci/benchmark-xdist.sh").read_text(encoding="utf-8")
        self.assertIn("tests/ backend/api/tests/ scripts/deploy/tests/", hybrid)
        self.assertIn('SERIAL_FILES=(', hybrid)
        self.assertIn('--ignore="$file"', hybrid)
        self.assertIn("--max-worker-restart=0", hybrid)
        self.assertIn("ops/ci/xdist_summary.py", hybrid)
        self.assertIn("CI_XDIST_REPEATS", hybrid)
        benchmark = load(ROOT / ".github/workflows/ci-pytest-benchmark.yml")
        self.assertEqual(benchmark["jobs"]["pytest-xdist-lab"]["env"]["CI_XDIST_REPEATS"], "3")

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
        # The existing private bridge's MTU=1500 caused GitHub TLS timeout.
        # Pin the operator-requested 1200 to this project and its inner bridge.
        self.assertEqual(cfg["networks"]["default"], {
            "driver": "bridge",
            "driver_opts": {"com.docker.network.driver.mtu": "1200"},
        })
        for name in ("docker", "runner", "runner-frontend"):
            self.assertNotIn("network_mode", svc[name])
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
        # BuildKit's default network and newly created Docker bridges must
        # also fit the outer bridge; fixing only the listeners is insufficient.
        self.assertIn("--mtu=1200", dind_command)
        # The Compose interpolation layer must preserve the shell variable.
        # A single $group would be eagerly expanded by Compose to empty.
        self.assertIn('--group="$$group"', dind_command)
        # Health/readiness must validate the same non-root account that runs
        # GitHub Actions jobs; root Docker access is not sufficient.
        backend_health = svc["runner"]["healthcheck"]["test"][1]
        self.assertIn("/usr/sbin/gosu runner docker info", backend_health)
        self.assertIn("/usr/sbin/gosu runner docker info", MANAGE.read_text())
        self.assertIn("stat -c 'DinD socket mode=", CI.read_text())
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
        for script in (MANAGE, ENTRYPOINT, FRONT_DEPS, BACK_DEPS, WATCH_SERVICE, CACHE_SUMMARY):
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
        self.assertIn('cat "$REQ" "$LOCK"', back)
        self.assertIn('-r "$LOCK"', back)
        self.assertTrue(CI_LOCK.is_file())
        self.assertIn('docker builder du', CACHE_SUMMARY.read_text())
        check = subprocess.run(
            ["python3", str(CHECK_LOCK), str(ROOT / "backend/requirements.txt"), str(CI_LOCK)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
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
