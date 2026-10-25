"""Synthetic cache-hit tests; no network/npm/PyTorch/production directories."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


def executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class DependencyCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="newshub-ci-cache-test-")
        self.root = Path(self.temp.name)
        self.ops = self.root / "ops/ci"
        self.ops.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "installs.log"
        self.env = dict(os.environ)
        self.env.update({
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "CI_TEST_LOG": str(self.log),
            "CI_TEST_REAL_PYTHON": shutil.which("python3"),
            "HOME": str(self.root),
        })

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, path, *args, cwd=None, env=None, check=True):
        return subprocess.run(
            ["bash", str(path), *args], cwd=cwd or self.root, env=env or self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=check, timeout=20,
        )

    def install_count(self):
        return len(self.log.read_text().splitlines()) if self.log.exists() else 0

    def test_frontend_cached_modules_are_reused_without_npm_ci(self):
        script = self.ops / "install-frontend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-frontend-deps.sh", script)
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"name":"test","version":"1.0.0"}')
        lock = frontend / "package-lock.json"
        lock.write_text('{"lockfileVersion":3,"name":"test"}')
        executable(self.bin / "node", '#!/bin/sh\necho v22.0.0\n')
        executable(self.bin / "npm", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == --version ]]; then echo 11.0; exit 0; fi
if [[ "$1" == ls ]]; then exit 0; fi
if [[ "$1" == ci ]]; then
    [[ "$2" == --prefix ]]
    mkdir -p "$3/node_modules/.bin"
    for tool in vite vitest; do
        printf '#!/bin/sh\nexit 0\n' > "$3/node_modules/.bin/$tool"
        chmod +x "$3/node_modules/.bin/$tool"
    done
    echo npm-ci >> "$CI_TEST_LOG"
    exit 0
fi
exit 71
""")
        first = self.run_script(script).stdout
        second = self.run_script(script).stdout
        self.assertIn("MISS", first)
        self.assertIn("HIT", second)
        self.assertEqual(self.install_count(), 1)
        self.assertTrue((frontend / "node_modules").is_symlink())
        lock.write_text('{"lockfileVersion":3,"name":"test","version":2}')
        self.run_script(script)
        self.assertEqual(self.install_count(), 2)

    def test_backend_venv_kept_when_requirements_unchanged(self):
        script = self.ops / "install-backend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-backend-deps.sh", script)
        backend = self.root / "backend"
        backend.mkdir()
        req = backend / "requirements.txt"
        req.write_text("pytest>=8\n")
        lock = backend / "requirements-ci.lock"
        lock.write_text("pytest==8.0\ntorch==2.14.1+cpu\nplaywright==1.62.0\n")
        shutil.copyfile(REPO_ROOT / "ops/ci/check-backend-lock.py", self.ops / "check-backend-lock.py")
        executable(self.bin / "python3", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == -c ]]; then echo 'cpython-312 x86_64'; exit 0; fi
if [[ "$1" == */check-backend-lock.py ]]; then
    exec "$CI_TEST_REAL_PYTHON" "$@"
fi
if [[ "$1" == -m && "$2" == venv ]]; then
    mkdir -p "$3/bin"
    cat > "$3/bin/python" <<'PY'
#!/usr/bin/env bash
set -eu
if [[ "$1" == -m && "$2" == pip ]]; then
    case "$3" in
        install) echo pip-install >> "$CI_TEST_LOG"; exit 0 ;;
        check) exit 0 ;;
        freeze) echo 'test==1.0'; exit 0 ;;
    esac
fi
if [[ "$1" == -c || "$1" == */check-backend-lock.py ]]; then exit 0; fi
exit 72
PY
    chmod +x "$3/bin/python"
    exit 0
fi
exit 73
""")
        first = self.run_script(script).stdout
        self.assertIn("MISS", first)
        self.assertEqual(self.install_count(), 3)
        second = self.run_script(script).stdout
        self.assertIn("HIT", second)
        self.assertEqual(self.install_count(), 3)
        self.assertTrue((backend / "venv").is_symlink())
        req.write_text("pytest>=9\n")
        self.run_script(script)
        self.assertEqual(self.install_count(), 6)
        # A changed exact-resolution lock must invalidate the cached venv too.
        lock.write_text("pytest==9.0\ntorch==2.14.1+cpu\nplaywright==1.62.0\n")
        self.run_script(script)
        self.assertEqual(self.install_count(), 9)

    def test_backend_failed_install_resumes_without_recreating_venv(self):
        script = self.ops / "install-backend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-backend-deps.sh", script)
        backend = self.root / "backend"
        backend.mkdir()
        (backend / "requirements.txt").write_text("pytest>=8\n")
        (backend / "requirements-ci.lock").write_text(
            "pytest==8.0\ntorch==2.14.1+cpu\nplaywright==1.62.0\n"
        )
        shutil.copyfile(
            REPO_ROOT / "ops/ci/check-backend-lock.py",
            self.ops / "check-backend-lock.py",
        )
        executable(self.bin / "python3", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == -c ]]; then echo 'cpython-312 x86_64'; exit 0; fi
if [[ "$1" == */check-backend-lock.py ]]; then
    exec "$CI_TEST_REAL_PYTHON" "$@"
fi
if [[ "$1" == -m && "$2" == venv ]]; then
    echo venv-create >> "$CI_TEST_LOG"
    mkdir -p "$3/bin"
    cat > "$3/bin/python" <<'PY'
#!/usr/bin/env bash
set -eu
env_dir="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
if [[ "$1" == -m && "$2" == pip ]]; then
    case "$3" in
        install)
            if [[ "$*" == *"torch=="* ]]; then
                if [[ ! -f "$env_dir/.torch-installed" ]]; then
                    echo torch-network >> "$CI_TEST_LOG"
                    : > "$env_dir/.torch-installed"
                fi
                exit 0
            fi
            if [[ "$*" == *" -r "* && ! -f "$CI_TEST_LOG.fail-once" ]]; then
                : > "$CI_TEST_LOG.fail-once"
                exit 80
            fi
            exit 0
            ;;
        check) exit 0 ;;
        freeze) echo 'test==1.0'; exit 0 ;;
    esac
fi
if [[ "$1" == */check-backend-lock.py ]]; then exit 0; fi
exit 72
PY
    chmod +x "$3/bin/python"
    exit 0
fi
exit 73
""")
        first = subprocess.run(
            ["bash", str(script)], cwd=self.root, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False, timeout=20,
        )
        self.assertNotEqual(first.returncode, 0)
        second = self.run_script(script).stdout
        self.assertIn("RESUME", second)
        entries = self.log.read_text().splitlines()
        self.assertEqual(entries.count("venv-create"), 1)
        self.assertEqual(entries.count("torch-network"), 1)

    def test_frontend_status_is_read_only_and_cache_only_skips_checkout_link(self):
        script = self.ops / "install-frontend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-frontend-deps.sh", script)
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"name":"test","version":"1.0.0"}')
        (frontend / "package-lock.json").write_text('{"lockfileVersion":3,"name":"test"}')
        executable(self.bin / "node", '#!/bin/sh\necho v22.0.0\n')
        executable(self.bin / "npm", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == --version ]]; then echo 11.0; exit 0; fi
if [[ "$1" == ls ]]; then exit 0; fi
if [[ "$1" == ci ]]; then
    mkdir -p "$3/node_modules/.bin"
    for tool in vite vitest; do
        printf '#!/bin/sh\nexit 0\n' > "$3/node_modules/.bin/$tool"
        chmod +x "$3/node_modules/.bin/$tool"
    done
    echo npm-ci >> "$CI_TEST_LOG"
    exit 0
fi
exit 71
""")

        status = self.run_script(script, "--status").stdout
        self.assertIn("CACHE_KIND=frontend", status)
        self.assertIn("STATUS=MISSING", status)
        cache_root = Path(self.env["XDG_CACHE_HOME"]) / "newshub-node-modules"
        self.assertFalse(cache_root.exists())
        self.assertFalse((frontend / "node_modules").exists())

        warmed = self.run_script(script, "--cache-only").stdout
        self.assertIn("STATUS=MISSING", warmed)
        self.assertFalse((frontend / "node_modules").exists())
        self.assertEqual(self.install_count(), 1)
        self.assertTrue((cache_root / ".current-key").is_file())
        self.assertIn("STATUS=HIT", self.run_script(script, "--status").stdout)

    def test_frontend_shared_cache_hits_from_a_second_checkout(self):
        shared_cache = self.root / "shared-frontend-cache"
        executable(self.bin / "node", '#!/bin/sh\necho v22.0.0\n')
        executable(self.bin / "npm", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == --version ]]; then echo 11.0; exit 0; fi
if [[ "$1" == ls ]]; then exit 0; fi
if [[ "$1" == ci ]]; then
    mkdir -p "$3/node_modules/.bin"
    for tool in vite vitest; do
        printf '#!/bin/sh\nexit 0\n' > "$3/node_modules/.bin/$tool"
        chmod +x "$3/node_modules/.bin/$tool"
    done
    echo npm-ci >> "$CI_TEST_LOG"
    exit 0
fi
exit 71
""")
        outputs = []
        for name in ("checkout-a", "checkout-b"):
            checkout = self.root / name
            (checkout / "ops/ci").mkdir(parents=True)
            shutil.copyfile(
                REPO_ROOT / "ops/ci/install-frontend-deps.sh",
                checkout / "ops/ci/install-frontend-deps.sh",
            )
            (checkout / "frontend").mkdir()
            (checkout / "frontend/package.json").write_text(
                '{"name":"test","version":"1.0.0"}'
            )
            (checkout / "frontend/package-lock.json").write_text(
                '{"lockfileVersion":3,"name":"test"}'
            )
            checkout_env = dict(self.env, CI_FRONTEND_CACHE_ROOT=str(shared_cache))
            outputs.append(
                self.run_script(
                    checkout / "ops/ci/install-frontend-deps.sh",
                    cwd=checkout,
                    env=checkout_env,
                ).stdout
            )

        self.assertIn("MISS", outputs[0])
        self.assertIn("HIT", outputs[1])
        self.assertEqual(self.install_count(), 1)

    def test_explicit_download_cache_paths_win(self):
        backend_script = self.ops / "install-backend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-backend-deps.sh", backend_script)
        backend = self.root / "backend"
        backend.mkdir()
        (backend / "requirements.txt").write_text("pytest>=8\n")
        (backend / "requirements-ci.lock").write_text(
            "pytest==8.0\ntorch==2.14.1+cpu\nplaywright==1.62.0\n"
        )
        shutil.copyfile(
            REPO_ROOT / "ops/ci/check-backend-lock.py",
            self.ops / "check-backend-lock.py",
        )
        executable(self.bin / "python3", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == -c ]]; then echo 'cpython-312 x86_64'; exit 0; fi
if [[ "$1" == */check-backend-lock.py ]]; then exec "$CI_TEST_REAL_PYTHON" "$@"; fi
if [[ "$1" == -m && "$2" == venv ]]; then
    mkdir -p "$3/bin"
    cat > "$3/bin/python" <<'PY'
#!/usr/bin/env bash
set -eu
if [[ "$1" == -m && "$2" == pip ]]; then
    [[ "${PIP_CACHE_DIR:-}" == "$CI_TEST_EXPECTED_PIP_CACHE" ]] || exit 81
    case "$3" in install) exit 0 ;; check) exit 0 ;; freeze) echo test==1.0; exit 0 ;; esac
fi
if [[ "$1" == */check-backend-lock.py ]]; then exit 0; fi
exit 72
PY
    chmod +x "$3/bin/python"
    exit 0
fi
exit 73
""")
        explicit_pip = self.root / "downloads/pip"
        backend_env = dict(
            self.env,
            PIP_CACHE_DIR=str(explicit_pip),
            CI_TEST_EXPECTED_PIP_CACHE=str(explicit_pip),
        )
        self.run_script(backend_script, "--cache-only", env=backend_env)
        self.assertTrue(explicit_pip.is_dir())

        frontend_script = self.ops / "install-frontend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-frontend-deps.sh", frontend_script)
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"name":"test","version":"1.0.0"}')
        (frontend / "package-lock.json").write_text('{"lockfileVersion":3,"name":"test"}')
        executable(self.bin / "node", '#!/bin/sh\necho v22.0.0\n')
        executable(self.bin / "npm", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == --version ]]; then echo 11.0; exit 0; fi
[[ "${npm_config_cache:-}" == "$CI_TEST_EXPECTED_NPM_CACHE" ]] || exit 82
if [[ "$1" == ls ]]; then exit 0; fi
if [[ "$1" == ci ]]; then
    mkdir -p "$3/node_modules/.bin"
    for tool in vite vitest; do
        printf '#!/bin/sh\nexit 0\n' > "$3/node_modules/.bin/$tool"
        chmod +x "$3/node_modules/.bin/$tool"
    done
    exit 0
fi
exit 71
""")
        explicit_npm = self.root / "downloads/npm"
        frontend_env = dict(
            self.env,
            npm_config_cache=str(explicit_npm),
            CI_TEST_EXPECTED_NPM_CACHE=str(explicit_npm),
        )
        self.run_script(frontend_script, "--cache-only", env=frontend_env)
        self.assertTrue(explicit_npm.is_dir())

    def test_frontend_retry_reuses_the_same_download_cache(self):
        script = self.ops / "install-frontend-deps.sh"
        shutil.copyfile(REPO_ROOT / "ops/ci/install-frontend-deps.sh", script)
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"name":"test","version":"1.0.0"}')
        (frontend / "package-lock.json").write_text('{"lockfileVersion":3,"name":"test"}')
        executable(self.bin / "node", '#!/bin/sh\necho v22.0.0\n')
        executable(self.bin / "npm", r"""#!/usr/bin/env bash
set -eu
if [[ "$1" == --version ]]; then echo 11.0; exit 0; fi
if [[ "$1" == ls ]]; then exit 0; fi
if [[ "$1" == ci ]]; then
    test -n "${npm_config_cache:-}"
    mkdir -p "$npm_config_cache"
    if [[ ! -f "$npm_config_cache/downloaded" ]]; then
        echo network-download >> "$CI_TEST_LOG"
        : > "$npm_config_cache/downloaded"
    fi
    if [[ ! -f "$CI_TEST_LOG.fail-once" ]]; then
        : > "$CI_TEST_LOG.fail-once"
        exit 80
    fi
    mkdir -p "$3/node_modules/.bin"
    for tool in vite vitest; do
        printf '#!/bin/sh\nexit 0\n' > "$3/node_modules/.bin/$tool"
        chmod +x "$3/node_modules/.bin/$tool"
    done
    exit 0
fi
exit 71
""")

        first = self.run_script(script, "--cache-only", check=False)
        self.assertNotEqual(first.returncode, 0)
        second = self.run_script(script, "--cache-only")
        self.assertIn("READY", second.stdout)
        self.assertEqual(self.log.read_text().splitlines().count("network-download"), 1)


if __name__ == "__main__":
    unittest.main()
