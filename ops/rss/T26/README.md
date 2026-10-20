# T26 synthetic compatibility candidate (NOT SEALED)

These tools use only fresh `/tmp/newshub-rss-t26-*` artifacts and newly named local
Docker projects. They never accept a production dataset, infer a user database,
reverse a migration, or declare a synthetic result a production compatibility seal.
The real authorized backup-copy rehearsal remains outstanding.

## Application/data rehearsal

```sh
python ops/rss/T26/run.py \
  --output /tmp/newshub-rss-t26-UNIQUE \
  --dependency-site /tmp/newshub-rss-coordinator-venv/lib/python3.12/site-packages \
  --full-app-base newshub:TESTED-FULL-SHA \
  --rollback-candidate newshub-rss-t26:EXISTING-COMPATIBLE-CANDIDATE
```

Omit `--rollback-candidate` for an initial same-image smoke test only. A final
candidate comparison must identify two tested SHA/image IDs. `--candidate` reuses
an existing explicitly named T26 image; otherwise an offline image is built using
`Dockerfile.candidate`. `--full-app-base` is required when building; there is no implicit old collector
cache. `--rss-dep-base` selects the local RSS cache (default
`newshub-rss-t09:isolated-check`). Existing `--candidate` images do not inspect
unused build caches.
Both base IDs/digests/revisions are recorded and tags are checked again after build.
The full application cache retains AI packages and its built frontend;
current backend source and pinned RSS dependencies overlay it. After T31 the
selected base must already omit retired collector packages. The probe refuses
collector package/code mismatches; it does not reinstall removed writers. Installed
`listparser==0.20` and `defusedxml==0.7.1` are copied read-only from the explicit
site path after validating METADATA against the repository pins. No package
installation modifies the shared virtualenv. This cached dependency/frontend build
is a **candidate**, not an exact production release Dockerfile build.

The harness seeds historical ORM models at0051, then migrates forward to every
current migration leaf. It compares the old columns of every table (PK/FK, counts,
exact source/translation bytes included), checks FK/integrity and0059 exact legacy
translation binding. It exercises the minimal shared source group, old ingestion
and full-content worker rejection on transition images (or confirms their code
is absent on retired images), ownership ABA, late translation history,
available content, personal paused ACL, read states, subscription/OPML durable
intents and owner-scoped import progress. The source-switch policy receipt is
explicitly synthetic and makes no HTTP claim.

The same database is then opened by current→compatible→current full application
images. Each runs actual container-loopback WSGI HTTP detail/ACL checks and DRF
subscription/OPML/read-state reads. Full table fingerprints must remain identical.
Only the test harness is mounted read-only across the images; application imports
come from each image. No migrations, DB restore, or data rollback occur during
this image roundtrip. The web engine identity is a fixed synthetic instance/account
matching the fixture manifest; no collector/admin token is mounted. Control tests
enqueue only and run with network disabled.

All temporary app containers have exact names/labels and are removed in `finally`,
including client timeout. The output directory is intentionally retained for
inspection. Candidate Docker images are retained locally by immutable IDs and
unique T26 tags; no registry push occurs.

## Paired disaster recovery and restored engine reconciliation

```sh
python ops/rss/T26/paired.py \
  --dataset /tmp/newshub-rss-t26-UNIQUE \
  --output /tmp/newshub-rss-t26-UNIQUE-paired.json \
  --python /tmp/newshub-rss-coordinator-venv/bin/python
```

This creates a **separate synthetic target copy**, real pinned Miniflux/PostgreSQL,
a local HTTPS publisher and a full app process. Explicit synthetic feed/entry
identity alignment occurs before the backup restore point; it is fixture setup,
not an operational rebinding procedure. T03 `scripts/rss/recovery.py` performs
all target/quiescence/schema/mapping checks, SQLite online snapshots, PG dumps,
prior-backup gates and restores. This harness implements none of those primitives.
It checks live-writer refusal, wrong-instance refusal without writes, restoration
of all relationship counts/logical hashes, then uses the actual full app to read
restored available/private content. T09 subsequently performs real incremental
and full reconciliation against the restored engine. That approved reconciliation
changes data after the restore comparison; it is not hidden restore drift.

Release capabilities are read from the actual application image and recorded in
strict v4, with v3 still supported by recovery. They are not hard-coded to restore
retired workers. The application rollback wrapper explicitly uses
`--leave-rss-stopped`: RSS must already be stopped, and the wrapper cannot
silently stop a running RSS process or resume it before reconciliation.

The restore points in evidence explicitly exclude deliberately committed later
SQLite and PG changes. Helpers have exact T26 names and a separate rehearsal label
so they cannot contaminate the T03 project inventory. Finally blocks remove that
project's containers, networks, volumes and temporary secrets/backups. The temporary application processes run as the synthetic bind-mount owner,
including restored 0600 files and the synthetic token. This does not change image
users or widen protected file permissions. PostgreSQL readiness checks TCP rather
than its Unix-only bootstrap server before Miniflux is started. Only aggregate
evidence survives. No real provider credentials or paid AI services are used.

## Actual deployment wrapper chain is a separate gate

```sh
python ops/rss/T26/rollback_preflight.py \
  --output /tmp/newshub-rss-t26-UNIQUE-preflight.json
```

The image roundtrip does **not** claim execution of
`recovery.py rollback → scripts/deploy/rollback.sh`. On the recorded host UID1000
cannot traverse the named-volume Source under `/var/lib/docker/volumes`. The real
T03 target validator rejects that inaccessible parent. Mounting it in a running
helper is also correctly detectable by the unchanged quiescence guard. The
preflight records this actual access rejection and exact Docker volume-user list;
it does not pretend that the complete rollback command ran. No parent-directory
mount, permission change, sudo or nsenter bypass is attempted. A host runner with
authorized direct access to the exact named-volume Source is required. Port9527
was free at preflight; it must be checked again before any future complete chain.
The explicit rollback env file must preserve engine instance/account identity
matching the manifest, while all collectors remain stopped.

## Focused verification

```sh
RSS_TEST_ALLOW_LIVE=1 RUN_MAIN=true \
  DJANGO_DB_PATH=/tmp/newshub-rss-t26-tests.sqlite3 PYTHONPATH=backend \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  tests/rss_engine_contract/test_migration_rehearsal.py
```

This checks fresh-output refusal plus actual failed-exit/timeout container cleanup.
The larger staged scripts above are the migration/restore evidence, not mocked
pytest substitutes. T03's existing `verify_isolated.py` also ran with0059 and
proved overwrite replay, fresh-target recovery and schema/hash/prior refusals.
