# NewsHub RSS Rules

Read [root rules](../../../AGENTS.md) and [backend rules](../../AGENTS.md). These rules also govern `backend/api/tests/rss/`, `tests/rss_engine_contract/`, `scripts/rss/` and RSS migration work; read them explicitly outside this directory.

- Follow the [RSS architecture contract](../../../docs/plans/rss-engine-migration/ARCHITECTURE.md): Miniflux owns routine feed fetching/extraction; NewsHub owns subscriptions, control/sync, sanitized content, access and AI consumption. Do not add a parallel feed parser or site extractor.
- Keep `EngineAdapter`, operations/control worker, reconciliation/sync, `content_store` and access separate. Network results never authorize their own DB writes; validate captured identity/version/lease inside the final short transaction.
- A FeedBinding is anchored to engine instance/account/feed identity; never silently rebind it after engine recreation. Shared physical feeds do not imply shared user subscriptions or visibility.
- Preserve URL/redirect/DNS/size/deadline/budget policy. Keep mutations idempotent; an unknown remote result requires reconciliation, not blind resend. Respect Retry-After and bounded retry rather than increasing concurrency around 429.
- Preserve source/body version fences, reader ACL and digest-based translation invalidation. Do not downgrade stored content, invent publication dates, call an unverified summary complete, or replay stale private content.
- Catalog/discovery metadata is not proof of source health or permission to subscribe. OPML is untrusted input; preview/confirm must stay bounded and owner-scoped.
- Existing Scrapy/full-content compatibility may still run. Repair authorized regressions, but defer removal/cutover and production engine operations to the RSS retirement/release gates.
- Select real RSS tests in `backend/api/tests/rss/` (adapter, subscriptions, operations, body commit, access, reconciliation, OPML). Read [test rules](../../../tests/AGENTS.md); `rss_live`/real engine/source checks require explicit isolated opt-in and are not implied by offline PASS.

## Code Review Rules
Flag identity rebinding, missing write/read fences, ACL expansion, unbounded retries and content degradation. New fields crossing engine DTO, persistence and frontend parsing need corresponding contract coverage.
