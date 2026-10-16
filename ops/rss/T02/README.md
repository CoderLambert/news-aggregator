# Lightweight RSS runtime

Build only the `rss-sync` target:

```sh
docker build --target rss-sync -t newshub-rss-t02:isolated-check .
python3 ops/rss/T02/verify_isolated.py \
  --image newshub-rss-t02:isolated-check --output /tmp/rss-t02-evidence.json
```

The verifier creates a random `newshub-rss-t02-<12 hex>` project and refuses remote
Docker daemons or existing project resources. It generates only synthetic secrets
in a temporary protected directory and uses newly allocated named volumes. The
base migration service is overridden to the lightweight image and `migrate
--skip-checks`, targeting only the new temporary SQLite volume. Only `rss-sync`,
`miniflux`, `rss-db` and that migration job start. No existing application or user
database is inspected or started. Finally, all project containers/networks/volumes
are removed; the test image and build cache remain for review.

The actual image probe verifies CPython3.12, UID10001, complete ORM migrations,
module/binary absence and a MetaPath trap for attempted embedding/URL imports.
It verifies the dedicated non-admin token from inside rss-sync, all three health
checks, and rejection of a second process via the SQLite-directory flock. The
checked-in evidence records the image ID and schema actually tested; rebuild on
the final integrated SHA before treating it as release evidence.

## Optional deployment configuration

`compose.rss.prod.yaml` is an explicit overlay/profile; it does not replace the
existing app host network/BYOK setup, legacy crawler, indexer, or optional workspace
channel-worker. It does not activate automatically. Configuration can be reviewed
with an explicit protected env file:

```sh
docker compose --env-file /absolute/protected/rss.env \
  -f compose.prod.yaml -f compose.workspace.prod.yaml -f compose.rss.prod.yaml \
  --profile rss config
```

This command is a configuration review, not production execution authorization.
The existing deploy.sh does not automatically manage the RSS overlay. Once RSS
writers are activated, T03's explicit manifest/writer-aware operations must manage
rss-sync and Miniflux when stopping writers or pairing SQLite/PostgreSQL backups.
Do not infer a two-database backup/restore guarantee from the old deployment flow.

Supply an immutable separately built `NEWSHUB_RSS_IMAGE`, the existing production
Django/proxy settings, and these fixed server-side values:

| Variable | Meaning |
| --- | --- |
| RSS_ENGINE_INSTANCE_UUID | Stable engine identity persisted in the protected manifest; never regenerated on restart |
| RSS_ENGINE_ACCOUNT_ID | Dedicated non-admin collector account, verified against the token's `/v1/me` |
| RSS_ENGINE_BASE_URL | In rss-sync, fixed `http://miniflux:8080`; a host process can use `http://127.0.0.1:${RSS_ENGINE_PORT}` |
| RSS_ENGINE_TOKEN_FILE | On host, protected token secret source; in rss-sync, `/run/secrets/rss_engine_token` |
| RSS_ENGINE_PORT | Miniflux loopback binding, default18080; isolated verifier uses0 for an allocated port |
| RSS_PG_PASSWORD_FILE | Dedicated PG password file |
| RSS_DATABASE_URL_FILE | Matching `postgres://miniflux:<password>@rss-db/miniflux?sslmode=disable` secret file |
| RSS_ENGINE_ADMIN_PASSWORD_FILE | Separate bootstrap admin password; never mounted in rss-sync |

Create the collector account/token through the operator-controlled private engine
interface before enabling real synchronization. Admin credentials and collector
credentials are separate. The test verifier provisions only its synthetic account
and must not be repurposed as a production account bootstrap. Secret files must be
protected on the host while readable by their intended container UID; local Compose
file secrets are read-only mounts and do not universally implement uid/gid remapping.
No broad app env_file, BYOK project key, model cache, media, or PG/admin secret is
mounted in rss-sync. PG has no host ports and only Miniflux joins its internal
network; Miniflux API binds loopback and its controlled bridge network. Publisher
fetches retain `FETCHER_ALLOW_PRIVATE_NETWORKS=0`, read/unread cleanup is explicit90
days, and fetcher debug is disabled.

## Runtime interface and limits

`NEWSHUB_RUNTIME_ROLE=rss_sync` exits ApiConfig.ready before embedding preload.
`manage.py rss_runtime --once` checks ORM only, without URL checks. With no mode
flag, one process holds `.rss-sync.lock` beside the SQLite database and writes a
heartbeat every20seconds. `--healthcheck` checks schema/ORM and a recent heartbeat.
SIGTERM/SIGINT stop the shell and remove its heartbeat.

Every status explicitly says `mode=orm_shell, sync_ready=false,
worker_integrated=false`. Runtime health means only that the shell is alive; it
does not mean a valid engine configuration has been verified, requests are being
processed, or synchronization is ready. T08/T09 must replace the shell with the
single worker, validate the four fixed engine configuration fields, preserve the
lock/health semantics, cap API concurrency at2, and serialize short SQLite writes.
This task performs no engine requests in the daemon and creates no operation queue
or extra scheduler. Directory daily scheduling remains T09 integration work.

The fixed runtime dependency lock is independent of backend/requirements.txt and
includes SDK1.1.6 and T06's conversion pins. No Torch, embedding package, Scrapy,
feedparser, browser or publisher-page extractor is installed. Existing full app
targets and development default stay as before. T00's API/cleanup/refetch evidence
is reused; production SSRF/gateway, full application live startup and resource-load
gates remain separate from this isolated runtime experiment.
