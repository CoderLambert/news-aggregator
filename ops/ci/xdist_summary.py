"""Fail-closed validation for the hybrid pytest benchmark summaries."""
from collections import Counter
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# Two paint regression tests were added by merged PR #86 to the previous
# 2408-passed baseline. The 16 explicit skips remain unchanged.
_EXPECTED = {"passed": 2410, "skipped": 16}
_SUMMARY = re.compile(
    r"^\s*=*\s*"
    r"(?P<outcomes>\d+\s+[A-Za-z][A-Za-z_-]*"
    r"(?:\s*,\s*\d+\s+[A-Za-z][A-Za-z_-]*)*)"
    r"\s+in\s+\d+(?:\.\d+)?s"
    r"(?:\s+\([^()\r\n]*\))?"
    r"\s*=*\s*$"
)
_ITEM = re.compile(r"(\d+)\s+([A-Za-z][A-Za-z_-]*)")
_ALLOWED = {"passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed", "warning", "warnings"}


def parse_terminal_summary(contents: str, *, source: str = "<log>") -> Counter:
    """Parse exactly one full pytest terminal summary line from a captured log."""
    matches = [
        match
        for line in contents.splitlines()
        if (match := _SUMMARY.fullmatch(line)) is not None
    ]
    if len(matches) != 1:
        raise ValueError(
            f"xdist benchmark terminal summary missing or ambiguous: {source}"
        )

    counts = Counter()
    for count, outcome in _ITEM.findall(matches[0].group("outcomes")):
        key = outcome.lower()
        if key not in _ALLOWED:
            raise ValueError(f"unknown pytest summary outcome {key!r}: {source}")
        counts[key] += int(count)
    return counts


def validate_terminal_coverage(logs: list[tuple[str, str]]) -> Counter:
    """Require the updated 2410 passed / 16 skipped baseline and no failures."""
    total = Counter()
    for source, contents in logs:
        total.update(parse_terminal_summary(contents, source=source))

    unexpected = {
        key: value
        for key, value in total.items()
        if key not in {"passed", "skipped", "warning", "warnings"} and value
    }
    actual = {key: total[key] for key in ("passed", "skipped") if total[key]}
    if unexpected or actual != _EXPECTED:
        raise ValueError(
            "xdist benchmark coverage mismatch: "
            f"passed={total['passed']} skipped={total['skipped']} "
            f"other={unexpected}; expected 2410/16 with zero failures"
        )
    return total


def validate_junit(path: str) -> None:
    root = ET.parse(path).getroot()
    if any(root.iter("failure")) or any(root.iter("error")):
        raise ValueError(f"xdist benchmark JUnit recorded an error or failure: {path}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4:
        raise SystemExit(
            "usage: xdist_summary.py SERIAL_LOG PARALLEL_LOG SERIAL_XML PARALLEL_XML"
        )

    try:
        totals = validate_terminal_coverage(
            [
                (args[0], Path(args[0]).read_text(encoding="utf-8")),
                (args[1], Path(args[1]).read_text(encoding="utf-8")),
            ]
        )
        validate_junit(args[2])
        validate_junit(args[3])
    except (OSError, ET.ParseError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(
        "xdist benchmark coverage PASS: "
        f"passed={totals['passed']}, skipped={totals['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
