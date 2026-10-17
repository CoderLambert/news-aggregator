"""Fail-closed identity, terminal-summary and JUnit audit of the hybrid test matrix.

The collected nodeids are the authoritative dynamic denominator. A new test
passes automatically when it is collected and executed; missing or duplicate
cases cannot hide behind an unchanged (or coincidentally matching) total.
"""
from collections import Counter, defaultdict
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# Deliberately pinned skip budget until each historical skip is individually
# classified. This is NOT a fixed number of passed/collected tests.
_ALLOWED_SKIPS = 16
_SUMMARY = re.compile(
    r"^\s*=*\s*"
    r"(?P<outcomes>\d+\s+[A-Za-z][A-Za-z_-]*"
    r"(?:\s*,\s*\d+\s+[A-Za-z][A-Za-z_-]*)*)"
    r"\s+in\s+\d+(?:\.\d+)?s"
    r"(?:\s+\([^()\r\n]*\))?"
    r"\s*=*\s*$"
)
_ITEM = re.compile(r"(\d+)\s+([A-Za-z][A-Za-z_-]*)")
_ALLOWED = {"passed", "failed", "error", "errors", "skipped", "xfailed",
            "xpassed", "warning", "warnings"}


def parse_terminal_summary(contents: str, *, source: str = "<log>") -> Counter:
    matches = [
        match for line in contents.splitlines()
        if (match := _SUMMARY.fullmatch(line)) is not None
    ]
    if len(matches) != 1:
        raise ValueError(f"xdist terminal summary missing or ambiguous: {source}")
    counts = Counter()
    for count, outcome in _ITEM.findall(matches[0].group("outcomes")):
        key = outcome.lower()
        if key not in _ALLOWED or counts[key]:
            raise ValueError(f"unknown or duplicated summary outcome {key!r}: {source}")
        counts[key] = int(count)
    return counts


def validate_terminal_coverage(logs: list[tuple[str, str]]) -> Counter:
    if len(logs) != 2:
        raise ValueError("xdist requires serial and parallel terminal summaries")
    total = Counter()
    for source, contents in logs:
        parsed = parse_terminal_summary(contents, source=source)
        if parsed["passed"] + parsed["skipped"] == 0:
            raise ValueError(f"xdist run did not execute any tests: {source}")
        unexpected = {key: count for key, count in parsed.items()
                      if key not in {"passed", "skipped", "warning", "warnings"} and count}
        if unexpected:
            raise ValueError(f"xdist run failed or contains unexpected outcomes: {source}: {unexpected}")
        total.update(parsed)
    if total["skipped"] != _ALLOWED_SKIPS:
        raise ValueError(
            f"xdist unexpected skips: {total['skipped']}, approved baseline {_ALLOWED_SKIPS}"
        )
    return total


def _read_manifest(path: str, kind: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("kind") != kind:
        raise ValueError(f"invalid {kind} audit manifest: {path}")
    return value


def validate_execution(expected_path: str, serial_path: str, parallel_path: str) -> Counter:
    expected = _read_manifest(expected_path, "collection").get("nodeids")
    if not isinstance(expected, list) or not expected or any(
        not isinstance(item, str) or not item for item in expected
    ) or len(expected) != len(set(expected)):
        raise ValueError("collection contains no identities, invalid names or duplicates")

    recorded = defaultdict(list)
    executed = []
    for path in (serial_path, parallel_path):
        manifest = _read_manifest(path, "execution")
        reports = manifest.get("reports")
        started, finished = manifest.get("started"), manifest.get("finished")
        if not isinstance(reports, list) or not isinstance(started, list) or not isinstance(finished, list):
            raise ValueError(f"missing execution reports or protocol receipts: {path}")
        if any(not isinstance(nodeid, str) or not nodeid for nodeid in started + finished):
            raise ValueError(f"invalid execution protocol identities: {path}")
        if Counter(started) != Counter(finished) or len(started) != len(set(started)):
            raise ValueError(f"duplicate/incomplete execution protocols: {path}")
        executed.extend(started)
        for report in reports:
            if not isinstance(report, dict) or set(report) != {
                "nodeid", "when", "outcome", "wasxfail", "is_subtest"
            } or not isinstance(report["nodeid"], str):
                raise ValueError(f"invalid test report: {path}")
            if report["when"] not in ("setup", "call", "teardown") or (
                report["outcome"] not in ("passed", "failed", "skipped")
            ) or type(report["wasxfail"]) is not bool or type(report["is_subtest"]) is not bool:
                raise ValueError(f"unknown test report outcome: {path}")
            recorded[report["nodeid"]].append(report)
    missing = sorted(set(expected) - set(executed))
    extra = sorted(set(executed) - set(expected))
    if missing or extra or len(executed) != len(expected):
        raise ValueError(
            f"xdist test identity mismatch missing={missing[:8]} extra={extra[:8]} "
            f"(missing_count={len(missing)}, extra_count={len(extra)}, "
            f"collected={len(expected)}, executed={len(executed)})"
        )
    report_missing = set(expected) - set(recorded)
    report_extra = set(recorded) - set(expected)
    if report_missing or report_extra:
        raise ValueError(f"missing/uncollected runtest reports: "
                         f"{sorted(report_missing)[:8]} / {sorted(report_extra)[:8]}")

    totals = Counter()
    for nodeid, reports in recorded.items():
        # Native unittest.TestCase.subTest produces several call reports for
        # one pytest protocol start/finish, *without* a subtest flag. These
        # are not duplicate executions: repeated protocols are checked above.
        if any(r["outcome"] == "failed" or r["wasxfail"] for r in reports):
            raise ValueError(f"failed, xfailed or unexpected report for {nodeid}")
        call = [r for r in reports if r["when"] == "call"]
        skipped = [r for r in reports if r["outcome"] == "skipped"]
        if skipped:
            if len(reports) != 1 or len(skipped) != 1 or skipped[0]["when"] not in ("setup", "call"):
                raise ValueError(f"unexpected skip report sequence: {nodeid}")
            totals["skipped"] += 1
        elif call and len(call) == len(reports) and all(r["outcome"] == "passed" for r in call):
            totals["passed"] += 1
        else:
            raise ValueError(f"missing terminal call or unexpected phase: {nodeid}")
    if totals["skipped"] != _ALLOWED_SKIPS:
        raise ValueError(f"unexpected skipped test identities: {totals['skipped']}")
    return totals


def validate_junit(path: str, *, expected_cases: int, expected_skips: int) -> None:
    root = ET.parse(path).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError(f"invalid xdist JUnit document: {path}")
    cases = list(root.iter("testcase"))
    if len(cases) != expected_cases:
        raise ValueError(f"xdist JUnit lost or duplicated cases: {path}")
    if next(root.iter("failure"), None) is not None or next(root.iter("error"), None) is not None:
        raise ValueError(f"xdist JUnit recorded error or failure: {path}")
    identities = [
        (item.get("classname"), item.get("name")) for item in cases
    ]
    if any(not classname or not name for classname, name in identities) or (
        len(set(identities)) != len(identities)
    ):
        raise ValueError(f"xdist JUnit missing or duplicate case identities: {path}")
    skips = sum(bool(list(item.iter("skipped"))) for item in cases)
    if skips != expected_skips:
        raise ValueError(f"xdist JUnit skip mismatch: {path}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 7:
        raise SystemExit("usage: xdist_summary.py COLLECTION_JSON SERIAL_AUDIT_JSON "
                         "PARALLEL_AUDIT_JSON SERIAL_LOG PARALLEL_LOG SERIAL_XML PARALLEL_XML")
    try:
        totals = validate_terminal_coverage([
            (args[3], Path(args[3]).read_text(encoding="utf-8")),
            (args[4], Path(args[4]).read_text(encoding="utf-8")),
        ])
        audited = validate_execution(*args[:3])
        if audited["passed"] != totals["passed"] or audited["skipped"] != totals["skipped"]:
            raise ValueError(f"xdist terminal/identity mismatch: {totals} vs {audited}")
        # Per-lane XML must also agree. Execution manifests capture nodeids
        # and outcomes for each lane, while the overall union is checked above.
        for audit, xml in ((args[1], args[5]), (args[2], args[6])):
            lane = _read_manifest(audit, "execution")
            # unittest.subTest emits extra call reports for one collected pytest
            # item. JUnit contains one testcase per pytest protocol, not one
            # testcase per emitted call report.
            validate_junit(xml, expected_cases=len(lane["started"]),
                           expected_skips=sum(
                               row["outcome"] == "skipped"
                               for row in lane["reports"]
                           ))
    except (OSError, ET.ParseError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"xdist coverage PASS: {totals['passed']} passed, {totals['skipped']} skipped; "
          f"{totals['passed'] + totals['skipped']} collected/executed identities reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
