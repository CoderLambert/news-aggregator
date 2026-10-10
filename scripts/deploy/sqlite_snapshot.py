#!/usr/bin/env python3
"""Consistent, permission-restricted SQLite backup and restore primitives."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterator


ARTIFACT_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
RESTORE_VERIFY_TIMEOUT_SECONDS = 120.0
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BACKUP_TIMEOUT_SECONDS = 120.0


class SnapshotError(ValueError):
    """Raised when a snapshot or restore target is unsafe or inconsistent."""


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise SnapshotError(f"{label} must be a regular file")
    return path


def _destination(path: Path, label: str) -> tuple[Path, Path]:
    if path.name in {"", ".", ".."} or path.is_symlink():
        raise SnapshotError(f"{label} path is invalid")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError:
        raise SnapshotError(f"{label} parent directory must exist") from None
    if not parent.is_dir():
        raise SnapshotError(f"{label} parent must be a directory")
    return parent / path.name, parent


def _read_release_manifest(path: Path) -> dict[str, Any]:
    _regular_file(path, "release manifest")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SnapshotError("release manifest is unreadable or invalid JSON") from None
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "release_sha", "image", "migrations", "static_sha"
    }:
        raise SnapshotError("release manifest fields are incomplete or unknown")
    if type(value["schema_version"]) is not int or value["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise SnapshotError("release manifest schema version is unsupported")
    if not isinstance(value["release_sha"], str) or not SHA_RE.fullmatch(value["release_sha"]):
        raise SnapshotError("release manifest SHA is invalid")
    image = value["image"]
    if not isinstance(image, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*", image):
        raise SnapshotError("release manifest image is invalid")
    if "@" in image:
        if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", image):
            raise SnapshotError("release manifest image digest is invalid")
    elif not re.search(rf"(?:^|[-_.]){re.escape(value['release_sha'])}$", image.rsplit(":", 1)[-1]):
        raise SnapshotError("release manifest image is not bound to its SHA")
    if not isinstance(value["static_sha"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["static_sha"]):
        raise SnapshotError("release manifest static SHA is invalid")
    migrations = value["migrations"]
    if not isinstance(migrations, list):
        raise SnapshotError("release manifest migrations are invalid")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in migrations:
        if not isinstance(item, dict) or set(item) != {"app", "name"}:
            raise SnapshotError("release migration entry must contain app and name")
        app, name = item["app"], item["name"]
        if not isinstance(app, str) or not re.fullmatch(r"[A-Za-z0-9_]+", app):
            raise SnapshotError("release migration app is invalid")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise SnapshotError("release migration name is invalid")
        pair = (app, name)
        if pair in seen:
            raise SnapshotError("release migrations contain duplicates")
        seen.add(pair)
        normalized.append({"app": app, "name": name})
    if normalized != sorted(normalized, key=lambda item: (item["app"], item["name"])):
        raise SnapshotError("release migrations must be sorted")
    return value


def _migration_rows(connection: sqlite3.Connection) -> list[dict[str, str]]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='django_migrations'"
    ).fetchone()
    if table is None:
        return []
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(django_migrations)")
    }
    if not {"app", "name"}.issubset(columns):
        raise SnapshotError("django_migrations schema is invalid")
    rows = connection.execute(
        "SELECT app, name FROM django_migrations ORDER BY app, name"
    ).fetchall()
    result = [{"app": str(app), "name": str(name)} for app, name in rows]
    if len({(item["app"], item["name"]) for item in result}) != len(result):
        raise SnapshotError("database migration rows contain duplicates")
    return result


def _open_readonly(path: Path) -> sqlite3.Connection:
    _regular_file(path, "SQLite source")
    uri = path.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise SnapshotError(f"could not open SQLite source ({type(exc).__name__})") from None


def _quick_check(connection: sqlite3.Connection) -> None:
    try:
        results = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as exc:
        raise SnapshotError(f"SQLite quick_check failed ({type(exc).__name__})") from None
    if results != [("ok",)]:
        raise SnapshotError("SQLite quick_check did not return exactly 'ok'")


def _online_backup(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
    *,
    timeout_seconds: float = BACKUP_TIMEOUT_SECONDS,
) -> None:
    """Copy a database with one absolute deadline checked on each progress step."""
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise SnapshotError("SQLite online backup timeout must be a finite positive number")
    deadline = time.monotonic() + timeout_seconds

    def check_deadline(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise SnapshotError("SQLite online backup exceeded its deadline")

    check_deadline(0, 0, 0)
    source.backup(
        destination,
        pages=256,
        progress=check_deadline,
        sleep=0.01,
    )
    check_deadline(0, 0, 0)


def _check_deadline(deadline: float | None, message: str) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise SnapshotError(message)


@contextlib.contextmanager
def _sqlite_progress_deadline(connection: sqlite3.Connection, deadline: float | None) -> Iterator[None]:
    if deadline is None:
        yield
        return

    timed_out = False

    def abort_if_expired() -> int:
        nonlocal timed_out
        if time.monotonic() >= deadline:
            timed_out = True
            return 1
        return 0

    connection.set_progress_handler(abort_if_expired, 1000)
    try:
        yield
        _check_deadline(deadline, "restore content verification exceeded its deadline")
    except sqlite3.OperationalError:
        if timed_out or time.monotonic() >= deadline:
            raise SnapshotError("restore content verification exceeded its deadline") from None
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _sha256_file(path: Path, *, deadline: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            _check_deadline(deadline, "restore content verification exceeded its deadline")
            digest.update(chunk)
    _check_deadline(deadline, "restore content verification exceeded its deadline")
    return digest.hexdigest()


def _logical_database_sha256(path: Path, *, deadline: float) -> str:
    digest = hashlib.sha256()
    timeout_message = "restore content verification exceeded its deadline"
    with contextlib.closing(_open_readonly(path)) as connection:
        with _sqlite_progress_deadline(connection, deadline):
            connection.execute("BEGIN")
            for name in ("user_version", "application_id"):
                value = connection.execute(f"PRAGMA {name}").fetchone()[0]
                digest.update(f"PRAGMA {name}={int(value)}\n".encode("ascii"))
            for line in connection.iterdump():
                _check_deadline(deadline, timeout_message)
                digest.update(line.encode("utf-8"))
                digest.update(b"\n")
            _check_deadline(deadline, timeout_message)
    return digest.hexdigest()


def _artifact_path(database: Path) -> Path:
    return Path(f"{database}.manifest.json")


def _validate_artifact(
    database: Path,
    *,
    deadline: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _check_deadline(deadline, "restore content verification exceeded its deadline")
    _regular_file(database, "snapshot database")
    sidecar = _artifact_path(database)
    _regular_file(sidecar, "snapshot manifest")
    try:
        artifact = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SnapshotError("snapshot manifest is unreadable or invalid JSON") from None
    _check_deadline(deadline, "restore content verification exceeded its deadline")
    if not isinstance(artifact, dict) or set(artifact) != {
        "schema_version", "database_sha256", "migrations", "release_manifest"
    }:
        raise SnapshotError("snapshot manifest fields are incomplete or unknown")
    if type(artifact["schema_version"]) is not int or artifact["schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise SnapshotError("snapshot manifest schema version is unsupported")
    if not isinstance(artifact["database_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["database_sha256"]):
        raise SnapshotError("snapshot database digest is invalid")
    if _sha256_file(database, deadline=deadline) != artifact["database_sha256"]:
        raise SnapshotError("snapshot database digest does not match its manifest")
    release = artifact["release_manifest"]
    if not isinstance(release, dict):
        raise SnapshotError("snapshot release manifest is missing")
    release = _read_release_manifest_from_value(release)
    migrations = artifact["migrations"]
    if not isinstance(migrations, list) or migrations != release["migrations"]:
        raise SnapshotError("snapshot migration metadata does not match its release manifest")
    with contextlib.closing(_open_readonly(database)) as connection:
        with _sqlite_progress_deadline(connection, deadline):
            _quick_check(connection)
            database_migrations = _migration_rows(connection)
    if database_migrations != migrations:
        raise SnapshotError("snapshot database migrations do not match its manifest")
    _check_deadline(deadline, "restore content verification exceeded its deadline")
    return artifact, release


def _read_release_manifest_from_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "release_sha", "image", "migrations", "static_sha"
    }:
        raise SnapshotError("embedded release manifest fields are invalid")
    # Use the same strict checks as the file parser without creating an artifact.
    if type(value["schema_version"]) is not int or value["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise SnapshotError("embedded release manifest schema version is unsupported")
    if not isinstance(value["release_sha"], str) or not SHA_RE.fullmatch(value["release_sha"]):
        raise SnapshotError("embedded release manifest SHA is invalid")
    if not isinstance(value["image"], str) or not value["image"]:
        raise SnapshotError("embedded release manifest image is invalid")
    image = value["image"]
    if "@" in image:
        if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", image):
            raise SnapshotError("embedded release manifest image digest is invalid")
    elif not re.search(rf"(?:^|[-_.]){re.escape(value['release_sha'])}$", image.rsplit(":", 1)[-1]):
        raise SnapshotError("embedded release manifest image is not bound to its SHA")
    if not isinstance(value["static_sha"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["static_sha"]):
        raise SnapshotError("embedded release manifest static SHA is invalid")
    migrations = value["migrations"]
    if not isinstance(migrations, list):
        raise SnapshotError("embedded release manifest migrations are invalid")
    for item in migrations:
        if not isinstance(item, dict) or set(item) != {"app", "name"}:
            raise SnapshotError("embedded release migration entry is invalid")
        if not isinstance(item["app"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", item["app"]):
            raise SnapshotError("embedded release migration app is invalid")
        if not isinstance(item["name"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", item["name"]):
            raise SnapshotError("embedded release migration name is invalid")
    if migrations != sorted(migrations, key=lambda item: (item["app"], item["name"])):
        raise SnapshotError("embedded release migrations must be sorted")
    if len({(item["app"], item["name"]) for item in migrations}) != len(migrations):
        raise SnapshotError("embedded release migrations contain duplicates")
    return value


def inspect_database(path: Path) -> dict[str, Any]:
    with contextlib.closing(_open_readonly(path)) as connection:
        _quick_check(connection)
        migrations = _migration_rows(connection)
    return {"quick_check": "ok", "migrations": migrations}


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _exclusive_output_lock(output: Path) -> Iterator[None]:
    lock_path = output.parent / f".{output.name}.snapshot.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SnapshotError("another snapshot operation holds the output lock") from None
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        yield
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)


def backup_database(source: Path, output: Path, release_manifest_path: Path) -> dict[str, Any]:
    output, parent = _destination(output, "snapshot output")
    sidecar = _artifact_path(output)
    if output.exists() or output.is_symlink() or sidecar.exists() or sidecar.is_symlink():
        raise SnapshotError("snapshot output already exists; refusing to overwrite")
    release_manifest = _read_release_manifest(release_manifest_path)
    temp_database: Path | None = None
    temp_manifest: Path | None = None
    published_database = False
    published_manifest = False
    completed = False
    with _exclusive_output_lock(output):
        try:
            if output.exists() or sidecar.exists():
                raise SnapshotError("snapshot output already exists; refusing to overwrite")
            fd, temp_name = tempfile.mkstemp(prefix=".newshub-snapshot.", suffix=".sqlite3", dir=parent)
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            os.close(fd)
            temp_database = Path(temp_name)
            with contextlib.closing(_open_readonly(source)) as source_connection:
                destination_connection: sqlite3.Connection | None = None
                try:
                    destination_connection = sqlite3.connect(temp_database, timeout=5)
                    _online_backup(source_connection, destination_connection)
                    _quick_check(destination_connection)
                    migrations = _migration_rows(destination_connection)
                except sqlite3.Error as exc:
                    raise SnapshotError(f"SQLite online backup failed ({type(exc).__name__})") from None
                finally:
                    if destination_connection is not None:
                        destination_connection.close()
            if migrations != release_manifest["migrations"]:
                raise SnapshotError("source database migrations do not match the release manifest")
            os.chmod(temp_database, 0o600)
            with temp_database.open("rb") as handle:
                os.fsync(handle.fileno())
            artifact = {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "database_sha256": _sha256_file(temp_database),
                "migrations": migrations,
                "release_manifest": release_manifest,
            }
            fd, manifest_name = tempfile.mkstemp(prefix=".newshub-snapshot.", suffix=".json", dir=parent)
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            temp_manifest = Path(manifest_name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(artifact, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temp_database, output)
                published_database = True
                os.link(temp_manifest, sidecar)
                published_manifest = True
                _fsync_directory(parent)
            except OSError as exc:
                raise SnapshotError(f"could not atomically publish snapshot ({type(exc).__name__})") from None
            _validate_artifact(output)
            completed = True
            return artifact
        finally:
            if temp_database is not None:
                temp_database.unlink(missing_ok=True)
            if temp_manifest is not None:
                temp_manifest.unlink(missing_ok=True)
            if not completed and published_database:
                output.unlink(missing_ok=True)
            if not completed and published_manifest:
                sidecar.unlink(missing_ok=True)


@contextlib.contextmanager
def migration_file_lock(database: Path) -> Iterator[None]:
    lock_path = database.parent / ".newshub-migrate.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as exc:
        raise SnapshotError(f"could not open migration lock ({type(exc).__name__})") from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SnapshotError("another migration or restore holds the database lock") from None
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _copy_to_temp(source: Path, directory: Path) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix=".newshub-restore.", suffix=".sqlite3", dir=directory)
    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        with contextlib.closing(_open_readonly(source)) as source_connection:
            destination_connection = sqlite3.connect(temporary, timeout=5)
            try:
                _online_backup(source_connection, destination_connection)
                _quick_check(destination_connection)
                _migration_rows(destination_connection)
            finally:
                destination_connection.close()
        return temporary
    except sqlite3.Error as exc:
        temporary.unlink(missing_ok=True)
        raise SnapshotError(f"SQLite restore staging failed ({type(exc).__name__})") from None
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_replace_database(target: Path, staged: Path, *, replace: bool) -> None:
    wal = Path(f"{target}-wal")
    shm = Path(f"{target}-shm")
    old_suffix = f".newshub-old-{uuid.uuid4().hex}"
    old_target = Path(f"{target}{old_suffix}")
    old_wal = Path(f"{wal}{old_suffix}")
    old_shm = Path(f"{shm}{old_suffix}")
    archived: list[tuple[Path, Path]] = []
    try:
        if target.exists():
            if not replace:
                raise SnapshotError("restore target exists; --replace is required")
            os.replace(target, old_target)
            archived.append((old_target, target))
        for source, old in ((wal, old_wal), (shm, old_shm)):
            if source.is_symlink():
                raise SnapshotError("SQLite WAL sidecar must not be a symlink")
            if source.exists():
                if not replace:
                    raise SnapshotError("restore target has WAL sidecars; --replace is required")
                os.replace(source, old)
                archived.append((old, source))
        os.replace(staged, target)
    except BaseException:
        if target.exists() and any(original == target for _, original in archived):
            target.unlink(missing_ok=True)
        for old, original in reversed(archived):
            if old.exists() and not original.exists():
                os.replace(old, original)
        raise
    for old, _original in archived:
        old.unlink(missing_ok=True)
    _fsync_directory(target.parent)


def restore_database(
    source: Path,
    target: Path,
    release_manifest_path: Path,
    *,
    replace: bool = False,
    writers_stopped: bool = False,
    prior_backup: Path | None = None,
    _verification_timeout_seconds: float = RESTORE_VERIFY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    artifact, embedded_release = _validate_artifact(source)
    expected_release = _read_release_manifest(release_manifest_path)
    if embedded_release != expected_release:
        raise SnapshotError("snapshot release manifest does not match the requested target manifest")
    if target.is_symlink():
        raise SnapshotError("restore target must not be a symlink")
    target, parent = _destination(target, "restore target")
    target_existed = target.exists()
    if target_existed:
        if not replace or not writers_stopped or prior_backup is None:
            raise SnapshotError("existing target requires --replace, --writers-stopped, and a prior backup")
    elif replace or prior_backup is not None:
        raise SnapshotError("--replace and prior backup are only valid for an existing target")
    staged: Path | None = None
    with migration_file_lock(target):
        try:
            if target.exists() != target_existed:
                raise SnapshotError("restore target changed before verification")
            if target_existed:
                if prior_backup is None:
                    raise SnapshotError("existing target requires a prior backup")
                if (
                    isinstance(_verification_timeout_seconds, bool)
                    or not isinstance(_verification_timeout_seconds, (int, float))
                    or not math.isfinite(_verification_timeout_seconds)
                    or _verification_timeout_seconds <= 0
                ):
                    raise SnapshotError("restore verification timeout must be a finite positive number")
                deadline = time.monotonic() + _verification_timeout_seconds
                _validate_artifact(prior_backup, deadline=deadline)
                prior_digest = _logical_database_sha256(prior_backup, deadline=deadline)
                target_digest = _logical_database_sha256(target, deadline=deadline)
                if prior_digest != target_digest:
                    raise SnapshotError("prior backup does not match the current target content")
            staged = _copy_to_temp(source, parent)
            with contextlib.closing(_open_readonly(staged)) as connection:
                _quick_check(connection)
                staged_migrations = _migration_rows(connection)
            if staged_migrations != expected_release["migrations"]:
                raise SnapshotError("restored database migration set does not match release manifest")
            _atomic_replace_database(target, staged, replace=replace)
            staged = None
            return {
                "restored": str(target),
                "migrations": artifact["migrations"],
                "quick_check": "ok",
            }
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--source", required=True, type=Path)
    backup.add_argument("--output", required=True, type=Path)
    backup.add_argument("--release-manifest", required=True, type=Path)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--source", required=True, type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--database", required=True, type=Path)
    validate.add_argument("--release-manifest", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--source", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    restore.add_argument("--release-manifest", required=True, type=Path)
    restore.add_argument("--replace", action="store_true")
    restore.add_argument("--writers-stopped", action="store_true")
    restore.add_argument("--prior-backup", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            result = backup_database(args.source, args.output, args.release_manifest)
        elif args.command == "inspect":
            result = inspect_database(args.source)
        elif args.command == "validate":
            artifact, release = _validate_artifact(args.database)
            if args.release_manifest and _read_release_manifest(args.release_manifest) != release:
                raise SnapshotError("snapshot release manifest does not match the requested manifest")
            result = {"artifact": artifact, "quick_check": "ok"}
        else:
            result = restore_database(
                args.source,
                args.target,
                args.release_manifest,
                replace=args.replace,
                writers_stopped=args.writers_stopped,
                prior_backup=args.prior_backup,
            )
        print(json.dumps(result, sort_keys=True))
    except (SnapshotError, OSError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, SnapshotError) else f"operation failed ({type(exc).__name__})"
        print(f"sqlite-snapshot: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
