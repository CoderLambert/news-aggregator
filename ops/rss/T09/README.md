# T09 isolated engine synchronization proof

Run from the task checkout with Docker on a local Unix socket:

```sh
docker build --target rss-sync -t newshub-rss-t09:isolated-check .
python ops/rss/T09/verify_live.py --image newshub-rss-t09:isolated-check --output ops/rss/T09/evidence.json
```

The harness reuses **only** the pinned T00 Compose file. It requires a new random `newshub-rss-t09-*` project, checks that no resources already exist for that project, publishes the engine on a random loopback port, creates its own non-admin collector, and always removes that project's containers/networks/volumes. The SQLite worker database and PostgreSQL are disposable tmpfs. Temporary credentials and a synthetic publisher CA are generated locally and never included in evidence. Private fetching is enabled only in this isolated publisher fixture.

`live_driver.py` runs inside the actual lightweight image. It exercises real Miniflux registration and ordered pages, commits an article and kills the child before advancing the cursor, obtains and discards a real response, and holds a separate SQLite writer to cause DB busy. The harness stops only its own engine to verify network failure leaves progress untouched. Synthetic PostgreSQL changes reintroduce an already allocated low ID, update old content, insert a high ID with a 1990 publication date, and finally delete retained engine rows; full reconciliation finds the changes while preserving all local articles. The final daemon check requires `sync_worker` and actual `sync_ready=true`.

The injected process exit is after a committed write; lease expiration is accelerated explicitly in the disposable SQLite fixture. Response loss is a deliberate discard after a successful real GET, not a claim of TCP packet-level fault injection. The low-ID/cleanup SQL operates exclusively on this fixture's PostgreSQL, never a user or production database. This proof does not cover production backup, final release migrations, throughput, or publisher quality.
