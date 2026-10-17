"""Regression tests for real pytest -q terminal output shapes."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "xdist_summary.py"
SPEC = importlib.util.spec_from_file_location("xdist_summary", MODULE_PATH)
xdist_summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xdist_summary)


class XdistSummaryTests(unittest.TestCase):
    def test_actual_failed_run_logs_parse_to_original_terminal_total(self):
        serial = xdist_summary.parse_terminal_summary("79 passed in 22.37s\n")
        parallel = xdist_summary.parse_terminal_summary(
            "================= 2329 passed, 16 skipped in 105.55s "
            "(0:01:45) =================\n"
        )
        self.assertEqual(serial["passed"], 79)
        self.assertEqual(parallel["passed"], 2329)
        self.assertEqual(parallel["skipped"], 16)
        self.assertEqual(serial["passed"] + parallel["passed"], 2408)

    def test_current_coverage_includes_two_new_g1_regressions(self):
        totals = xdist_summary.validate_terminal_coverage(
            [
                ("serial.log", "79 passed in 22.37s\n"),
                (
                    "parallel.log",
                    "2331 passed, 16 skipped in 105.55s (0:01:45)\n",
                ),
            ]
        )
        self.assertEqual(totals["passed"], 2410)
        self.assertEqual(totals["skipped"], 16)

    def test_reported_bare_serial_format_is_supported(self):
        totals = xdist_summary.parse_terminal_summary("79 passed in 24.11s\n")
        self.assertEqual(totals["passed"], 79)
        self.assertEqual(totals["skipped"], 0)

    def test_parenthesized_elapsed_time_without_equals_is_supported(self):
        totals = xdist_summary.parse_terminal_summary(
            "2329 passed, 16 skipped in 105.55s (0:01:45)\n"
        )
        self.assertEqual(totals["passed"], 2329)
        self.assertEqual(totals["skipped"], 16)

    def test_multiple_summaries_fail_as_ambiguous(self):
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            xdist_summary.parse_terminal_summary(
                "79 passed in 22.37s\n79 passed in 22.37s\n"
            )

    def test_failure_counts_are_never_ignored(self):
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            xdist_summary.validate_terminal_coverage(
                [
                    ("serial.log", "79 passed in 22.37s\n"),
                    (
                        "parallel.log",
                        "1 failed, 2330 passed, 16 skipped in 105.55s "
                        "(0:01:45)\n",
                    ),
                ]
            )

    def test_wrong_expected_counts_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            xdist_summary.validate_terminal_coverage(
                [
                    ("serial.log", "79 passed in 22.37s\n"),
                    (
                        "parallel.log",
                        "2331 passed, 15 skipped in 105.55s "
                        "(0:01:45)\n",
                    ),
                ]
            )


if __name__ == "__main__":
    unittest.main()
