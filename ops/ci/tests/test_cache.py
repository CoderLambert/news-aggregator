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

    def run_script(self, path):
        return subprocess.run(
            ["bash", str(path)], cwd=self.root, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True, timeout=20,
        ).stdout

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
        first = self.run_script(script)
        second = self.run_script(script)
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
        first = self.run_script(script)
        self.assertIn("MISS", first)
        self.assertEqual(self.install_count(), 3)
        second = self.run_script(script)
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
        second = self.run_script(script)
        self.assertIn("RESUME", second)
        entries = self.log.read_text().splitlines()
        self.assertEqual(entries.count("venv-create"), 1)
        self.assertEqual(entries.count("torch-network"), 1)


if __name__ == "__main__":
    unittest.main()
