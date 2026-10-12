"""Keep help and invalid CLI arguments from starting Docker services."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

import run_local


class RunnerCliTests(unittest.TestCase):
    def test_help_exits_before_starting_compose_or_creating_test_state(self):
        stdout = io.StringIO()
        with patch.object(run_local, "safe_process") as safe_process:
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as raised:
                    run_local.main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage:", stdout.getvalue())
        safe_process.assert_not_called()

    def test_unknown_argument_is_rejected_before_starting_compose(self):
        stderr = io.StringIO()
        with patch.object(run_local, "safe_process") as safe_process:
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    run_local.main(["--not-a-supported-option"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments", stderr.getvalue())
        safe_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
