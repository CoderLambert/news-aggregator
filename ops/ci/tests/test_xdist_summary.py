"""Regression tests for dynamic, fail-closed hybrid pytest coverage auditing."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree as ET

MODULE_PATH = Path(__file__).resolve().parents[1] / "xdist_summary.py"
SPEC = importlib.util.spec_from_file_location("xdist_summary", MODULE_PATH)
xdist_summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xdist_summary)


class XdistSummaryTests(unittest.TestCase):
    def test_real_terminal_shapes(self):
        self.assertEqual(
            xdist_summary.parse_terminal_summary("79 passed in 22.37s\n")["passed"], 79
        )
        counts = xdist_summary.parse_terminal_summary(
            "==== 2329 passed, 16 skipped in 105.55s (0:01:45) ===\n"
        )
        self.assertEqual((counts["passed"], counts["skipped"]), (2329, 16))

    def test_new_passed_tests_do_not_require_a_hardcoded_count(self):
        old = xdist_summary.validate_terminal_coverage([
            ("serial", "1 passed in 0.1s"),
            ("parallel", "2 passed, 16 skipped in 0.1s"),
        ])
        new = xdist_summary.validate_terminal_coverage([
            ("serial", "1 passed in 0.1s"),
            ("parallel", "27 passed, 16 skipped in 0.1s"),
        ])
        self.assertEqual(new["passed"] - old["passed"], 25)

    def test_skip_count_is_still_a_gate(self):
        with self.assertRaisesRegex(ValueError, "unexpected skips"):
            xdist_summary.validate_terminal_coverage([
                ("serial", "1 passed in 0.1s"),
                ("parallel", "2 passed, 17 skipped in 0.1s"),
            ])

    def test_failure_xfail_xpass_and_duplicate_summaries_are_rejected(self):
        for summary in (
            "1 failed, 2 passed, 16 skipped in 1.0s",
            "1 xfailed, 2 passed, 16 skipped in 1.0s",
            "1 xpassed, 2 passed, 16 skipped in 1.0s",
        ):
            with self.subTest(summary=summary), self.assertRaisesRegex(ValueError, "unexpected outcomes"):
                xdist_summary.validate_terminal_coverage([
                    ("serial", "1 passed in 0.1s"), ("parallel", summary),
                ])
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            xdist_summary.parse_terminal_summary("1 passed in 0.1s\n1 passed in 0.1s")

    def _files(self, folder, *, omit=None, duplicate=False, unexpected=None):
        nodeids = ["tests/test_ci.py::test_first", "tests/test_ci.py::test_second"]
        nodeids.extend(f"tests/test_skip.py::test_skip_{i}" for i in range(16))
        collection = folder / "collection.json"
        collection.write_text(json.dumps({"kind": "collection", "nodeids": nodeids}))
        serial = folder / "serial.json"
        parallel = folder / "parallel.json"
        def row(nodeid, outcome, when="call"):
            return {"nodeid": nodeid, "outcome": outcome, "when": when, "wasxfail": False, "is_subtest": False}
        a = [row(nodeids[0], "passed")]
        b = [row(nodeids[1], "passed")]
        b.extend(row(n, "skipped", "setup") for n in nodeids[2:])
        if omit:
            b = [report for report in b if report["nodeid"] != omit]
        if duplicate:
            b.append(b[0])
        if unexpected:
            b.append(row(unexpected, "passed"))
        serial.write_text(json.dumps({"kind": "execution", "reports": a,
            "started": [row["nodeid"] for row in a],
            "finished": [row["nodeid"] for row in a]}))
        parallel.write_text(json.dumps({"kind": "execution", "reports": b,
            "started": [row["nodeid"] for row in b],
            "finished": [row["nodeid"] for row in b]}))
        return collection, serial, parallel

    def test_all_collected_nodeids_are_reconciled(self):
        with TemporaryDirectory() as name:
            paths = self._files(Path(name))
            counts = xdist_summary.validate_execution(*(str(p) for p in paths))
            self.assertEqual((counts["passed"], counts["skipped"]), (2, 16))

    def test_missing_collected_test_fails_even_if_total_was_faked(self):
        with TemporaryDirectory() as name:
            paths = self._files(Path(name), omit="tests/test_ci.py::test_second")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                xdist_summary.validate_execution(*(str(p) for p in paths))

    def test_duplicate_or_uncollected_execution_fails(self):
        with TemporaryDirectory() as name:
            paths = self._files(Path(name), duplicate=True)
            with self.assertRaisesRegex(ValueError, "duplicate/incomplete execution protocols"):
                xdist_summary.validate_execution(*(str(p) for p in paths))
        with TemporaryDirectory() as name:
            paths = self._files(Path(name), unexpected="tests/test_extra.py::test_extra")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                xdist_summary.validate_execution(*(str(p) for p in paths))

    def test_unflagged_native_subtests_share_one_unique_pytest_protocol(self):
        with TemporaryDirectory() as name:
            paths = self._files(Path(name))
            parallel = paths[2]
            value = json.loads(parallel.read_text())
            parent = value["reports"][0]
            value["reports"].extend([dict(parent) for _ in range(6)])
            parallel.write_text(json.dumps(value))
            counts = xdist_summary.validate_execution(*(str(p) for p in paths))
            self.assertEqual((counts["passed"], counts["skipped"]), (2, 16))
            value["started"].append(parent["nodeid"])
            parallel.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "duplicate/incomplete execution protocols"):
                xdist_summary.validate_execution(*(str(p) for p in paths))
            value["started"].pop()
            value["reports"][-1]["outcome"] = "failed"
            parallel.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "failed, xfailed"):
                xdist_summary.validate_execution(*(str(p) for p in paths))

    def test_junit_rejects_failure_duplicates_and_skip_mismatch(self):
        with TemporaryDirectory() as name:
            xml = Path(name) / "report.xml"
            root = ET.Element("testsuite")
            ET.SubElement(root, "testcase", classname="tests.ci", name="first")
            ET.SubElement(root, "testcase", classname="tests.ci", name="second")
            ET.ElementTree(root).write(xml)
            xdist_summary.validate_junit(str(xml), expected_cases=2, expected_skips=0)
            with self.assertRaisesRegex(ValueError, "lost or duplicated"):
                xdist_summary.validate_junit(str(xml), expected_cases=3, expected_skips=0)
            ET.SubElement(root, "testcase", classname="tests.ci", name="second")
            ET.ElementTree(root).write(xml)
            with self.assertRaisesRegex(ValueError, "duplicate case"):
                xdist_summary.validate_junit(str(xml), expected_cases=3, expected_skips=0)
            root.remove(root[-1])
            ET.SubElement(root[0], "error")
            ET.ElementTree(root).write(xml)
            with self.assertRaisesRegex(ValueError, "error or failure"):
                xdist_summary.validate_junit(str(xml), expected_cases=2, expected_skips=0)

    def test_main_reconciles_junit_parent_cases_not_unittest_subtest_reports(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            collection, serial, parallel = self._files(folder)
            payload = json.loads(parallel.read_text())
            payload["reports"].extend([dict(payload["reports"][0]) for _ in range(6)])
            parallel.write_text(json.dumps(payload))
            serial_log, parallel_log = folder / "s.log", folder / "p.log"
            serial_log.write_text("1 passed in 0.1s")
            parallel_log.write_text("1 passed, 16 skipped in 0.1s")
            serial_xml, parallel_xml = folder / "s.xml", folder / "p.xml"
            root = ET.Element("testsuite")
            ET.SubElement(root, "testcase", classname="tests.test_ci", name="test_first")
            ET.ElementTree(root).write(serial_xml)
            root = ET.Element("testsuite")
            ET.SubElement(root, "testcase", classname="tests.test_ci", name="test_second")
            for i in range(16):
                item = ET.SubElement(root, "testcase", classname="tests.test_skip",
                                     name=f"test_skip_{i}")
                ET.SubElement(item, "skipped")
            ET.ElementTree(root).write(parallel_xml)
            args = [str(p) for p in (collection, serial, parallel,
                     serial_log, parallel_log, serial_xml, parallel_xml)]
            self.assertEqual(xdist_summary.main(args), 0)
            # Missing JUnit parent test is still forbidden.
            root.remove(root[0])
            ET.ElementTree(root).write(parallel_xml)
            with self.assertRaisesRegex(SystemExit, "lost or duplicated cases"):
                xdist_summary.main(args)

    def test_main_rejects_terminal_and_audit_disagreement(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            collection, serial, parallel = self._files(folder)
            serial_log = folder / "serial.log"
            parallel_log = folder / "parallel.log"
            serial_log.write_text("1 passed in 0.1s\n")
            parallel_log.write_text("3 passed, 16 skipped in 0.1s\n")
            with self.assertRaisesRegex(SystemExit, "terminal/identity mismatch"):
                xdist_summary.main([
                    *(str(p) for p in (collection, serial, parallel, serial_log, parallel_log)),
                    "unused-serial.xml", "unused-parallel.xml"
                ])


if __name__ == "__main__":
    unittest.main()
