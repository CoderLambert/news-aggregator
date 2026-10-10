# NewsHub release and recovery gates

This runbook describes the local release tooling. A successful local run does not establish public DNS, certificate issuance, server access, firewall policy, or production readiness. Those checks stay `NOT_RUN` until an operator carries out the separately authorized site change.

## Required evidence before a release

Build one non-root production image from the exact 40-character source revision. Keep the image local or use an immutable SHA tag/digest; the tooling never pulls it. Generate a strict release manifest with `scripts/deploy/release_manifest.py describe`. The manifest records the image revision, every on-disk Django migration, and the frontend static tree digest. Do not edit those values by hand.

The CI workflow runs the frontend checks, collects and runs all three backend test roots, runs the production Django check with synthetic values, exercises offline deployment helpers, builds the production Docker target, and runs the isolated G1 local-domain browser check. CI has read-only repository permissions and does not deploy, publish an image, use provider credentials, or modify public DNS. A skipped tool or failed required command is not a pass.

The root pytest configuration uses `test_*.py` and includes `tests/` plus `backend/api/tests/`. For release evidence, explicitly collect all roots so API tests cannot disappear from a green result:

```sh
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest --collect-only -q tests/ backend/api/tests/ scripts/deploy/tests/
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q tests/ backend/api/tests/ scripts/deploy/tests/
```

Never place a real `.env` or provider key in CI. Production checks use a synthetic Django secret and loopback proxy value. The normal frontend build and static export must use the same release SHA as the production image.

## Maintenance-window deployment

Use a dedicated Compose project name and its matching `<project>_db-data` volume. Pass an absolute, regular `--env-file` containing the explicit deployment configuration; do not source it in a shell or print it. The configured image must already exist locally and carry the requested revision label. Keep the static root and SQLite snapshot outside the source checkout. A snapshot contains user data and must have access limited to the operator; encryption keys are stored and backed up separately.

For an existing database, supply both manifests: `--current-manifest` describes the currently installed app/image and database schema, while `--manifest` describes the target image. Supply a new absolute `--backup-output` and the exact database volume. First preview the operation:

```sh
scripts/deploy/deploy.sh \
  --env-file /secure/path/newshub.env \
  --project newshub-site \
  --sha 0123456789abcdef0123456789abcdef01234567 \
  --image newshub:0123456789abcdef0123456789abcdef01234567 \
  --root /srv/newshub \
  --manifest /secure/path/target-release.json \
  --current-manifest /secure/path/current-release.json \
  --db-volume newshub-site_db-data \
  --backup-output /secure/backups/newshub-before-0123456789abcdef0123456789abcdef01234567.sqlite3
```

Only after reviewing that plan should an operator add `--execute`. The command verifies the current app image and database-volume mount, stops only this project's crawler, indexer, and app, confirms no running container still uses the database volume, and creates a new SQLite online-backup snapshot against the current image manifest. It independently validates the snapshot before running the target migration once. It starts the app and waits for its readiness health check, starts the workers and waits for their health checks, then exports the matching static release and atomically switches `current`.

Any failure after the maintenance window starts leaves this project's app and workers stopped. It preserves the snapshot and the previous static `current`; it does not restart an old image or attempt a migration downgrade. The migration lock prevents concurrent migrations, while stopping the app and workers prevents old code from reading the changing schema. An external process that uses the volume must also be stopped before the command proceeds.

For the first empty database only, use `--fresh` in place of `--current-manifest`, `--backup-output`, and the current-app assumptions. The project must have no existing app or worker containers, and the selected volume must not contain `db.sqlite3`. Existing files are never treated as a fresh database.

## Rollback and data restore

Code rollback is permitted only when the stopped database's exact `django_migrations` app/name set matches the target old manifest. `rollback.sh` never changes the database. It stops only the named project's app/workers, checks the database volume has no other running user, starts and health-checks the target image, then switches `current` to an already exported and manifest-verified release. If the schema differs, it leaves the project stopped; a `--compatible` flag cannot override that decision.

When migrations changed the schema, restore the verified pre-migration snapshot before starting old code. Stop all writers, make and verify a separate snapshot of the current database state, then use `restore.sh` with `--replace --writers-stopped --prior-backup` and the matching old release manifest. The restore helper takes the same migration file lock, stages and validates the database, and atomically replaces it only after validation. Never remove the database volume, delete WAL/SHM files while a writer may be active, copy only the SQLite main file, or use `docker compose down -v` as a recovery step.

The SQLite online-backup API reads the source in read-only mode and includes committed WAL content while excluding an open uncommitted transaction. Backup artifacts and their manifests are published without overwriting existing files and with mode `0600`. Run the documented isolated restore rehearsal before relying on a backup for recovery. A missing encryption key can make encrypted provider tokens unrecoverable; the key is not part of a database snapshot.

## Runtime monitoring gates

Before opening external traffic, record the operator-approved alert thresholds and evidence source for each item below. The repository cannot infer safe capacity, budget, or alert limits from a healthy HTTP probe.

- Certificate expiry, renewal timer status, and a successful renewal dry check; never run Certbot or alter a system Nginx configuration as part of these local scripts.
- Readiness, HTTP 5xx rate, latency, SSE connections and disconnects, and the ability to keep article and login requests responsive while streams are active.
- Crawler and indexer health checks, last successful heartbeat, backlog age, and failure counts.
- Free disk space and growth for SQLite/WAL, Chroma, TTS/model caches, logs, static releases, and shared hashed assets.
- Snapshot age, off-host retention, restricted access, and a successful restore rehearsal; record the separately protected encryption-key recovery path.
- AI requests, provider identity, per-user and global spend, limits, and alerts. Keep every AI/provider flag disabled until ownership, hard budgets, concurrency limits, and failure accounting are implemented and reviewed. Never route a public request to a user's paid account as a fallback.
- Log retention, access control, and redaction of credentials, cookies, authorization headers, and private article/chat content.

Missing threshold, monitoring access, backup evidence, or recovery rehearsal means the corresponding release gate remains open. A local HTTPS/browser pass verifies the isolated domain path only; it does not replace these operational gates or the later public DNS/TLS/network acceptance.
