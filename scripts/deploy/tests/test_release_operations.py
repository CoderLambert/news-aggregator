from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.deploy import release_manifest, sqlite_snapshot


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
            with patch.object(sqlite_snapshot.time, "monotonic", side_effect=advancing_clock):
                with patch.object(
                    sqlite_snapshot,
                    "_online_backup",
                    side_effect=lambda source, destination: real_online_backup(
                        source, destination, timeout_seconds=0.5
                    ),
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

    def test_exported_static_release_matches_image_tree_through_shared_assets_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "releases" / RELEASE_SHA
            assets = root / "assets"
            release.mkdir(parents=True)
            assets.mkdir()
            (release / "index.html").write_text("index", encoding="utf-8")
            (assets / "app.js").write_text("bundle", encoding="utf-8")
            (release / "assets").symlink_to("../../assets")
            image_dist = root / "image-dist"
            (image_dist / "assets").mkdir(parents=True)
            (image_dist / "index.html").write_text("index", encoding="utf-8")
            (image_dist / "assets" / "app.js").write_text("bundle", encoding="utf-8")
            expected = release_manifest.sha256_tree(image_dist)
            self.assertEqual(release_manifest.sha256_exported_release(release), expected)

    def test_describe_image_inspects_revision_and_nonroot_user_then_uses_network_none(self) -> None:
        image_json = json.dumps({"migrations": MIGRATIONS, "static_sha": "b" * 64})
        with patch.object(release_manifest, "_docker_text", side_effect=[RELEASE_SHA, "10001:10001"]), patch.object(
            release_manifest.subprocess,
            "run",
            return_value=type("Result", (), {"stdout": image_json})(),
        ) as run:
            value = release_manifest.describe_image(f"newshub:{RELEASE_SHA}", RELEASE_SHA)
        self.assertEqual(value["migrations"], MIGRATIONS)
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
        self.assertEqual(set(workflow["on"]), {"push", "pull_request"})
        self.assertNotIn("pull_request_target", workflow["on"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"frontend", "backend-and-release-gates"})
        frontend_job = jobs["frontend"]
        node_setup = next(step for step in frontend_job["steps"] if step.get("uses", "").startswith("actions/setup-node@"))
        self.assertEqual(node_setup["with"]["node-version"], "22")
        frontend_runs = "\n".join(step.get("run", "") for step in frontend_job["steps"])
        for command in ("npm ci", "npm run typecheck", "npm run lint", "npm run test:run", "npm run build"):
            self.assertIn(command, frontend_runs)
        backend_job = jobs["backend-and-release-gates"]
        self.assertEqual(backend_job["env"]["RUN_MAIN"], "true")
        self.assertEqual(backend_job["env"]["PYTHONPATH"], "backend:crawler")
        python_setup = next(step for step in backend_job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
        self.assertEqual(python_setup["with"]["python-version"], "3.12")
        runs = "\n".join(step.get("run", "") for step in backend_job["steps"])
        self.assertLess(runs.index("torch==2.14.1+cpu"), runs.index("pip install -r backend/requirements.txt"))
        self.assertIn("tests/ backend/api/tests/ scripts/deploy/tests/", runs)
        self.assertIn("--target production", runs)
        self.assertIn("local-domain-smoke.sh --execute", runs)
        self.assertIn(
            "nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94",
            runs,
        )
        self.assertNotIn("nginx:stable-alpine", runs)
        uses = [step["uses"] for job in jobs.values() for step in job["steps"] if "uses" in step]
        self.assertEqual(
            set(uses),
            {
                "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
                "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
            },
        )
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
