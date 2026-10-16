# Feed admission correction delivery

2026-10-16; branch `task/rss-feed-admission-policy`, baseline `e4e62fd`.
Implementation reviewed independently by T04; final SHA is the Git delivery
receipt. No production action, DDL, user database, shared Compose or API routing
changes. Root owns Compose/HTTP403 wiring (`7082d2b`) and T09/T26 fixture opt-in.

The implementation and parameter contract are in [README.md](README.md).
Ordinary article default crawling is available only with explicit
`RSS_FULL_CONTENT_ENABLED=1`; the default0 gate independently applies at service,
dispatch and SDK boundaries. Known restricted/non-article/mixed policies cannot
be overridden by admin. Limited real native observations select Feed mode but do
not imply complete/verified content. Finite native evidence is copied from T27
with original public URLs, hashes, sample limits and `not_confirmed` status.

Actual commands/results on Python3.12.14:

- `RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync DJANGO_DB_PATH=/tmp/newshub-rss-feed-policy-tests.sqlite3 PYTHONPATH=backend:crawler /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_feed_policy.py backend/api/tests/rss/test_engine_adapter.py backend/api/tests/rss/test_control_worker.py backend/api/tests/rss/test_operations.py backend/api/tests/rss/test_subscriptions.py backend/api/tests/rss/test_discovery.py`: **199 passed, 37.92s**, exit0.
- Same environment, separate `/tmp/newshub-rss-feed-policy-sync.sqlite3`, `pytest -q backend/api/tests/rss/test_sync_reconciliation.py -k 'not refetch'`: **38 passed, 6 deselected, 3.56s**, exit0. The six existing positive refetch fixtures require explicit gate1, already assigned to root; they are not reported as passing this branch.
- `/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/feed-policy/verify_live.py --output ops/rss/feed-policy/evidence.json`: **exit0**. Final project `newshub-rss-feed-policy-5fa638238d8c`, fixed Miniflux2.3.3, dedicated non-admin collector, synthetic HTTPS publisher, new temporary PG/SQLite/CA/token, existing locked lightweight image with current backend mounted read-only. Counters prove initial allowed article extraction, no direct denied or abstract HTML request, Feed-only abstract retention, gate0 normal service/worker and independent SDK refusal, downgrade allowed. All project containers/volumes/networks removed. Earlier own project `newshub-rss-feed-policy-79f6658e6c77` was also removed.
- `git diff --check`: exit0 before commit.

Failure-driven corrections retained in tests: disabled blocked SourceConfig with
empty reason must still retain publisher deny domains; feed-only rules must not
drop permitted HN/arXiv summaries; current engine refetch URL change is rejected
before fetch-content; raw create policy confirmation never permits second POST.
Existing unknown-create recovery still locates and converges one committed feed.

**Production gate remains BLOCKED for automatic/explicit full extraction.** The
synthetic experiment deliberately reproduces allowed URL→denied publisher HTTP
redirect (`redirect-target` requested once). Native EntryURL filtering precedes
rewrite/scraping and is not final-target protection. This evidence is synthetic,
not public or production traffic, and cannot mark C03 fully accepted. Gate0 is
the deployable boundary until narrowed enablement is accepted or redirect policy
is resolved. Existing full feeds/autonomous engine polling and in-flight requests
must be quiesced separately; the local switch cannot cancel them. Full-mode
native filtering drops entire forbidden entries, a coverage difference explicitly
documented rather than a claim of summary-only per-item extraction control.

Not rerun: production/GitHub-token gateway tests, full repository CI, full native
contract suite, T03 paired recovery, T26 builds, unrelated T27 browser/public
sampling. T00 does not use this SDK gate. T08 harness was updated to explicit
isolated gate1 without relabelling its prior evidence; root owns T09/T26 updates.
