#!/usr/bin/env python3
"""Capture a stopped SQLite WAL database into a private writable directory."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path


FILES = ("db.sqlite3", "db.sqlite3-wal", "db.sqlite3-shm")


class StageError(ValueError):
    """Raised when a stopped database cannot be captured safely."""


def _snapshot_state(source_fd: int) -> dict[str, tuple[int, int, int, int] | None]:
    result: dict[str, tuple[int, int, int, int] | None] = {}
    for name in FILES:
        try:
            info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        except FileNotFoundError:
            result[name] = None
            continue
        if not stat.S_ISREG(info.st_mode):
            raise StageError(f"SQLite source member is not a regular file: {name}")
        result[name] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if result["db.sqlite3"] is None:
        raise StageError("SQLite source database is missing")
    return result


def _copy_member(source_fd: int, destination_fd: int, name: str, expected_size: int) -> None:
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    input_fd = os.open(name, source_flags, dir_fd=source_fd)
    try:
        output_fd = os.open(name, destination_flags, 0o600, dir_fd=destination_fd)
        try:
            copied = 0
            while True:
                chunk = os.read(input_fd, 1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(output_fd, view)
                    if written <= 0:
                        raise StageError(f"short write while staging {name}")
                    copied += written
                    view = view[written:]
            if copied != expected_size:
                raise StageError(f"SQLite source member changed size while staging: {name}")
            os.fsync(output_fd)
        finally:
            os.close(output_fd)
    finally:
        os.close(input_fd)


def stage(source: Path, destination: Path) -> dict[str, int]:
    if destination.exists() or destination.is_symlink():
        raise StageError("staging destination already exists")
    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        before = _snapshot_state(source_fd)
        destination.mkdir(mode=0o700)
        destination_fd = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            copied: dict[str, int] = {}
            for name in FILES:
                member_state = before[name]
                if member_state is None:
                    continue
                size = member_state[2]
                _copy_member(source_fd, destination_fd, name, size)
                copied[name] = size
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
        after = _snapshot_state(source_fd)
        if after != before:
            raise StageError("SQLite source members changed while staging; writers may still be active")
        return copied
    finally:
        os.close(source_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--destination-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        copied = stage(args.source_dir, args.destination_dir)
    except (OSError, StageError) as exc:
        print(f"sqlite-stage: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"captured": copied}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
