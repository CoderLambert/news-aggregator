from __future__ import annotations

import json
import contextlib
import io
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.deploy import release_manifest, sqlite_snapshot, sqlite_stage


ROOT = Path(__file__).resolve().parents[3]
RELEASE_SHA = "a" * 40
MIGRATIONS = [
    {"app": "api", "name": "0001_initial"},
    {"app": "auth", "name": "0001_initial"},
]


def manifest(image: str | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "release_sha": RELEASE_SHA,
        "image": image or f"newshub:{RELEASE_SHA}",
        "migrations": MIGRATIONS,
        "static_sha": "b" * 64,
    }


def write_manifest(path: Path, value: dict[str, object] | None = None) -> Path:
    path.write_text(json.dumps(value or manifest()), encoding="utf-8")
    return path


def make_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app varchar(255), name varchar(255), applied datetime)"
    )
    connection.executemany(
        "INSERT INTO django_migrations (app, name, applied) VALUES (?, ?, CURRENT_TIMESTAMP)",
        [(item["app"], item["name"]) for item in MIGRATIONS],
    )
    connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    connection.execute("INSERT INTO records (body) VALUES ('committed row')")
    connection.commit()
    return connection


class SQLiteSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.sqlite3"
        self.connection = make_database(self.source)
        self.release = write_manifest(self.root / "release.json")

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def read_rows(self, path: Path) -> list[str]:
        with sqlite3.connect(path) as connection:
            return [row[0] for row in connection.execute("SELECT body FROM records ORDER BY id")]

    def test_online_backup_progress_callback_enforces_absolute_deadline(self) -> None:
        class Source:
            called = False

            def backup(self, _destination, *, progress, **_kwargs) -> None:
                self.called = True
                progress(0, 1, 1)

        source = Source()
        clock_values = iter((0.0, 0.0, 1.0))
        with patch.object(sqlite_snapshot.time, "monotonic", side_effect=lambda: next(clock_values)):
            with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "exceeded its deadline"):
                sqlite_snapshot._online_backup(source, object(), timeout_seconds=0.5)  # type: ignore[arg-type]
        self.assertTrue(source.called)

    def test_sqlite_error_details_preserve_code_and_name(self) -> None:
        error = sqlite3.OperationalError("synthetic")
        error.sqlite_errorcode = sqlite3.SQLITE_CANTOPEN
        error.sqlite_errorname = "SQLITE_CANTOPEN"
        self.assertEqual(
            sqlite_snapshot._sqlite_error_details(error),
            "OperationalError, name=SQLITE_CANTOPEN, code=14",
        )

    def test_stopped_wal_members_are_captured_without_mutation(self) -> None:
        source_dir = self.root / "volume"
        source_dir.mkdir()
        (source_dir / "db.sqlite3").hardlink_to(self.source)
        (source_dir / "db.sqlite3-wal").hardlink_to(Path(f"{self.source}-wal"))
        (source_dir / "db.sqlite3-shm").hardlink_to(Path(f"{self.source}-shm"))
        capture = self.root / "capture"
        copied = sqlite_stage.stage(source_dir, capture)
        self.assertEqual(set(copied), {"db.sqlite3", "db.sqlite3-wal", "db.sqlite3-shm"})
        self.assertEqual((capture / "db.sqlite3").stat().st_mode & 0o777, 0o600)
        self.assertEqual((capture / "db.sqlite3-wal").stat().st_mode & 0o777, 0o600)
        self.assertEqual((capture / "db.sqlite3-shm").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.read_rows(capture / "db.sqlite3"), ["committed row"])

    def test_staging_rejects_source_change(self) -> None:
        source_dir = self.root / "volume"
        source_dir.mkdir()
        (source_dir / "db.sqlite3").hardlink_to(self.source)
        (source_dir / "db.sqlite3-wal").hardlink_to(Path(f"{self.source}-wal"))
        (source_dir / "db.sqlite3-shm").hardlink_to(Path(f"{self.source}-shm"))
        capture = self.root / "capture"
        original = sqlite_stage._snapshot_state
        calls = 0

        def changed(source_fd):
            nonlocal calls
            calls += 1
            state = original(source_fd)
            if calls == 2:
                database = state["db.sqlite3"]
                assert database is not None
                state["db.sqlite3"] = (*database[:2], database[2] + 1, database[3])
            return state

        with patch.object(sqlite_stage, "_snapshot_state", side_effect=changed):
            with self.assertRaisesRegex(sqlite_stage.StageError, "writers may still be active"):
                sqlite_stage.stage(source_dir, capture)

    def test_backup_and_restore_deadline_failures_close_and_clean_staging(self) -> None:
        real_connect = sqlite3.connect
        real_online_backup = sqlite_snapshot._online_backup
        opened_destinations: list[sqlite3.Connection] = []

        def track_destination(database, *args, **kwargs):
            connection = real_connect(database, *args, **kwargs)
            if ".newshub-snapshot." in os.fspath(database) or ".newshub-restore." in os.fspath(database):
                opened_destinations.append(connection)
            return connection

        def advancing_clock():
            advancing_clock.calls += 1
            return 0.0 if advancing_clock.calls <= 2 else 1.0

        advancing_clock.calls = 0
        output = self.root / "timed-out.sqlite3"
        with patch.object(sqlite_snapshot.sqlite3, "connect", side_effect=track_destination):
            with patch.object(sqlite_snapshot.time, "monotonic", side_effect=advancing_clock):
                with patch.object(
                    sqlite_snapshot,
                    "_online_backup",
                    side_effect=lambda source, destination: real_online_backup(
                        source, destination, timeout_seconds=0.5
                    ),
                ):
                    with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "exceeded its deadline"):
                        sqlite_snapshot.backup_database(self.source, output, self.release)
        self.assertFalse(output.exists())
        self.assertFalse(sqlite_snapshot._artifact_path(output).exists())
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir() if path.name.startswith(".newshub-snapshot.")),
            [],
        )
        self.assertEqual(len(opened_destinations), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened_destinations[-1].execute("SELECT 1")

        snapshot = self.root / "valid.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        target = self.root / "existing.sqlite3"
        existing = make_database(target)
        existing.close()
        prior = self.root / "prior.sqlite3"
        sqlite_snapshot.backup_database(target, prior, self.release)
        original_target = target.read_bytes()
        advancing_clock.calls = 0
        with patch.object(sqlite_snapshot.sqlite3, "connect", side_effect=track_destination):
            with patch.object(
                sqlite_snapshot,
                "_online_backup",
                side_effect=sqlite_snapshot.SnapshotError("SQLite online backup exceeded its deadline"),
            ):
                with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "exceeded its deadline"):
                    sqlite_snapshot.restore_database(
                        snapshot,
                        target,
                        self.release,
                        replace=True,
                        writers_stopped=True,
                        prior_backup=prior,
                    )
        self.assertEqual(target.read_bytes(), original_target)
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir() if path.name.startswith(".newshub-restore.")),
            [],
        )
        self.assertEqual(len(opened_destinations), 2)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened_destinations[-1].execute("SELECT 1")

    def test_wal_backup_contains_committed_rows_but_not_an_open_transaction(self) -> None:
        wal = Path(f"{self.source}-wal")
        self.assertTrue(wal.exists())
        self.connection.execute("BEGIN IMMEDIATE")
        self.connection.execute("INSERT INTO records (body) VALUES ('uncommitted row')")

        snapshot = self.root / "online.sqlite3"
        result = sqlite_snapshot.backup_database(self.source, snapshot, self.release)

        self.assertEqual(result["migrations"], MIGRATIONS)
        self.assertEqual(self.read_rows(snapshot), ["committed row"])
        self.assertEqual(sqlite_snapshot.inspect_database(snapshot)["quick_check"], "ok")
        self.connection.rollback()

    def test_restore_new_target_preserves_rows_and_schema(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        restored = self.root / "restored.sqlite3"

        result = sqlite_snapshot.restore_database(snapshot, restored, self.release)

        self.assertEqual(result["quick_check"], "ok")
        self.assertEqual(self.read_rows(restored), ["committed row"])
        self.assertEqual(sqlite_snapshot.inspect_database(restored)["migrations"], MIGRATIONS)
        self.assertEqual(stat.S_IMODE(restored.stat().st_mode), 0o600)

    def test_existing_target_requires_stop_and_an_existing_valid_old_backup(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        target = self.root / "existing.sqlite3"
        previous = make_database(target)
        previous.execute("INSERT INTO records (body) VALUES ('old-only row')")
        previous.commit()
        previous.close()
        old_snapshot = self.root / "old.sqlite3"
        sqlite_snapshot.backup_database(target, old_snapshot, self.release)
        original = target.read_bytes()

        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "writers-stopped"):
            sqlite_snapshot.restore_database(snapshot, target, self.release)
        self.assertEqual(target.read_bytes(), original)

        sqlite_snapshot.restore_database(
            snapshot,
            target,
            self.release,
            replace=True,
            writers_stopped=True,
            prior_backup=old_snapshot,
        )
        self.assertFalse(Path(f"{target}-wal").exists())
        self.assertFalse(Path(f"{target}-shm").exists())
        self.assertEqual(self.read_rows(target), ["committed row"])

    def test_restore_rejects_stale_or_wrong_prior_and_keeps_target_and_wal_unchanged(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        target = self.root / "existing.sqlite3"
        target_connection = make_database(target)
        stale_prior = self.root / "stale-prior.sqlite3"
        sqlite_snapshot.backup_database(target, stale_prior, self.release)
        target_connection.execute("INSERT INTO records (body) VALUES ('committed after backup')")
        target_connection.commit()
        wal = Path(f"{target}-wal")
        self.assertTrue(wal.exists())
        original_target = target.read_bytes()
        original_wal = wal.read_bytes()

        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "does not match the current target"):
            sqlite_snapshot.restore_database(
                snapshot,
                target,
                self.release,
                replace=True,
                writers_stopped=True,
                prior_backup=stale_prior,
            )
        self.assertEqual(target.read_bytes(), original_target)
        self.assertEqual(wal.read_bytes(), original_wal)
        self.assertEqual(self.read_rows(target), ["committed row", "committed after backup"])

        foreign = self.root / "foreign.sqlite3"
        foreign_connection = make_database(foreign)
        foreign_connection.execute("UPDATE records SET body='different database row'")
        foreign_connection.commit()
        foreign_connection.close()
        wrong_prior = self.root / "wrong-prior.sqlite3"
        sqlite_snapshot.backup_database(foreign, wrong_prior, self.release)
        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "does not match the current target"):
            sqlite_snapshot.restore_database(
                snapshot,
                target,
                self.release,
                replace=True,
                writers_stopped=True,
                prior_backup=wrong_prior,
            )
        self.assertEqual(target.read_bytes(), original_target)
        self.assertEqual(wal.read_bytes(), original_wal)
        target_connection.close()

    def test_restore_content_verification_deadline_is_bounded_and_does_not_replace(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        target = self.root / "existing.sqlite3"
        target_connection = make_database(target)
        prior = self.root / "prior.sqlite3"
        sqlite_snapshot.backup_database(target, prior, self.release)
        original = target.read_bytes()
        clock_values = iter((0.0, 2.0))
        with patch.object(sqlite_snapshot.time, "monotonic", side_effect=lambda: next(clock_values)):
            with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "exceeded its deadline"):
                sqlite_snapshot.restore_database(
                    snapshot,
                    target,
                    self.release,
                    replace=True,
                    writers_stopped=True,
                    prior_backup=prior,
                    _verification_timeout_seconds=1.0,
                )
        self.assertEqual(target.read_bytes(), original)
        target_connection.close()

    def test_restore_verification_progress_handler_aborts_and_is_removed(self) -> None:
        class FakeConnection:
            handler = None
            instruction_count = 0

            def set_progress_handler(self, handler, instruction_count):
                self.handler = handler
                self.instruction_count = instruction_count

        connection = FakeConnection()
        with patch.object(sqlite_snapshot.time, "monotonic", return_value=5.0):
            with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "exceeded its deadline"):
                with sqlite_snapshot._sqlite_progress_deadline(connection, 4.0):  # type: ignore[arg-type]
                    self.assertEqual(connection.instruction_count, 1000)
                    self.assertEqual(connection.handler(), 1)
        self.assertIsNone(connection.handler)
        self.assertEqual(connection.instruction_count, 0)

    def test_logical_digest_covers_schema_rows_and_sqlite_header_pragmas(self) -> None:
        target = self.root / "digest-source.sqlite3"
        connection = make_database(target)
        connection.close()
        first_deadline = sqlite_snapshot.time.monotonic() + 120
        before = sqlite_snapshot._logical_database_sha256(target, deadline=first_deadline)
        with sqlite3.connect(target) as updated:
            updated.execute("PRAGMA user_version=7")
            updated.execute("PRAGMA application_id=12345")
        second_deadline = sqlite_snapshot.time.monotonic() + 120
        after = sqlite_snapshot._logical_database_sha256(target, deadline=second_deadline)
        self.assertNotEqual(before, after)

        snapshot = self.root / "digest-copy.sqlite3"
        sqlite_snapshot.backup_database(target, snapshot, self.release)
        copied_deadline = sqlite_snapshot.time.monotonic() + 120
        self.assertEqual(
            after,
            sqlite_snapshot._logical_database_sha256(snapshot, deadline=copied_deadline),
        )

    def test_bad_snapshot_manifest_or_database_is_rejected_without_target_change(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        target = self.root / "existing.sqlite3"
        original_db = make_database(target)
        original_db.close()
        old_snapshot = self.root / "old.sqlite3"
        sqlite_snapshot.backup_database(target, old_snapshot, self.release)
        original = target.read_bytes()

        sidecar = sqlite_snapshot._artifact_path(snapshot)
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        value["database_sha256"] = "0" * 64
        sidecar.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "digest"):
            sqlite_snapshot.restore_database(
                snapshot,
                target,
                self.release,
                replace=True,
                writers_stopped=True,
                prior_backup=old_snapshot,
            )
        self.assertEqual(target.read_bytes(), original)

    def test_backup_refuses_existing_output_and_cleans_failed_partial_files(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        original = snapshot.read_bytes()
        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "already exists"):
            sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        self.assertEqual(snapshot.read_bytes(), original)

        incompatible_manifest = write_manifest(
            self.root / "incompatible.json",
            {**manifest(), "migrations": [{"app": "api", "name": "9999_unknown"}]},
        )
        failed = self.root / "failed.sqlite3"
        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "do not match"):
            sqlite_snapshot.backup_database(self.source, failed, incompatible_manifest)
        self.assertFalse(failed.exists())
        self.assertFalse(sqlite_snapshot._artifact_path(failed).exists())
        self.assertEqual(
            sorted(item.name for item in self.root.iterdir() if item.name.startswith(".newshub-snapshot.")),
            [],
        )

    def test_bad_sqlite_snapshot_is_rejected_and_does_not_replace_target(self) -> None:
        snapshot = self.root / "bad.sqlite3"
        snapshot.write_bytes(b"not a sqlite database")
        sidecar = sqlite_snapshot._artifact_path(snapshot)
        sidecar.write_text(
            json.dumps({
                "schema_version": 1,
                "database_sha256": sqlite_snapshot._sha256_file(snapshot),
                "migrations": MIGRATIONS,
                "release_manifest": manifest(),
            }),
            encoding="utf-8",
        )
        target = self.root / "existing.sqlite3"
        old = make_database(target)
        old.close()
        old_bytes = target.read_bytes()
        prior = self.root / "prior.sqlite3"
        sqlite_snapshot.backup_database(target, prior, self.release)
        with self.assertRaises(sqlite_snapshot.SnapshotError):
            sqlite_snapshot.restore_database(
                snapshot,
                target,
                self.release,
                replace=True,
                writers_stopped=True,
                prior_backup=prior,
            )
        self.assertEqual(target.read_bytes(), old_bytes)

    def test_restore_rejects_target_migration_mismatch_and_active_migration_lock(self) -> None:
        snapshot = self.root / "snapshot.sqlite3"
        sqlite_snapshot.backup_database(self.source, snapshot, self.release)
        target = self.root / "target.sqlite3"
        wrong_release = write_manifest(
            self.root / "wrong-release.json",
            {**manifest(), "migrations": [{"app": "api", "name": "0002_future"}]},
        )
        with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "does not match"):
            sqlite_snapshot.restore_database(snapshot, target, wrong_release)
        self.assertFalse(target.exists())

        with sqlite_snapshot.migration_file_lock(target):
            with self.assertRaisesRegex(sqlite_snapshot.SnapshotError, "migration or restore"):
                sqlite_snapshot.restore_database(snapshot, target, self.release)
        self.assertFalse(target.exists())


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_schema_is_strict_and_image_must_be_immutable_and_sha_bound(self) -> None:
        self.assertEqual(release_manifest.validate_manifest(manifest()), manifest())
        for invalid in (
            {**manifest(), "extra": True},
            {**manifest(), "release_sha": "not-a-sha"},
            {**manifest(), "image": "newshub:latest"},
            {**manifest(), "image": "newshub:other"},
            {**manifest(), "migrations": [MIGRATIONS[1], MIGRATIONS[0]]},
            {**manifest(), "migrations": [MIGRATIONS[0], MIGRATIONS[0]]},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(release_manifest.ManifestError):
                    release_manifest.validate_manifest(invalid)

        digest_image = f"registry.example/newshub@sha256:{'c' * 64}"
        self.assertEqual(
            release_manifest.validate_manifest(manifest(digest_image))["image"], digest_image
        )
        ci_tag = f"newshub:ci-{RELEASE_SHA}"
        self.assertEqual(release_manifest.validate_manifest(manifest(ci_tag))["image"], ci_tag)
        with self.assertRaisesRegex(release_manifest.ManifestError, "suffix"):
            release_manifest.validate_image_reference("newshub:stable", RELEASE_SHA)

    def test_static_tree_digest_is_stable_and_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text("index", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("asset", encoding="utf-8")
            first = release_manifest.sha256_tree(root)
            self.assertEqual(first, release_manifest.sha256_tree(root))
            self.assertEqual(len(first), 64)
            (root / "bad-link").symlink_to(root / "index.html")
            with self.assertRaisesRegex(release_manifest.ManifestError, "symlink"):
                release_manifest.sha256_tree(root)

    def test_exported_static_release_hashes_only_its_hardlinked_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "releases" / RELEASE_SHA
            shared_assets = root / "assets"
            release_assets = release / "assets"
            release.mkdir(parents=True)
            shared_assets.mkdir()
            release_assets.mkdir()
            (release / "index.html").write_text("index", encoding="utf-8")
            shared_app = shared_assets / "app.js"
            shared_app.write_text("bundle", encoding="utf-8")
            os.link(shared_app, release_assets / "app.js")
            (shared_assets / "old-version-only.js").write_text("old", encoding="utf-8")
            image_dist = root / "image-dist"
            (image_dist / "assets").mkdir(parents=True)
            (image_dist / "index.html").write_text("index", encoding="utf-8")
            (image_dist / "assets" / "app.js").write_text("bundle", encoding="utf-8")
            expected = release_manifest.sha256_tree(image_dist)
            self.assertEqual(release_manifest.sha256_exported_release(release), expected)
            self.assertTrue(os.path.samefile(shared_app, release_assets / "app.js"))

            shared_app.write_text("tampered", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    release_manifest.main([
                        "validate-static", "--release", str(release), "--expected-sha", expected
                    ]),
                    2,
                )
            shared_app.write_text("bundle", encoding="utf-8")

            linked_asset = release_assets / "app.js"
            linked_asset.unlink()
            linked_asset.write_text("bundle", encoding="utf-8")
            with self.assertRaisesRegex(release_manifest.ManifestError, "hardlink"):
                release_manifest.sha256_exported_release(release)
            linked_asset.unlink()
            linked_asset.symlink_to(shared_app)
            with self.assertRaisesRegex(release_manifest.ManifestError, "symlink"):
                release_manifest.sha256_exported_release(release)

    def test_production_container_runbook_uses_the_maintenance_gate(self) -> None:
        document = (ROOT / "docs/deployment/production-containers.md").read_text(encoding="utf-8")
        self.assertIn("scripts/deploy/deploy.sh", document)
        self.assertIn("--current-manifest", document)
        self.assertIn("--backup-output", document)
        self.assertIn("--fresh", document)
        self.assertNotIn(
            "docker compose --env-file .env.production -f compose.prod.yaml up -d",
            document,
        )

    def test_describe_image_inspects_revision_and_nonroot_user_then_uses_network_none(self) -> None:
        image_json = json.dumps({"migrations": MIGRATIONS, "static_sha": "b" * 64})
        with patch.object(release_manifest, "_docker_text", side_effect=[RELEASE_SHA, "10001:10001", '{"channel_worker":true,"full_content_worker":true,"crawler_worker":true}']), patch.object(
            release_manifest.subprocess,
            "run",
            return_value=type("Result", (), {"stdout": image_json})(),
        ) as run:
            value = release_manifest.describe_image(f"newshub:{RELEASE_SHA}", RELEASE_SHA)
        self.assertEqual(value["migrations"], MIGRATIONS)
        self.assertEqual(value['capabilities'], {'full_content_worker': True, 'channel_worker': True, 'crawler_worker': True})
        command = run.call_args.args[0]
        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("--pull=never", command)
        self.assertFalse(any(arg == "-v" or arg == "--volume" for arg in command))
        self.assertTrue(any("SYNTHETIC" not in arg and "synthetic-key" in arg for arg in command))

    def test_manifest_output_is_private_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "release.json"
            release_manifest._write_new_json(path, manifest())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            original = path.read_bytes()
            with self.assertRaisesRegex(release_manifest.ManifestError, "already exists"):
                release_manifest._write_new_json(path, manifest())
            self.assertEqual(path.read_bytes(), original)


class CollectionAndWorkflowTests(unittest.TestCase):
    def test_release_dockerfile_persists_three_independent_download_caches(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        expected_mounts = {
            "newshub-rss-pip-v1": "target=/root/.cache/pip",
            "newshub-frontend-npm-v1": "target=/root/.npm",
            "newshub-runtime-torch-pip-v1": "target=/root/.cache/pip",
        }
        for cache_id, target in expected_mounts.items():
            mount = f"--mount=type=cache,id={cache_id},{target},sharing=locked"
            self.assertEqual(dockerfile.count(mount), 1, cache_id)
        self.assertEqual(len(expected_mounts), len(set(expected_mounts)))
        self.assertIn("AS rss-sync", dockerfile)
        self.assertIn("AS frontend-build", dockerfile)
        self.assertIn("ARG TORCH_VERSION=2.14.1+cpu", dockerfile)
        self.assertIn('"torch==${TORCH_VERSION}"', dockerfile)
        self.assertIn("-r /app/backend/requirements-rss.lock", dockerfile)
        self.assertIn("npm ci", dockerfile)

    def test_root_pytest_config_includes_api_root_and_unified_patterns(self) -> None:
        values: dict[str, str] = {}
        for line in (ROOT / "pytest.ini").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("["):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        self.assertEqual(values["python_files"], "test_*.py")
        self.assertEqual(values["testpaths"], "tests/ backend/api/tests/")

    def test_ci_is_read_only_token_scoped_and_runs_all_three_test_roots(self) -> None:
        workflow = yaml.load(
            (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        # Dual self-hosted Runner architecture: manual dispatch is allowed, but
        # never the privileged pull_request_target trigger.
        self.assertEqual(set(workflow["on"]), {"push", "pull_request", "workflow_dispatch"})
        self.assertNotIn("pull_request_target", workflow["on"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"changes", "dev-frontend", "dev-backend", "frontend", "backend-and-release-gates", "merge-gate"})
        # Docs-only and approved non-runtime metadata must skip the entire
        # automatic workflow, not merely schedule an empty routing job.
        push_ignore = workflow["on"]["push"]["paths-ignore"]
        self.assertEqual(push_ignore, workflow["on"]["pull_request"]["paths-ignore"])
        self.assertIn("docs/**", push_ignore)
        self.assertIn("frontend/README.md", push_ignore)
        self.assertIn(".github/ISSUE_TEMPLATE/**", push_ignore)
        self.assertNotIn(".github/**", push_ignore)
        self.assertNotIn("**/*.md", push_ignore)
        # Same-repo gate permits Draft's safe fast checks; full job access
        # requires Ready (non-Draft), main push or manual dispatch.
        router = jobs["changes"]
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", router["if"])
        self.assertNotIn("!github.event.pull_request.draft", router["if"])
        self.assertIn("converted_to_draft", workflow["on"]["pull_request"]["types"])
        self.assertIn("ready_for_review", workflow["on"]["pull_request"]["types"])
        for stage in ("dev-frontend", "dev-backend"):
            self.assertEqual(jobs[stage]["needs"], "changes")
            self.assertIn("github.event.pull_request.draft", jobs[stage]["if"])
        gate = jobs["merge-gate"]
        self.assertEqual(set(gate["needs"]), {"changes", "frontend", "backend-and-release-gates"})
        self.assertIn("always()", gate["if"])
        self.assertIn("!github.event.pull_request.draft", gate["if"])
        self.assertIn("true:success|false:skipped", gate["steps"][0]["run"])
        # A lone backend test change in a Draft PR must never schedule the
        # expensive release matrix or its frontend counterpart.
        self.assertIn("github.event.pull_request.draft", jobs["dev-backend"]["if"])
        self.assertIn("!github.event.pull_request.draft", jobs["backend-and-release-gates"]["if"])
        draft_runs = "\n".join(step.get("run", "") for step in jobs["dev-backend"]["steps"])
        for expensive in ("benchmark-xdist.sh", "local-domain-smoke.sh", "docker build"):
            self.assertNotIn(expensive, draft_runs)
        self.assertEqual(router["runs-on"], ["self-hosted", "linux", "x64", "newshub-frontend"])
        for name, scope in (("frontend", "frontend"), ("backend-and-release-gates", "backend")):
            job = jobs[name]
            self.assertEqual(job["needs"], "changes")
            self.assertIn("needs.changes.result == 'success'", job["if"])
            self.assertIn(f"needs.changes.outputs.{scope} == 'true'", job["if"])
            self.assertIn("github.event_name == 'workflow_dispatch'", job["if"])
            self.assertIn("!github.event.pull_request.draft", job["if"])
            self.assertIn("!cancelled()", job["if"])
        for name, job in jobs.items():
            if name == "merge-gate":
                self.assertFalse(any("uses" in step for step in job["steps"]))
                continue
            checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
            self.assertEqual(checkout["with"]["persist-credentials"], "false")
        frontend_job = jobs["frontend"]
        self.assertEqual(frontend_job["runs-on"], ["self-hosted", "linux", "x64", "newshub-frontend"])
        frontend_runs = "\n".join(step.get("run", "") for step in frontend_job["steps"])
        self.assertIn('test "$(node -p \'process.versions.node.split(".")[0]\')" = 22', frontend_runs)
        self.assertIn("test ! -S /ci-docker/docker.sock", frontend_runs)
        self.assertIn("bash ops/ci/install-frontend-deps.sh", frontend_runs)
        frontend_install = (ROOT / "ops/ci/install-frontend-deps.sh").read_text(encoding="utf-8")
        self.assertIn("npm ci", frontend_install)
        for command in ("npm run typecheck", "npm run lint", "npm run test:run", "npm run build"):
            self.assertIn(command, frontend_runs)
        self.assertLess(frontend_runs.index("install-frontend-deps.sh"), frontend_runs.index("npm run typecheck"))
        backend_job = jobs["backend-and-release-gates"]
        self.assertEqual(backend_job["runs-on"], ["self-hosted", "linux", "x64", "newshub-ci"])
        self.assertEqual(backend_job["env"]["RUN_MAIN"], "true")
        self.assertEqual(backend_job["env"]["PYTHONPATH"], "backend")
        runs = "\n".join(step.get("run", "") for step in backend_job["steps"])
        self.assertIn("= 3.12", runs)
        self.assertIn('test "$DOCKER_HOST" = unix:///ci-docker/docker.sock', runs)
        self.assertLess(runs.index("bash ops/ci/install-backend-deps.sh"), runs.index("pytest -q"))
        backend_install = (ROOT / "ops/ci/install-backend-deps.sh").read_text(encoding="utf-8")
        self.assertIn("2.14.1+cpu", backend_install)
        self.assertLess(backend_install.index('"torch==$TORCH_PIN"'), backend_install.index('-r "$LOCK"'))
        # The default workflow invokes the pinned hybrid matrix indirectly;
        # keep asserting all three roots instead of requiring inline pytest.
        self.assertIn("bash ops/ci/benchmark-xdist.sh", runs)
        hybrid = (ROOT / "ops/ci/benchmark-xdist.sh").read_text(encoding="utf-8")
        self.assertIn("tests/ backend/api/tests/ scripts/deploy/tests/", hybrid)
        self.assertIn("SERIAL_FILES=(", hybrid)
        self.assertIn('--ignore="$file"', hybrid)
        self.assertIn("ops/ci/xdist_summary.py", hybrid)
        full_step = next(s for s in backend_job["steps"] if s["name"] == "Run backend and offline deployment tests")
        self.assertEqual(full_step["env"]["CI_XDIST_REPEATS"], "1")
        self.assertEqual(full_step["env"]["NEWSHUB_TEST_DOCKER_CONTEXT"], "1")
        self.assertIn('python3 ops/ci/build-production.py --sha "$RELEASE_SHA" --image "$NEWSHUB_IMAGE"', runs)
        build_command = (ROOT / 'ops/ci/build-production.py').read_text()
        self.assertIn('"--target", "production"', build_command)
        self.assertIn('"--build-arg", f"RELEASE_SHA={args.sha}"', build_command)
        self.assertIn('"--tag", args.image', build_command)
        self.assertIn("local-domain-smoke.sh --execute", runs)
        self.assertIn(
            "nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94",
            runs,
        )
        self.assertNotIn("nginx:stable-alpine", runs)
        uses = [step["uses"] for job in jobs.values() for step in job["steps"] if "uses" in step]
        self.assertEqual(set(uses), {"actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"})
        self.assertFalse(any("secrets." in value for value in _walk_strings(workflow)))


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, nested in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_strings(nested)


if __name__ == "__main__":
    unittest.main()
