# T08 persistent control worker

This adds six fixed intents to FeedOperation; it is not a publisher fetcher or a
generic task/HTTP service. HTTP authorization, CSRF, quotas and subscription/group
transactions remain T11/T17/T19 responsibilities. No schema or shared dependency
changes are required.

## Service interfaces

- `canonicalize_feed_url(value)`: public HTTPS syntax, no DNS request; rejects
  userinfo, private literal hosts and exact credential query keys. Host uses
  lowercase/IDNA, default443 and fragment are removed; business query bytes, path
  case/trailing slash and other HTTPS ports are retained.
- `get_or_create_binding(instance_uuid, account_id, feed_url, desired_mode='feed')`
  returns the unique FeedBinding; incompatible shared modes raise policy_conflict.
- `enqueue_operation(kind, actor=..., dedupe_key=..., binding=None, entry=None,
  source_id=None, url=None)` returns a FeedOperation model. Idempotency is per actor;
  a conflicting request raises OperationError('idempotency_conflict'). No network
  occurs here. Actor=None is a trusted internal system intent, never a browser user.
- `reconcile_binding(binding_id)` runs after subscription/link changes in the same
  short caller transaction. An enabled link with a miniflux-owned source and a
  subscription, or an editorial_pin on a miniflux-owned source, keeps collection
  enabled. Pins remain independent of link.enabled, but legacy/paused owners
  cannot start collection through a prestaged pin. Last-reference
  removal pauses immediately, advances policy and queues convergence; no history
  or engine feed is deleted.
- `change_policy(binding_id, expected_policy_version=..., desired_mode=...,
  actor=None, dedupe_key=None)` advances policy and pauses before queueing. It
  cancels old pending repairs. Only confirmed engine policy advances applied_version.
- `get_operation_for_actor(actor, operation_id)` returns id/kind/state/result/attempts
  for that actor only, including an additional result whitelist; cross-user/system
  operations are not_found. `cancel_operation(actor, id)` fences the old lease; a
  cancelled running mutation remains visibly cancelled while recovery reconciles it.

Source/subscription writers should acquire/create the binding before other reads
in their SQLite transaction. Functions write before reading rows to avoid SQLite
read-to-write lock upgrades; bounded retry handles standalone SQLite contention,
not an arbitrary caller's already-open failed transaction. T19's fixed
safe_input.subscription payload/request_hash is preserved and ignored by register
execution. Authorization is not inferred from the shared binding or operation ID.

## Execution and T09 handoff

`ControlWorker(config).tick()` performs claim/completion writes on its caller thread
and places only network work in one control slot. `submit_short_read(callback)`
reserves one independent adapter/read slot for T09; it returns None while occupied
and never builds a backlog. T09 must consume that future and commit its data/cursor
on the main thread. Each slot creates its own fixed-account adapter/session; at
most two API calls are in flight in this single process. `run_once()` is the
synchronous test/explicit one-operation entry point and rejects caller transactions.

Claims use conditional state/token/epoch updates, not select_for_update (ignored
by SQLite). Lease/policy/source/body-owner/revision checks precede remote repair
and publication. A policy change during a known create forces a fresh reconciliation
under current policy so a late physical feed is located and disabled when needed.
Refresh only requests a feed refresh; it does not promise old-body extraction.
Set-enabled converges the complete approved policy together, so an old crawler mode
cannot be re-enabled between separate field updates.

Successful refetch never writes News or stores returned HTML. The durable result is
`{entry_id, pending_sync:true}`; `refetch_handoffs(limit=100)` exposes these to T09.
T09 re-GETs the entry, passes safe_input.fence plus the operation's binding policy
version into T07 CAS, and calls `acknowledge_refetch(id, request_hash,
sync_status='accepted', reason='', revision=None)` after that CAS, preferably in the
same short transaction. Final statuses are accepted/unchanged/quarantined/stale/
rejected/conflict. The acknowledgement preserves entry_id and records pending_sync
false, explicit sync_status, safe code and optional decimal revision. Engine success
alone must not be shown as accepted body repair. There is no HTML in polling results.

`refetch_fence` positively allows only standard/public_rss/public_feed/official_html/
regulatory_data. Unknown/summary policies, a disabled link, an unready full-content
binding, a different body writer, or changed source/body/revision tokens fail closed.
Active users may repair an authorized public source without subscribing; personal
sources require a current subscription. HTTP callers still authorize the article
and selected source via T11 before enqueueing.

## Unknown results and supervision

At most five attempts use bounded exponential delays and honor longer Retry-After.
Unknown creates only list existing feeds; a missing feed does not prove the earlier
request stopped and never permits automatic re-create. A uniquely found committed
feed is configured/verified against current policy. A cancelled in-flight register
is recovered under a fresh lease and final references, including disabling its
late-created feed. Unknown refresh/refetch/configuration only read back stored
state; an unprovable result becomes manual_blocked, not a retry of the mutation.
The current FeedDTO exposes crawler/disabled but omits blocklist_rules and
keeplist_rules. Matching flags therefore cannot confirm the complete approved
policy after an unknown configuration result. T04 can already return a verified
PolicyReceipt when its immediate raw-response reconciliation proves every field;
T08's later DTO-only recovery cannot make that claim and retains the manual gate.
Other actors/new idempotency keys cannot bypass an unsettled physical-create gate.
Manual gates require operator diagnosis/quiescence evidence; no blind clear/retry
endpoint is introduced. Normal retained-entry reconciliation may still observe
engine content independently; this is not proof that the unknown operation succeeded.

Run `manage.py rss_sync_worker` explicitly, or set RSS_CONTROL_WORKER_ENABLED=1
for rss_runtime. This reuses T02's singleton SQLite-directory lock and role guard.
The default T02 ORM shell remains available; no deployment profile is activated.
Status says mode=control_worker/control_worker_integrated=true, but sync_ready=false
and worker_integrated=false until T09 completes incremental/reconciliation wiring.

A live control future is never reclaimed when a lease expires. It is reported
stalled after90seconds and health fails. Unhealthy alone does not restart Docker:
at RSS_CONTROL_STALL_SECONDS (default120, configurable1..3600) the main process
exits75 using os._exit, terminating its local HTTP threads and triggering the
configured unless-stopped restart. The remote operation is still unknown; its
expired persistent lease resumes via reconciliation. SIGTERM shutdown likewise
does not claim Future cancellation or remote termination. T09 must supervise its
own read/sync work when connecting the reserved slot; this task does not prove a
wall-clock HTTP deadline or full sync readiness.

## Reproducible evidence

```sh
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-t08-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_operations.py backend/api/tests/rss/test_control_worker.py \
  scripts/deploy/tests/test_rss_runtime.py
docker build --target rss-sync -t newshub-rss-t08:isolated-check .
python3 ops/rss/T08/verify_live.py --image newshub-rss-t08:isolated-check \
  --output /tmp/rss-t08-evidence.json
```

The live harness reads T00's pinned Compose as a base and overrides only its own
random new project. It creates a synthetic HTTPS publisher with a temporary test
CA, only this experiment's private-enabled content engine, temporary PG/SQLite and
a non-admin collector token. It starts no existing app or database and always
removes its project resources/secrets. Test images/cache remain for review.
The runtime/adapter still accepts public HTTPS URLs; internal DNS/TLS mapping is
only test infrastructure and is explicitly not production SSRF/gateway evidence.

The actual engine proved 20 actor operations→one physical feed (live sequential;
20-thread contention is separate synthetic SQLite evidence), last-reference stop,
both policy modes, refresh, persistent refetch/handoff, and discovery0/1/3 plus
timeout. Miniflux2.3.3 returns404 for zero candidates and500 for finder errors;
only discover maps not_found to an empty successful candidate list, following
[its fixed-tag handler](https://github.com/miniflux/v2/blob/2.3.3/internal/api/subscription_handlers.go).
The initially broad fixture200 responses incorrectly enabled common-path feed
probes; strict404 and a genuinely empty test hostname corrected that fixture.
Lost responses, cancellation races, stale leases/tokens and stalled-process exit
are fault-injection tests, not claimed live production failures. T07 body acceptance,
T09 end-to-end synchronization and final integrated-schema/release evidence remain
separate gates. Actual isolated output is in evidence.json.
