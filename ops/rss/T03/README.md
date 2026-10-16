# T03 paired recovery tools

`scripts/rss/recovery.py` is a thin wrapper around the existing strict schema3
`release_manifest.py`, SQLite online backup/restore primitives, Docker's official
PG `pg_dump`/`pg_restore`, and the existing application `rollback.sh`. It adds no
approval files or deployment service. New start/update orchestration is outside
this recovery command; existing deployment entry points remain available, but RSS
writers must be quiesced as part of the coordinated release window.

## Explicit targets and inventory

Every invocation requires `--environment isolated|production --manifest ABSOLUTE
--target-project NAME`. All mutations additionally require `--execute`; backup,
restore and rollback otherwise validate local inputs and print a JSON dry-run.
Dry-run does not inspect Docker or prove live quiescence/schema. The read-only
status/install-check/diagnose commands inspect the target inventory without stop,
start, SQL writes or credential output; they do not claim sync readiness.

The RSS inventory schema1 embeds an **unchanged, strict release schema3** object.
This is distinct from changing the existing release-manifest schema. Unknown
fields/versions are rejected. The generated isolated manifest in
`verify_isolated.py` is a runnable example of all required fields:

- `project`, `environment`, `release`: explicit target, immutable release SHA/image,
  complete applied migration set, static hash and current worker capabilities.
- `sqlite.path`: absolute real host path to the SQLite file. For a Docker named
  db-data volume this must be its inspected host Source plus the database filename;
  it cannot name an unrelated copy. Every writer mount must match its parent.
  The operator must already have access to that explicit path; the tool does not
  discover/read user data directories or infer a Docker volume mount point.
- `postgres`: full64hex container_id, fixed image digest, database, user and volume.
  Container project/service labels, exact volume ownership and no PG published
  ports are checked. An unexpected running volume user is refused.
- `engine`: full container identity/digest, persisted instance_uuid, fixed non-admin
  account_id/username and exact Miniflux database schema. The engine DATABASE_URL
  must point to that rss-db/database/user. DATABASE_URL_FILE must be a named
  protected secret reference. UUID comes from the protected inventory/SQLite;
  Miniflux numeric IDs do not establish a rebuilt engine's identity.
- `writers.roles`: all six keys app/crawler/indexer/channel-worker/full-content/
  rss-sync, each an explicit list of full container IDs, including empty lists.
  `other_containers` explicitly lists non-writer service→ID entries. Extra project
  containers, wrong mounts/roles/images and writable DB mounts in non-writers fail.
- `writers.host_processes`: explicit PID/role/start_ticks/cmdline_sha256 inventory.
  A reused/mismatching PID is never signalled. `schedulers` lists explicit systemd
  timer/service units and user/system scope; both timer and spawned service must
  be inventoried when relevant. Active units fail until stopped. Unsupported cron
  or external supervisors must be disabled/verified separately before declaring
  `host_inventory_complete:true`; an environment name is not such evidence.
- `secret_refs`: name→absolute file paths. These selected files are copied into
  pair/secrets with0600 permissions under0700 directories, hashed but never
  printed. The pair contains database credential hashes and protected secrets:
  store it in protected/encrypted backup storage, never source control. Secret
  restoration is separate and explicit; the CLI refuses differing/missing target
  secret references instead of overwriting deployment credentials automatically.
- `rollback`: null unless a compatibility target is configured. Otherwise contains
  target_release, compatibility_evidence/evidence_sha256, env_file, static_root,
  db_volume and worker_services. Evidence schema1 binds the complete target release,
  rss_compatible=true and production_sealed. Production requires a real T26 seal;
  a synthetic assertion is not production evidence. Allowed workers are indexer
  and, only when supported, channel-worker. Legacy and RSS collectors stay stopped.

The inventory must be complete, operator-controlled and protected. A manifest is
not an authenticity signature or proof that an unlisted host writer does not
exist. These tools do not replace process/scheduler discovery in the maintenance
window, approval of the exact environment or the T26 compatibility review.

## Backup and disaster restore

```sh
python3 scripts/rss/recovery.py backup --environment isolated \
  --manifest /absolute/target.json --target-project newshub-rss-example \
  --output /absolute/backups/pair-1
# Add --execute --stop-writers only for the explicitly inventoried target.

python3 scripts/rss/recovery.py restore --environment isolated \
  --manifest /absolute/target.json --target-project newshub-rss-example \
  --source /absolute/backups/pair-1 --replace --prior-backup /absolute/backups/prior
# A fresh, explicitly empty PG database and absent SQLite instead use --fresh,
# with no --replace/prior. Add --execute to perform either restore.
```

Backup checks the complete target allowlist **before** stopping anything. With
`--stop-writers`, it stops only listed schedulers/PIDs/containers plus Miniflux;
otherwise any live writer fails. PG stays running for dump/restore. All other PG
client sessions must be absent. SQLite is captured using its online backup API,
including committed WAL, never by copying only its live main file.

`pair.json` is published last in a newly reserved0700 directory. It binds a UUID,
two recorded UTC restore points, strict release/schema/engine identity, exact file
hashes (including the existing SQLite sidecar), SQLite/PG logical content hashes,
mapping hash and protected secret hashes. An incomplete directory is not a valid
pair. PostgreSQL table rows and sequence positions enter the logical fingerprint;
FK checks and feed/entry/account/URL joins verify identity. Locally retained entry
maps whose entries have expired from Miniflux are counted, never deleted or guessed.

Overwrite requires an intact paired prior backup matching **both current target
databases**. A corrupt current database cannot satisfy that gate: preserve it and
restore to separate explicit fresh targets instead. Fresh restore refuses any
SQLite file/sidecars or any public PG table. There is no cross-database atomic
transaction: PG restores inside its own transaction, then existing atomic SQLite
replacement runs. A later failure leaves every writer stopped and the prior pair
available for diagnosis/recovery; the tool never starts services after restore.
The reported restore points explicitly define post-backup data loss/RPO.

For ordinary application rollback use action `rollback --prior-backup PATH`.
It validates compatible exact-schema image evidence, verifies a current safety
pair, stops writers, and delegates only the application/static switch to the
existing rollback script. **It never calls either database restore.** The new
`rollback.sh --worker-services CSV` option selects a capability-checked subset;
empty means app only. Existing non-RSS default behavior is unchanged. After an
application switch, further RSS activation requires the coordinated verification.
The wrapper does not impose its ordinary180s subprocess timeout on rollback.sh:
that script owns its300s-per-service readiness and fail-closed signal/exit traps.
A shorter outer timeout would kill its shell and bypass that cleanup.

## Reproduction and limits

```sh
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-t03-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  scripts/deploy/tests/test_rss_backup_restore.py \
  scripts/deploy/tests/test_release_operations.py \
  scripts/deploy/tests/test_full_content_release.py
python3 ops/rss/T03/verify_isolated.py \
  --python /tmp/newshub-rss-coordinator-venv/bin/python \
  --output /tmp/t03-evidence.json
```

The real experiment creates its own random newshub-rss-t03-* project, named PG
volume, loopback API port and temporary SQLite. Actual Miniflux2.3.3 creates the
collector/feed/entries; PG17.6 custom archives and the complete Django schema
through0058 are restored twice and into fresh targets. Six **synthetic sleep
writer containers** exercise the role/stop inventory, not actual app behavior.
The fixture is synthetic and private fetch is allowed only in this experiment;
it is not public HTTPS/SSRF evidence. The live account/mapping/foreign-key and
user relationship checks are real; secret-file permissions/copy and application
rollback command behavior have separate unit/subprocess evidence.

The experiment retains only aggregate evidence.json in the repository. Databases,
archives, secret material, test containers, volume/network and temporary files are
removed. Production data, live app image/static rollback, real host scheduler/PID
termination and compatibility/ACL checks remain NOT_RUN. This evidence ends at
0058; the later0059 data migration and final release image must enter T26's full
schema rehearsal/seal. No migration subset is accepted as compatible. Large
production databases and restore time/RPO budgets need that measured rehearsal;
the current logical fingerprint queries buffer per-table results.
