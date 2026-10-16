#!/usr/bin/env python3
"""Validate a frozen CI requirements set without importing untrusted packages.

Use inside a venv to check every distribution (including transitive ones).
No HTTP calls, secrets, repository mutations, or filesystem pruning.
"""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([0-9][A-Za-z0-9.+_-]*)$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned(lock: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw in enumerate(lock.read_text(encoding="utf-8").splitlines(), 1):
        entry = raw.partition("#")[0].strip()
        if not entry:
            continue
        match = PIN.fullmatch(entry)
        if not match:
            raise ValueError(f"CI lock line {lineno} must be an exact name==version")
        name, pin = canonical(match.group(1)), match.group(2)
        if name in values:
            raise ValueError(f"CI lock duplicate distribution: {name}")
        values[name] = pin
    if not values:
        raise ValueError("CI lock contains no pinned distributions")
    for required, expected in (("torch", "2.14.1+cpu"), ("playwright", "1.62.0")):
        if values.get(required) != expected:
            raise ValueError(f"CI lock must pin {required}=={expected}")
    return values


def required_direct(requirements: Path) -> set[str]:
    result = set()
    for lineno, raw in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
        entry = raw.partition("#")[0].strip()
        if not entry:
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?=[<=>!~;\s]|$)", entry)
        if not match or not NAME.fullmatch(match.group(1)):
            raise ValueError(f"unsupported direct requirement at line {lineno}")
        result.add(canonical(match.group(1)))
    return result


def check(req: Path, lock: Path, installed: bool = False) -> dict[str, str]:
    versions = pinned(lock)
    missing = required_direct(req) - set(versions)
    if missing:
        raise ValueError("CI lock missing direct dependencies: " + ", ".join(sorted(missing)))
    if installed:
        for name, expected in versions.items():
            try:
                actual = version(name)
            except PackageNotFoundError as exc:
                raise ValueError(f"CI lock dependency is not installed: {name}") from exc
            if actual != expected:
                raise ValueError(f"CI lock mismatch: {name} expected {expected} got {actual}")
    return versions


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "--installed"):
        print("usage: check-backend-lock.py REQUIREMENTS LOCK [--installed]", file=sys.stderr)
        return 2
    try:
        rows = check(Path(argv[0]), Path(argv[1]), installed=len(argv) == 3)
    except (OSError, ValueError) as exc:
        print(f"CI lock validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"NewsHub CI lock: {len(rows)} exact package pins validated"
          + (" against installed versions" if len(argv) == 3 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
