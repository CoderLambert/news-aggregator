"""Identity-level audit of pytest collection and test reports for the hybrid CI runner.

Loaded explicitly with `-p coverage_audit`. The xdist controller receives
runtest reports; workers never write manifests to a shared filename.
"""
import json
from pathlib import Path

import pytest

_collected = []
_reports = []


def pytest_addoption(parser):
    group = parser.getgroup("newshub-ci-coverage")
    group.addoption("--ci-audit-output", default=None, metavar="FILE",
                    help="Write a CI-only JSON manifest of collected tests or execution reports")


def pytest_collection_finish(session):
    if session.config.getoption("--ci-audit-output") and session.config.option.collectonly:
        _collected.extend(item.nodeid for item in session.items)


def pytest_runtest_logreport(report):
    # A setup skip has no call report; a teardown failure is important even
    # when the test call itself passed. The controller receives xdist reports.
    if report.when == "call" or report.failed or report.skipped:
        _reports.append({
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "wasxfail": bool(getattr(report, "wasxfail", False)),
        })


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    target = config.getoption("--ci-audit-output")
    if not target or hasattr(config, "workerinput"):
        return
    if config.option.collectonly:
        manifest = {"kind": "collection", "nodeids": _collected}
    else:
        manifest = {"kind": "execution", "reports": _reports}
    # The parent runner owns a private TMPDIR. Never emit secrets, test output,
    # tracebacks or request payloads into the audit manifest.
    Path(target).write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
