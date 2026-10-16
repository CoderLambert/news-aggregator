# Feed admission correction (2026-10-16)

Candidate implementation for ARCHITECTURE 4.1–4.3 and C03/C05, reviewed separately
by T04. It unifies direct, signed discovery candidate and directory selection
through `subscriptions.subscribe`. A token, catalog name or `body_fields` is not
collection permission or native-full-content evidence. No DDL, permissions model,
user CSS, proxy, publisher fetcher or production service was added.

`feed_policy.approved_feed_policy(canonical_feed_url)` intersects exact reviewed
feed URLs (including syndication hosts), URL/retired publisher rules and current
database contracts. New ordinary public article sources receive `standard` and,
when the full-content gate is enabled, default `full_content`. New restricted
sources retain actual limitations; non-article/mixed feeds receive
`rss_summary_only`. Forbidden collection and unsupported selection contracts are
rejected. Shared bindings also intersect every linked publication, source URL,
persisted known source policy, association policy and current SourceConfig.
Admin privilege cannot override these restrictions. No random `display_name`
exception exists.

Only `https://jvns.ca/atom.xml` and `https://webkit.org/feed/` currently default to
native `feed`/`public_feed` from finite T27 observations. The copied public
sample evidence is [native-samples.json](native-samples.json). Each has two real
feed-mode samples; manual completeness remains `not_confirmed`. This changes
mode only and never stamps a News entry `verified`. V8's declared Atom body
field is deliberately not treated as native evidence. Other exact paths/query
variants do not inherit a native-mode exception.

Hacker News/hnrss mixed links remain Feed content, with discussion type and
summary completeness. arXiv stays abstract; product/repository/video-like source
types cannot enable full-content crawling. No per-item fetcher was added.
`known_feed_content_kind` is a pure metadata fallback for generated source names
in sync; it does not run admission, read settings or throw a collection-policy
failure that would block a whole page. Existing linked config and page/CAS fences
remain responsible for current source policy.

## Deployment gate and SDK contract

`RSS_FULL_CONTENT_ENABLED` accepts only environment strings `0` or `1` (not
empty, whitespace, `true`, `false`); default is **0**. Django settings exposes a
strict bool. `EngineConfig.full_content_enabled` independently defaults False;
`from_environment()` reads the same strict switch. Isolated positive extraction
tests must explicitly opt in. Root separately owns production Compose web+sync
default0 wiring and HTTP403 mapping.

Gate0 makes ordinary subscriptions choose Feed mode and blocks admin full mode,
queued full-mode operations and explicit repairs. The adapter independently
rejects full-content create (including `disabled=True`: pinned Miniflux processes
initial entries even then), enabled full policy updates/re-enables, refresh of a
currently crawler-enabled remote feed, and explicit refetch. Gate0 permits Feed
downgrade and disabling an existing feed without losing its historical mode.
`RSS_DEFAULT_FEED_MODE='feed'` remains an additional initial preference when gate1
is deliberately enabled. Ordinary subscribers cannot silently alter a shared
mode; the existing admin endpoint remains the mode control, without arbitrary
rules/CSS input.

**Gate0 is not an engine kill switch.** Existing crawler-enabled engine feeds
and already dispatched operations must be quiesced/disabled and verified before
a cutover requiring no future publisher requests. The app switch cannot cancel
an in-flight request or stop autonomous Miniflux polling by itself.

Every create and full policy update atomically includes the server-owned
`block_filter_entry_rules` field. `EntryURL=` uses the pinned Miniflux filter
grammar with bounded host authority regexes (case/IDNA/subdomain/trailing dot/port
boundaries). Feed mode excludes completely forbidden publishers while preserving
permitted arXiv/HN/etc Feed summaries. Full mode additionally excludes known
no-HTML, summary-only, non-article and mixed publisher targets. This native filter
drops the **entire entry**, which is a documented coverage loss for mixed full
feeds; it cannot preserve that item's summary while skipping only HTML.

`EngineConfig.server_entry_url_block_rules` is a trusted immutable server
snapshot, never an HTTP input. The mandatory static collection restrictions
cannot be cleared. Main-thread prepare/dispatch compiles dynamic SourceConfig
domains, including disabled endpoints and blocked statuses, into Request data;
the network thread uses `dataclasses.replace` and never reads ORM. Policy
confirmation checks the raw response for every sent field on create and update.
An existing feed with unproven fields is unknown, never recreated. The existing
worker reconciliation locates one committed feed and converges current policy;
the later DTO-only configuration recovery remains manual-blocked when it cannot
prove all fields.

The last ORM checks run on the dispatching main thread. Source tightening before
dispatch prevents new mutations. After dispatch, a policy change cannot retract
the remote request. Explicit repair first checks the current stored article's
publisher permission, then the engine's current entry URL and complete identity
before issuing fetch-content. A changed engine URL is refused; no network ORM or
direct News write was introduced.

## Actual evidence and limits

Run the focused tests with an isolated SQLite path:

```sh
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-feed-policy-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_feed_policy.py backend/api/tests/rss/test_engine_adapter.py \
  backend/api/tests/rss/test_control_worker.py backend/api/tests/rss/test_operations.py \
  backend/api/tests/rss/test_subscriptions.py backend/api/tests/rss/test_discovery.py
python ops/rss/feed-policy/verify_live.py --output ops/rss/feed-policy/evidence.json
```

The harness reuses only pinned T00 images and an existing locked lightweight
runtime image; the task's backend is mounted read-only. It creates a fresh random
project, PG/SQLite, non-admin collector, synthetic HTTPS publisher, temporary CA
and token. Synthetic `www.reuters.com` and `arxiv.org` names resolve solely to the
new project's fixture. No public publisher, production secret, user volume or
existing service is contacted. Project-labelled containers/networks/volumes are
checked absent before creation and absent after cleanup. Image cache remains.

The actual pinned Miniflux experiment proves normal `subscribe` chooses crawler
at **initial create**, extracts an allowed article, and sends zero article
requests to direct forbidden/no-HTML targets. Gate0 uses a gate0 worker config,
preserves an arXiv Feed entry without HTML fetching, refuses admin/SDK full paths,
and allows downgrade. The counters and exact images are in
[evidence.json](evidence.json). Ordinary Feed/favicon metadata requests still occur.

**Redirect/rewrite safety remains BLOCKED.** The same synthetic run deliberately
proves an allowed publisher URL can redirect to the denied synthetic publisher:
its `/redirect-target` counter is positive. Native filtering runs before URL
rewrite and scraping and does not cover final redirects. This is negative
evidence, not a production experiment or a claim that C03 is fully accepted.
Full-content enablement remains closed by default until that deployment gate is
resolved or its narrowed scope is explicitly accepted. No new proxy platform or
transport has been introduced. The explicit-refetch path does not use Miniflux's
entry filters, hence its separate current-target and identity checks are required.

Pinned primary behavior reviewed: [filter grammar and OR rules](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/filter/filter.go),
[create before initial processing](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/handler/handler.go),
[entry processing and scrape order](https://github.com/miniflux/v2/blob/2.3.3/internal/reader/processor/processor.go).
These are implementation constraints, not evidence of private-network protection.
