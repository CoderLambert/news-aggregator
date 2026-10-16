# T00 isolated Miniflux contract laboratory

This is a test harness, not a deployment manifest or production adapter. It never
accepts an existing engine URL, database, container, or Compose path. The runner
chooses a fresh `newshub-rss-t00-<12 hex>` project. The fixture rejects remote Docker
daemons and existing project resources. PostgreSQL uses tmpfs and has no published
port; API/fixture ports bind only loopback with random host ports. Teardown removes
only this project's containers/network, including on failure. Hardcoded passwords
belong exclusively to throwaway synthetic accounts.

```sh
python3 -m venv /tmp/newshub-rss-t00-venv
/tmp/newshub-rss-t00-venv/bin/python -m pip install -r ops/rss/T00/requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /tmp/newshub-rss-t00-venv/bin/python -m pytest \
  -c tests/rss_engine_contract/pytest.ini --confcutdir tests/rss_engine_contract \
  tests/rss_engine_contract/test_engine_contract.py -m 'not rss_live' -q
/tmp/newshub-rss-t00-venv/bin/python ops/rss/T00/run_live.py
```

The separate pytest configuration and confcutdir intentionally exclude the parent
conftest that initializes Django. No NewsHub database/settings/credentials load.
The live suite is one ordered experiment: A1 populates the empty database, A3
changes an article, A2 ages/cleans rows, then A4 probes security/failure behavior.
Run the entire live suite rather than one downstream stage in a fresh database.

The runner creates a temporary JSON file containing exactly `environment: isolated`
and `project`, then sets `RSS_TEST_ALLOW_LIVE=1` and `RSS_TEST_CONFIG`. Without the
live flag tests skip; malformed config fails before creating resources. No fallback
to an existing service exists. The test bridge permits outbound traffic, but all
publisher URLs are fixed synthetic endpoints. SDK sessions disable ambient HTTP
proxies. The content engine explicitly allows private fetches; a separate guarded
engine/database explicitly refuses them. Content tests are not SSRF proof.

## Frozen evidence and downstream interfaces

`versions.json` records actual pulled digests/image IDs/platform and SDK wheel
checksum from [PyPI 1.1.6 metadata](https://pypi.org/pypi/miniflux/1.1.6/json).
`requirements.txt` freezes this laboratory only, without changing application
dependencies. PostgreSQL17.6 is the tested candidate, not a recommendation to adopt
an old patch release in production. All Compose images are pinned by digest.

`contract.py` supplies executable evidence for T04/T09:

- Empty engine H=0. Use `order=id,direction=asc,after_entry_id=L,before_entry_id=H+1`
  with limit 1..1000. If H is signed int64 maximum, the probe blocks rather than
  wraps or omits H; T09 must preserve progress and report the boundary.
- SDK1.1.6 fetch_entry_content does not persist. The minimal extension adds only
  `update_content=true` to its fixed SDK endpoint, then independently GETs the
  entry. It does not fetch publisher URLs or introduce a transport abstraction.
- Refresh of a crawler-enabled feed leaves extracted old content intact. Explicit
  refetch persists changed content. Neither action proves completeness.
- Explicit read/unread90-day cleanup uses created_at, writes tombstones, retains
  old-published/recent-created entries and starred/shared exceptions. Reconcile
  actual retained rows, without a published_at cutoff.
- The guarded engine rejects private DNS/IPv4/IPv6/metadata addresses and dangerous
  protocols. HTTP503/badXML do not register feeds. Feed Basic Auth is absent from
  article fetches and from a redirect to another host.

These are real engine/PG experiments using a synthetic publisher, not real-source
quality or production network evidence. Public HTTPS-to-private redirects, DNS
rebinding, TLS/hairpin behavior, authenticated gateway redirect prohibition,
complete error/log secret isolation, media rewriting, huge API responses and low-ID
late-commit/cleanup races remain unverified. T18 owns actual gateway evidence and
T04 owns production DTO/error/size limits. Cross-host header stripping is not a
no-redirect policy; this harness makes no such claim.

The recorded test runner is host Python3.14.8. Fixture Python3.12.12 does not prove
runner/SDK compatibility with repository Python3.12 CI; rerun there before
accepting that compatibility gate. No production action is performed here.
