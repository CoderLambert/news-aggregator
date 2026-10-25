"""Behavior tests for safe, targeted dependency-cache maintenance."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
MAINTENANCE = ROOT / "ops/ci/cache-maintenance.py"


class CacheMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="newshub-cache-gc-test-")
        self.root = Path(self.temp.name) / "cache"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def keyed(self, digit: str, *, ready: bool = True, mtime: int = 1) -> Path:
        key = digit * 64
        directory = self.root / key
        directory.mkdir()
        (directory / "payload").write_text("synthetic")
        if ready:
            (directory / ".newshub-ready").write_text(f"{key}\n")
        os.utime(directory, (mtime, mtime))
        return directory

    def run_gc(self, *args: str, check: bool = True):
        return subprocess.run(
            ["python3", str(MAINTENANCE), "gc", "--root", str(self.root), *args],
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )

    def test_gc_defaults_to_dry_run_and_keeps_current_and_recent_success(self):
        stale = self.keyed("a", mtime=10)
        recent = self.keyed("b", mtime=20)
        current = self.keyed("c", ready=False, mtime=5)
        (self.root / ".current-key").write_text(f"{current.name}\n")

        result = self.run_gc("--keep-successful", "1")

        self.assertIn(f"WOULD_REMOVE {stale}", result.stdout)
        self.assertIn(f"KEEP {recent}", result.stdout)
        self.assertIn(f"KEEP {current}", result.stdout)
        self.assertTrue(stale.is_dir())
        self.assertTrue(recent.is_dir())
        self.assertTrue(current.is_dir())
        self.assertFalse((self.root / ".install.lock").exists())

    def test_execute_removes_only_stale_keyed_directories(self):
        stale = self.keyed("a", mtime=10)
        recent = self.keyed("b", mtime=20)
        current = self.keyed("c", ready=False, mtime=5)
        (self.root / ".current-key").write_text(f"{current.name}\n")
        unknown = self.root / "downloads"
        unknown.mkdir()
        target = self.root / "outside"
        target.mkdir()
        symlink = self.root / ("d" * 64)
        symlink.symlink_to(target, target_is_directory=True)

        result = self.run_gc("--keep-successful", "1", "--execute")

        self.assertIn(f"REMOVED {stale}", result.stdout)
        self.assertFalse(stale.exists())
        self.assertTrue(recent.is_dir())
        self.assertTrue(current.is_dir())
        self.assertTrue(unknown.is_dir())
        self.assertTrue(target.is_dir())
        self.assertTrue(symlink.is_symlink())
        self.assertTrue((self.root / ".install.lock").is_file())

    def test_invalid_current_key_fails_closed(self):
        stale = self.keyed("a", mtime=10)
        (self.root / ".current-key").write_text("../outside\n")

        result = self.run_gc("--execute", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid current cache key", result.stderr)
        self.assertTrue(stale.is_dir())


if __name__ == "__main__":
    unittest.main()
