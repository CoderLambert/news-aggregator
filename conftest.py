"""Disposable, process-isolated SQLite schema template for offline tests.

The template is created once per pytest session in a subprocess. Each
consumer uses SQLite's online backup into its own temp path; no child shares a
database, WAL file, process, file lock or credentials with any other test.
Tests exercising migrations themselves must still create their own databases.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def migrated_synthetic_db(tmp_path_factory):
    directory = tmp_path_factory.mktemp("news-synthetic-schema")
    database = directory / "template.sqlite3"
    if database.exists():
        raise AssertionError("synthetic migration template must be fresh")
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT / "backend"), str(ROOT / "crawler"))),
        "DJANGO_SETTINGS_MODULE": "newsaggregator.settings",
        "DJANGO_ENV": "development",
        "DJANGO_DB_PATH": str(database),
        "RUN_MAIN": "true",
        "NEWS_CRAWL_ONLY": "1",
        "CRAWLER_SCHEDULER_ENABLED": "0",
        "FULL_CONTENT_WORKER_ENABLED": "0",
    }
    code = (
        "import django\n"
        "django.setup()\n"
        "from django.core.management import call_command\n"
        "from django.db import connection\n"
        "call_command('migrate', verbosity=0)\n"
        "connection.close()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not database.is_file():
        raise AssertionError(
            "isolated synthetic schema migration failed: "
            + result.stderr[-1600:]
        )
    return database


def backup_synthetic_db(template: Path, target: Path) -> None:
    """Snapshot committed SQLite content without copying a live WAL file."""
    import sqlite3
    from contextlib import closing

    if target.exists():
        raise AssertionError("test must use a new isolated database target")
    with closing(sqlite3.connect(template.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)

@pytest.fixture
def copy_synthetic_db(migrated_synthetic_db):
    def copy(destination: Path) -> None:
        backup_synthetic_db(migrated_synthetic_db, destination)
    return copy
