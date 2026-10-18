"""Offline regression checks for CI path routing (stdlib only, no GitHub API)."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ops/ci"))
from change_scope import classify_path, route_paths, changed_paths, main  # noqa: E402


class ChangeScopeTests(unittest.TestCase):
    def test_classification_matrix(self):
        cases = {
            "frontend/src/pages/NewsList.tsx": "frontend",
            "frontend/tests/pages/NewsList.test.jsx": "frontend",
            "frontend/package-lock.json": "frontend",
            "frontend/README.md": "docs",
            "backend/api/models.py": "backend",
            "backend/api/tests/test_ai_connections.py": "backend",
            "crawler/runner.py": "backend",
            "tests/backend/test_api_views.py": "backend",
            "scripts/deploy/smoke.sh": "backend",
            "ops/shared-litellm-proxy/proxy.yaml": "backend",
            "tools/byok_t00_probe/probe.py": "backend",
            "backend/api/ai_connection_urls.py": "both",
            "backend/api/serializers.py": "both",
            "backend/newsaggregator/urls.py": "both",
            ".github/workflows/ci.yml": "both",
            "ops/ci/change_scope.py": "both",
            "compose.prod.yaml": "both",
            "Dockerfile": "both",
            "scripts/run_tests.sh": "both",
            "unknown/new-service.py": "both",
            "docs/features/byok/readme.md": "docs",
            "README.md": "docs",
            "TESTING.md": "docs",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(classify_path(path), expected)

    def test_route_matrix(self):
        cases = [
            (["frontend/src/App.tsx"], (True, False)),
            (["backend/api/models.py"], (False, True)),
            (["docs/plan.md", "README.md"], (False, False)),
            (["frontend/src/App.tsx", "backend/api/models.py"], (True, True)),
            (["frontend/src/App.tsx", "docs/help.md"], (True, False)),
            ([".github/workflows/ci.yml"], (True, True)),
            (["new-unknown.yaml"], (True, True)),
            ([], (True, True)),
            (["backend/api/test.py", "frontend/src/App.tsx"], (True, True)),
        ]
        for paths, result in cases:
            with self.subTest(paths=paths):
                self.assertEqual(route_paths(paths), result)

    def test_missing_event_metadata_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            env = {"GITHUB_EVENT_NAME": "push", "GITHUB_OUTPUT": str(output)}
            with patch.dict(os.environ, env, clear=True):
                main()
            self.assertEqual(output.read_text(), "frontend=true\nbackend=true\n")

    def test_push_range_and_pull_request_merge_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()

            git("init", "-q")
            git("config", "user.name", "CI Test")
            git("config", "user.email", "ci@example.invalid")
            (root / "docs").mkdir()
            (root / "docs/first.md").write_text("first")
            git("add", ".")
            git("commit", "-qm", "initial")
            baseline = git("rev-parse", "HEAD")
            git("checkout", "-qb", "feature")
            (root / "frontend/src").mkdir(parents=True)
            (root / "frontend/src/App.tsx").write_text("export {}")
            git("add", ".")
            git("commit", "-qm", "frontend")
            head = git("rev-parse", "HEAD")
            git("checkout", "-q", "-")
            (root / "backend/api").mkdir(parents=True)
            (root / "backend/api/models.py").write_text("x = 1")
            git("add", ".")
            git("commit", "-qm", "backend")
            base = git("rev-parse", "HEAD")
            # PR is purely frontend despite unrelated backend changes on base.
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                paths = changed_paths("pull_request", "", base, head)
                self.assertEqual(paths, ["frontend/src/App.tsx"])
                self.assertEqual(route_paths(paths), (True, False))
                # A main push containing docs+backend changes routes backend.
                pushed = changed_paths("push", baseline, "", base)
                self.assertEqual(route_paths(pushed), (False, True))
                self.assertEqual(sorted(pushed), ["backend/api/models.py"])
                # Unknown/initial push history fails open via main.
                with self.assertRaises(ValueError):
                    changed_paths("push", "0" * 40, "", head)
            finally:
                os.chdir(old_cwd)

    def test_rename_between_scopes_runs_both(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()

            git("init", "-q")
            git("config", "user.name", "CI Test")
            git("config", "user.email", "ci@example.invalid")
            (root / "frontend").mkdir()
            (root / "frontend/file.txt").write_text("content")
            git("add", ".")
            git("commit", "-qm", "initial")
            before = git("rev-parse", "HEAD")
            (root / "backend").mkdir()
            (root / "frontend/file.txt").rename(root / "backend/file.txt")
            git("add", "-A")
            git("commit", "-qm", "move")
            after = git("rev-parse", "HEAD")
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                self.assertEqual(route_paths(changed_paths("push", before, "", after)), (True, True))
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
