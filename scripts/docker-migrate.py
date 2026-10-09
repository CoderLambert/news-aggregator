#!/usr/bin/env python3
"""Run production Django migrations under a nonblocking SQLite-directory lock."""

from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class MigrationLockHeld(RuntimeError):
    """Raised when another migration process already owns the database lock."""


@contextmanager
def migration_lock(database_path: str | os.PathLike[str]) -> Iterator[None]:
    database_directory = Path(database_path).parent
    database_directory.mkdir(parents=True, exist_ok=True)
    lock_path = database_directory / ".newshub-migrate.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MigrationLockHeld from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> int:
    if os.environ.get("DJANGO_ENV") != "production":
        print("docker-migrate.py requires DJANGO_ENV=production.", file=sys.stderr)
        return 2

    repository_root = Path(__file__).resolve().parents[1]
    backend_path = repository_root / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsaggregator.settings")

    import django

    django.setup()

    from django.conf import settings
    from django.core.management import execute_from_command_line

    database_path = Path(settings.DATABASES["default"]["NAME"])
    if not database_path.is_absolute():
        print("Production SQLite database path must be absolute.", file=sys.stderr)
        return 2

    try:
        with migration_lock(database_path):
            execute_from_command_line(
                [str(backend_path / "manage.py"), "migrate", "--noinput"]
            )
    except MigrationLockHeld:
        print("Another migration already holds the database directory lock.", file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
