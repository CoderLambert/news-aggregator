"""Identity-level audit of pytest collection and test reports for the hybrid CI runner.

Loaded explicitly with `-p coverage_audit`. The xdist controller receives
runtest reports; workers never write manifests to a shared filename.
"""
import json
from pathlib import Path

import pytest

def _canonical_nodeid(nodeid):
    # Passing individual serial modules changes pytest's inferred rootdir
    # from repository root to backend/. The identity still names the same
    # collected test; normalize only this known safe path prefix.
    return "backend/" + nodeid if nodeid.startswith("api/tests/") else nodeid


_collected = []
_started = []
_finished = []
_reports = []


def pytest_addoption(parser):
    group = parser.getgroup("newshub-ci-coverage")
    group.addoption("--ci-audit-output", default=None, metavar="FILE",
                    help="Write a CI-only JSON manifest of collected tests or execution reports")


def pytest_collection_finish(session):
    if session.config.getoption("--ci-audit-output") and session.config.option.collectonly:
        _collected.extend(_canonical_nodeid(item.nodeid) for item in session.items)


def pytest_runtest_logstart(nodeid, location):
    # A protocol start is emitted once per pytest item, unlike the multiple
    # call reports emitted by unittest.TestCase.subTest.
    _started.append(_canonical_nodeid(nodeid))


def pytest_runtest_logfinish(nodeid, location):
    _finished.append(_canonical_nodeid(nodeid))


def pytest_runtest_logreport(report):
    # A setup skip has no call report; a teardown failure is important even
    # when the test call itself passed. The controller receives xdist reports.
    if report.when == "call" or report.failed or report.skipped:
        _reports.append({
            "nodeid": _canonical_nodeid(report.nodeid),
            "when": report.when,
            "outcome": report.outcome,
            "wasxfail": bool(getattr(report, "wasxfail", False)),
            "is_subtest": hasattr(report, "subtest"),
        })


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    target = config.getoption("--ci-audit-output")
    if not target or hasattr(config, "workerinput"):
        return
    if config.option.collectonly:
        manifest = {"kind": "collection", "nodeids": _collected}
    else:
        manifest = {"kind": "execution", "started": _started,
                    "finished": _finished, "reports": _reports}
    # The parent runner owns a private TMPDIR. Never emit secrets, test output,
    # tracebacks or request payloads into the audit manifest.
    Path(target).write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
