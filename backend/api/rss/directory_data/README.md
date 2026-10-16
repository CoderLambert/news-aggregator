# Pinned RSS directory inputs (schema v1)

These are metadata candidates, not health-checked feeds. No source content was
requested to prepare these artifacts. All `verified_at` values remain null.

## Provenance and license

- `seed-v1.lock.json` pins the exact UTF-8 JSON bytes imported by
  `import_pinned_seed()`. Root `source.commit` identifies the NewsHub code baseline
  used for the authored supplement; `newshub-curated-v1` identifies its metadata
  revision. It does not claim the generated seed existed in that baseline commit.
- The first collection is **38 actual HTTPS entries** from
  [plenaryapp/awesome-rss-feeds at 9ab2482](https://github.com/plenaryapp/awesome-rss-feeds/tree/9ab2482cae9031a5a39635c887fcfc8ece7e130a),
  specifically `recommended/with_category/Programming.opml` and
  `recommended/with_category/Web Development.opml`. Title, description and xmlUrl
  were copied directly; the enclosing outline becomes a category tag. URL is the
  stable local key. Seven HTTP URLs were excluded, without rewriting them to
  HTTPS. The lock records source-file hashes, paths, and every exclusion.
  Upstream's CC0-1.0 license is preserved as `plenary-CC0-1.0.txt`.
- The second collection contains two newly authored CC0-1.0 metadata records:
  React's GitHub release Atom URL and 中新网健康's RSS URL. This collection carries
  its own origin and does not replace Plenary attribution. The supplement is
  explicitly dedicated under [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/).
- The third collection is a declarative projection of the GitHub issue route
  from RSSHub's real
  [build/routes.json at gh-pages 140f27c](https://github.com/DIYgod/RSSHub/blob/140f27c701b499703cb3e22cb4541d50b1406c40/build/routes.json).
  It includes only name, description, categories, path, parameters and features.
  No handler, module, Radar or analytics is shipped in the projection.
  `rsshub-subset-v1.json` provides that collection independently for contract tests.
  `rsshub-format.lock.json` pins both the full upstream JSON hash and subset hash,
  plus source type and license hashes at source commit
  `8e94b949479ba3295ee9653806f59b2be6559158`.
  RSSHub currently supplies the GNU AGPL v3 license, preserved in full as
  `rsshub-AGPL-3.0.txt`. Its metadata remains attributed **AGPL-3.0-only**, never
  relabeled CC0. The generated artifact commit and separately inspected source
  commit are recorded separately; no unproven build correspondence is claimed.
  Source is available through the pinned upstream URLs and this repository's
  JSON projection. Publisher content rights and RSSHub gateway approval remain
  separate from software/data licensing.

The default bundle's license expression is `CC0-1.0 AND AGPL-3.0-only`. Each result
carries the relevant collection's source id, commit, license and stable key.
This bounded subset deliberately does not claim to cover the full Plenary or
RSSHub catalog, nor to have tested the routes against live publishers.

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
