"""Offline unit checks for the restart watchdog. No Docker/GitHub calls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

WATCH = Path(__file__).resolve().parents[1] / "watch.py"
SPEC = importlib.util.spec_from_file_location("newshub_ci_watch", WATCH)
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


class WatchdogSafetyTests(unittest.TestCase):
    def test_first_bad_observation_only_waits(self):
        state = {}
        allowed, reason = watch.eligible(state, "runner", 1000, grace=True)
        self.assertFalse(allowed)
        self.assertIn("5-minute", reason)
        allowed, reason = watch.eligible(state, "runner", 1301, grace=True)
        self.assertTrue(allowed, reason)

    def test_busy_github_runner_is_never_restarted(self):
        with mock.patch.object(watch, "command") as action:
            watch.consider_restart(
                "runner", "cid", "running", "unhealthy",
                {"omarchy-newshub": {"status": "online", "busy": True}},
                {}, 5000, False,
            )
            action.assert_not_called()

    def test_github_api_unavailable_does_not_restart_running_runner(self):
        with mock.patch.object(watch, "command") as action:
            watch.consider_restart("runner-frontend", "cid", "running", "unhealthy", None, {}, 5000, False)
            action.assert_not_called()

    def test_busy_backend_blocks_dind_restart(self):
        with mock.patch.object(watch, "command") as action:
            watch.consider_restart(
                "docker", "docker-id", "running", "unhealthy",
                {"omarchy-newshub": {"status": "online", "busy": True}},
                {}, 5000, False,
            )
            action.assert_not_called()

    def test_unknown_local_worker_blocks_dind_restart(self):
        with mock.patch.object(watch, "command") as action:
            watch.consider_restart(
                "docker", "docker-id", "running", "unhealthy",
                {"omarchy-newshub": {"status": "online", "busy": False}},
                {}, 5000, None,
            )
            action.assert_not_called()

    def test_idle_runner_restarts_only_after_grace(self):
        state = {}
        remote = {"omarchy-newshub-frontend": {"status": "offline", "busy": False}}
        with mock.patch.object(watch, "worker_activity", return_value=False):
            with mock.patch.object(watch, "command", return_value=(0, "")) as action:
                watch.consider_restart("runner-frontend", "cid", "running", "healthy", remote, state, 1000, False)
                action.assert_not_called()
                watch.consider_restart("runner-frontend", "cid", "running", "healthy", remote, state, 1301, False)
                action.assert_called_once_with(["docker", "restart", "--time", "30", "cid"], timeout=55)

    def test_recovery_cap_prevents_unbounded_restart(self):
        state = {"runner": {
            "window_start": 1000, "attempts": 3,
            "last_attempt": 1200, "first_unhealthy": 1000,
        }}
        allowed, reason = watch.eligible(state, "runner", 5000, grace=False)
        self.assertFalse(allowed)
        self.assertIn("cap", reason)
        allowed, _ = watch.eligible(state, "runner", 25000, grace=False)
        self.assertTrue(allowed)

    def test_manual_stop_flag_prevents_all_probe_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "maintenance-disabled").touch()
            with mock.patch.object(watch, "command") as cmd:
                self.assertEqual(watch.watch(data), 0)
                cmd.assert_not_called()

    def test_state_is_atomic_and_owner_readable_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "watch-state.json"
            watch.write_state(dest, {"runner": {"attempts": 2}})
            self.assertEqual(watch.read_state(dest)["runner"]["attempts"], 2)
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)

    def test_crash_loop_quarantined_only_after_grace(self):
        state = {}
        remote = {"omarchy-newshub-frontend": {"status": "offline", "busy": False}}
        with mock.patch.object(watch, "command", return_value=(0, "")) as command:
            watch.consider_restart("runner-frontend", "cid", "restarting", "none", remote, state, 1000, False)
            command.assert_not_called()
            watch.consider_restart("runner-frontend", "cid", "restarting", "none", remote, state, 1301, False)
            command.assert_called_once_with(["docker", "stop", "--time", "20", "cid"], timeout=45)
            self.assertEqual(state["runner-frontend"]["attempts"], 3)

    def test_busy_backend_not_quarantined_during_dind_crashloop(self):
        state = {}
        remote = {"omarchy-newshub": {"status": "online", "busy": True}}
        with mock.patch.object(watch, "command") as command:
            watch.consider_restart("docker", "cid", "restarting", "none", remote, state, 1000, False)
            watch.consider_restart("docker", "cid", "restarting", "none", remote, state, 1301, False)
            command.assert_not_called()

    def test_busy_local_worker_blocks_running_runner_recovery(self):
        remote = {"omarchy-newshub": {"status": "offline", "busy": False}}
        with mock.patch.object(watch, "worker_activity", return_value=True), mock.patch.object(watch, "command") as cmd:
            watch.consider_restart("runner", "cid", "running", "unhealthy", remote, {}, 5000, False)
            cmd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
