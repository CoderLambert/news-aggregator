#!/usr/bin/env python3
"""Safely inspect and prune NewsHub content-addressed dependency caches."""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import sys


KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def valid_root(value: str) -> Path:
    root = Path(value)
    if not root.is_absolute() or root == Path("/"):
        raise argparse.ArgumentTypeError("cache root must be an absolute, non-root path")
    if root.is_symlink():
        raise argparse.ArgumentTypeError("cache root must not be a symlink")
    return root


def current_key(root: Path) -> str | None:
    marker = root / ".current-key"
    if not marker.exists():
        return None
    if marker.is_symlink() or not marker.is_file():
        raise ValueError("invalid current cache key marker")
    value = marker.read_text(encoding="utf-8").strip()
    if not KEY_PATTERN.fullmatch(value):
        raise ValueError("invalid current cache key")
    return value


def keyed_directories(root: Path) -> list[Path]:
    entries: list[Path] = []
    for entry in root.iterdir():
        if (
            KEY_PATTERN.fullmatch(entry.name)
            and not entry.is_symlink()
            and entry.is_dir()
        ):
            entries.append(entry)
    return sorted(entries, key=lambda item: item.name)


def is_successful(entry: Path) -> bool:
    marker = entry / ".newshub-ready"
    return (
        marker.is_file()
        and not marker.is_symlink()
        and marker.read_text(encoding="utf-8").strip() == entry.name
    )


def plan(root: Path, keep_successful: int) -> tuple[list[Path], list[Path]]:
    current = current_key(root)
    entries = keyed_directories(root)
    successful = sorted(
        (entry for entry in entries if is_successful(entry)),
        key=lambda entry: entry.stat().st_mtime_ns,
        reverse=True,
    )
    keep = {entry.name for entry in successful[:keep_successful]}
    if current is not None:
        keep.add(current)
    kept = [entry for entry in entries if entry.name in keep]
    removable = [entry for entry in entries if entry.name not in keep]
    return kept, removable


def safe_remove(root: Path, entry: Path) -> None:
    if entry.parent != root or not KEY_PATTERN.fullmatch(entry.name):
        raise ValueError(f"refusing unsafe cache path: {entry}")
    mode = entry.lstat().st_mode
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise ValueError(f"refusing changed cache path: {entry}")
    shutil.rmtree(entry)


def gc(root: Path, keep_successful: int, execute: bool) -> int:
    if not root.exists():
        print(f"CACHE_ROOT_MISSING {root}")
        return 0
    if not root.is_dir():
        raise ValueError("cache root must be a directory")

    if execute:
        lock_path = root / ".install.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "r+", encoding="utf-8"):
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                kept, removable = plan(root, keep_successful)
                for entry in kept:
                    print(f"KEEP {entry}")
                for entry in removable:
                    safe_remove(root, entry)
                    print(f"REMOVED {entry}")
        finally:
            # fdopen closes the descriptor on the normal and exceptional paths.
            pass
    else:
        kept, removable = plan(root, keep_successful)
        for entry in kept:
            print(f"KEEP {entry}")
        for entry in removable:
            print(f"WOULD_REMOVE {entry}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)
    gc_parser = subcommands.add_parser("gc", help="plan or execute targeted cache cleanup")
    gc_parser.add_argument("--root", required=True, type=valid_root)
    gc_parser.add_argument("--keep-successful", type=int, default=2)
    gc_parser.add_argument("--execute", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.keep_successful < 0:
        raise ValueError("keep-successful must be non-negative")
    return gc(args.root, args.keep_successful, args.execute)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"cache-maintenance: {exc}", file=sys.stderr)
        raise SystemExit(2)
