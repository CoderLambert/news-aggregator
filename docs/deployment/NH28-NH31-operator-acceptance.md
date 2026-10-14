# NH-28–NH-31 release acceptance — operator-owned gates

This document supplies evidence collection contracts, **not** a declaration that
NewsHub is authorized or production-ready. All eight gates start `NOT_RUN`.
Do not store actual credentials, medical records, publisher tokens, sensitive
database contents, or the evidence directory inside Git.

## Offline workflow

1. Finish this release's code/CI and record the **exact full main SHA**.
2. Create a private directory on the operator's machine (`umask 077; mkdir
   -p /secure/newshub-acceptance`).
3. Run `python scripts/deploy/acceptance_evidence.py init --file
   /secure/newshub-acceptance/release-evidence.json --sha <40-hex-SHA>`.
4. For each gate, save a redacted evidence report with mode 0600.
   Set its `status` to `EVIDENCE_RECORDED`, `evidence_file` to the local
   filename relative to the evidence root, `sha256` to the SHA-256 of the file,
   and a short nonsensitive `operator_note`.
5. Run `python scripts/deploy/acceptance_evidence.py check --file
   /secure/newshub-acceptance/release-evidence.json --sha <SHA>
   --evidence-root /secure/newshub-acceptance`.

The checker exits 2 while gates remain unrun/blocked and exits 1 on invalid,
missing or altered evidence. Exit 0 only means the files' integrity matches the
ledger, **not** that the findings were approved. Production rollout still
requires an explicit human sign-off for every gate.

## NH-28: BYOK-only research, not site-paid fallback

- `NH-28-research-byok-auth`: record the public site's approved auth mode,
  user-by-user authorization scope, model routing, and explicit rejection
  without a valid user BYOK connection. If subscription usage lacks formal
  approval, leave it disabled. No public provider-secret fallback.
- `NH-28-research-runtime`: using a synthetic user/model, test tool-call
  budgets, cancellation, disconnect/reconnect recovery, stream quotas, and
  stale model or credential generation fences. Record denied access and
  zero paid calls in the isolated test.
- Do not equate an existing `503 hosted_integration_unapproved` guard with
  permission to bypass an external platform approval.

## NH-29: SQLite off-host restore and key recovery

- `NH-29-offhost-restore`: reuse `scripts/deploy/backup.sh`,
  `scripts/deploy/restore.sh`, and the immutable release manifest from
  [release gates](release-gates.md). In an **isolated project/database volume**,
  validate a snapshot made by SQLite online backup (including committed WAL),
  then restore it without production writers and compare schema, row counts
  and selected hashed records. Copy an encrypted snapshot off-host and
  demonstrate recovery from that location. Redact all data before recording
  evidence.
- `NH-29-key-recovery`: separately restore the protected Django/token and
  provider-key encryption material into an isolated environment, verify a
  synthetic encrypted credential can be decrypted, then destroy local test
  secrets. Never put raw encryption keys in the ledger or Git. Missing key
  recovery leaves the gate `NOT_RUN` or `BLOCKED`.
- Do not use `docker compose down -v`, mutate production backups, or treat
  `python manage.py migrate` as a rollback strategy.

## NH-30: official source legality and content quality

- `NH-30-source-license`: enumerate every enabled `source_policy.POLICIES`
  and `sector_feeds` contract; record official API/RSS URL, access and
  redistribution license, attribution requirements, approval date, owner and
  known rate budget. Unsupported or unlicensed sources stay disabled.
- `NH-30-content-quality`: in a separately approved and rate-limited
  sampling window (never a bulk live crawl in CI), independently verify:
  GUID/canonical URL, publisher, real publication timestamp, body completeness,
  excerpt/full classification, 304/429 handling, and safe access to the source.
  Include per-source error rates and recovery intent for failures. Keep
  distinct human-reviewed samples from synthetic tests.

## NH-31: 2C/4GB capacity and safe degradation

- `NH-31-vps-capacity`: on a disposable **isolated 2-vCPU/4GB** environment,
  test representative article list/search, source listing, BYOK-disabled
  browsing, bounded SSE connections, crawler/content/indexer concurrency,
  SQLite WAL checkpointing, and a cache-cold boot. Log CPU, RSS, storage,
  request p50/p95/p99, 5xx/429 and queue-age metrics without credentials.
  Record explicit operator-approved thresholds; a healthy /health/ready
  response alone is insufficient.
- `NH-31-degradation`: simulate model outages, provider 429, malformed RSS,
  stalled SSE readers, source worker crash/recovery, index unavailable,
  disk pressure and read-only mode. Verify rejected work remains bounded,
  user-readable fallbacks, and that no automatic paid retries are created.
- Never run capacity testing against the public VPS or real paid providers
  without separate explicit authorization.

The release is not approved until every gate has genuine evidence **and**
the owner has reviewed and signed off on it. A code-only PR can ship these
tools, but cannot claim the real-world acceptance has occurred.
