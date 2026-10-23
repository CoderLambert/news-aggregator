# Pinned RSS directory inputs (schema v1)

These are metadata candidates, not health-checked feeds. No source content was
requested to prepare these artifacts. All `verified_at` values remain null.

## Active seed: Tidings Top200

`seed-v1.json` is the schema-v1 projection of `tidings-top200.opml` from
`fuxiaoai/tidings-rss` at
`f9b54abf9dd3e7af2a1dda12bca06c8fe8b57d7b`. The lock pins the seed, original
OPML, CC0-1.0 license, import report, and selected-description receipt.

The selected OPML contains 200 records under 14 category outlines. The active
directory includes the 194 original HTTPS feed URLs; the six HTTP records remain
excluded by the existing HTTPS-only policy. URLs are neither upgraded nor
replaced. `tidings-import-report.json` records every selected item, original
category, and inclusion or restriction reason.

Names and categories come from the pinned OPML. Descriptions match the same
commit's `data/feeds.json` by exact feed URL; category-only labels use short
readable descriptions. AWS and OpenAI have locally authored summaries referenced
to their primary news/blog pages. `tidings-descriptions.json` records each
description and its basis. No feed health, language, region, or statistics are
inferred.

Importing this seed does not subscribe to or fetch any feed. The normal runtime
calls `import_pinned_seed()` on its metadata schedule; local operators can call
the same function for an immediate refresh. Existing user subscriptions are
unaffected by seed updates. Old database snapshots are retained, and Git history
provides the previous seed for source-level rollback.

## Supplementary format fixtures

The retained Plenary and NewsHub-curated artifacts document the previous seed and
remain available as schema fixtures. `rsshub-subset-v1.json` independently tests
the declarative RSSHub namespace format. `rsshub-format.lock.json` pins that
projection and its AGPL-3.0-only license receipts; RSSHub metadata is never
relabelled as CC0. These supplementary artifacts are not part of the active
Tidings seed.

## Import format and service contract

`import_snapshot(payload: bytes, *, expected_checksum: str)` accepts reviewed,
pinned UTF-8 JSON, at most 8 MiB / 10,000 entries / 100 collections. Schema v1 has
`schema_version: 1`, a `source` object (`id`, fixed Git `commit`, `license`, HTTPS
repository `url`) and either `entries`, `namespaces`, or a list of independently
attributed `collections`. Collection objects contain their own `source` and
exactly one of `entries` or `namespaces`.

A curated entry uses `key`, `name`, `public_url`, optional `description`,
`language`, `region`, `tags`, `visibility: public|hidden`, and optional template
requirements. Personal visibility and claimed `verified_at` are rejected.
Concrete feeds must be public, credential-free HTTPS URLs; this syntactic
metadata check grants no DNS/network approval for subscription.

RSSHub `namespaces` follows the actual routes.json object format:
`{namespace: {name, description?, lang?, categories?, routes: {routeKey: route}}}`.
Route records support `path` as a string or list, `name`, `description`,
`categories`, `parameters` (string descriptions or description/default/options
objects), and `features.requireConfig/requirePuppeteer/antiCrawler/supportScihub`.
Only declarative fields are read. Heat, topFeeds, handler/module and Radar values
are ignored even when present in a supplied artifact. Optional route parameters
remain optional. Unsupported path grammar rejects the update; it never evaluates
JS. Every route remains `kind: route_template`, with its relative path (including
optional markers) in `public_url`; it is not a public feed instance or a gateway
URL. Required config names are capabilities, never config values/secrets.

All collections validate before any write. One short transaction creates the
snapshot/entries and switches the unique active flag. Validation or DB errors
leave the old snapshot active; old snapshots are retained. Byte-identical imports
reuse a snapshot. Stable result UUIDs derive from collection id + key, independent
of sort order, descriptions and snapshot checksum.

`search_directory(q='', *, limit=20, cursor=None)` returns `results`,
`next_cursor`, and `snapshot_version` (the active SHA256). It reads only the local
snapshot, performs NFKC/casefold matching, ranks exact URL/name, prefix, then
name/URL/tag/description substring, followed by feed-before-template availability
and stable UUID. This does not assert feed health. Limit is 1–50; query is at most
200 characters. Signed cursors bind the normalized query and checksum; a snapshot
change rejects an old cursor. It preserves one selected snapshot across a read
and never mixes entries from different versions. Old snapshot rows remain valid
while an in-flight search completes.

`subscribed: null` is intentionally unknown until T20 adds authenticated user
state; `cached_articles: []` is an empty authorized preview, with no statistics.
No personal source or subscription model is read or written by this module.
The T02 worker must call the importer once per daily metadata check and retain
its check schedule; this task does not install a scheduler or network updater.
The caller supplies the reviewed bytes/checksum and handles validation failures.
T20 exposes the route, enriches user state and uses normal subscription validation.
