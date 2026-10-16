# T18 optional RSSHub candidate — live gate BLOCKED

The native Miniflux path does not load this overlay or depend on RSSHub. This
delivery supplies reviewed parameter schemas, fixed artifacts and a closed
gateway candidate. It does **not** enable subscriptions, configure public DNS or
TLS, supply a real GitHub token, or approve a production deployment.

## Pure route interfaces

`api.rss.routes` imports only the Python standard library. It does not import
Django, Miniflux, HTTP clients, source parsers, browsers or model code, and performs
no DNS/network/file/secret access.

- `render_route(template_id, parameters)` and `parse_alias(value)` return immutable
  RouteInstance objects. `public()` returns only an rsshub:// alias, declared
  parameters, content_kind, capability names and executable=false.
- Approved schema subset: `github.issue`, matching T16's
  `/github/issue/:user/:repo/:state?/:labels?` metadata, supports GitHub owner/repo
  and optional state=open|closed|all. Its default canonical alias includes/open.
  Labels are explicitly unsupported in this subset, never silently dropped.
- `github.trending` requires since=daily|weekly|monthly and a language from the
  bounded LANGUAGES list; optional spoken_language uses the bounded locale list.
  Broader upstream language names such as c++/c# are not accepted by this initial
  subset. Upstream requires GITHUB_ACCESS_TOKEN and emits **repository** metadata,
  not full news articles. Issues emit issue objects. Feed mode is appropriate;
  crawler=true/HTTP200 must not be treated as proof of full article content.
- Unsupported namespaces/paths/parameters, query/fragment, percent encodings,
  slash/backslash traversal, URL-shaped values, header/cookie/proxy/token options,
  userinfo and user credentials fail with safe fixed RouteError.code values.
- `GatewayConfig` selects one server-controlled canonical HTTPS DNS origin, fixed
  RSSHub image, an internal secret reference and approved public issue repositories.
  It defaults disabled. No user request chooses these settings. Syntax checking
  is not DNS/SSRF approval; private/special names/literals/ports are rejected, but
  actual resolution and destination safety remain a deployment/live-engine gate.
- `gateway_target(alias, config)` produces a **server-only candidate URL**, never
  execution permission. `match_gateway_target(url, config)` requires exact origin
  and canonical route/parameters. Same-origin but unapproved repositories/paths,
  similar hosts, explicit alternative ports and URL encoding fail.
- `gateway_request(url, config)` is a future adapter handoff with secret_ref hidden
  from repr/public DTO, and follow_redirects=false as a required transport contract.
  **LIVE_APPROVALS is empty**. Even enabled=true fails gateway_unverified; public
  metadata always remains executable=false. No T16 seed/DDL/API/OPML integration
  has been promoted or changed.

The current EngineAdapter has no fixed publisher Basic Auth setup and its API
session's allow_redirects=false concerns the **Miniflux API**, not Miniflux's
publisher requests. A request data field does not implement no-redirect behavior.
Before any approval is added, a coordinated minimal adapter/configuration change
must prove fixed system credential selection and authenticated publisher redirect
refusal with the real engine/gateway. Do not repurpose API credentials, attach auth
by hostname prefix, or pass user-supplied headers/URLs/secret values.

## Optional service and closed Nginx candidate

`compose.rsshub.yaml` is an independent optional overlay with profile rsshub. It
does not edit the native Compose files or activate a profile. Include it explicitly
only in an approved RSSHub deployment. Compose resolves its required token-file
variable when the file is included, so leave this file out of native startup.
RSSHUB_ENTRYPOINT_FILE must select the absolute reviewed entrypoint path; this
avoids Compose multi-file relative-path resolution against the wrong base folder.

The fixed official RSSHub image runs UID1000, read-only rootfs, no-new-privileges,
no extra capabilities,128pids/512MiB cap and memory cache with64 **items**, not64MiB.
It publishes only127.0.0.1:1200 by default. The real isolated test started the exact
candidate under these restrictions and verified health; this is not a production
resource/peak measurement. No Redis service, remote browser or custom RSSHub route
is supplied. Standard image browser cache was empty; Node24.22.0 was observed on
linux/amd64. Upstream dependencies may include browser libraries; none is added to
NewsHub's lightweight sync image.

The entrypoint reads only `/run/secrets/rsshub_github_token`, disables xtrace before
reading, rejects empty/multiline/invalid/oversized values without echoing them and
exports only the upstream GITHUB_ACCESS_TOKEN setting. The source file selected
by RSSHUB_GITHUB_TOKEN_FILE must be protected and readable by container UID1000;
Compose local secret mounts do not automatically fix host ownership. Gateway
Basic Auth and GitHub source token are distinct secrets. Use a dedicated
public-resource-only service token; public URL syntax does not prove token scope.

`deploy/nginx/rsshub.gateway.conf.disabled` is excluded from ordinary *.conf
includes and hardcodes live=0, returning503. Its example host is not provisioned.
It is a candidate for the existing host Nginx, not a second production gateway
service. The reviewed allowlist accepts bounded Trending parameters and only the
explicit public DIYgod/RSSHub issue repository. Keep the Python repository
allowlist and Nginx route list aligned when reviewing additional public targets.

After a real gate passes, host/TLS/htpasswd paths and activation must be part of
the reviewed deployment. The candidate enforces exact Host/raw request_uri,
GET/HEAD only, Basic Auth, request limits, no forwarded client headers/body,
Authorization/Proxy-Authorization/Cookie stripping, hidden Location/Refresh/
Set-Cookie and generic handling of upstream redirects/server errors. Access logs
are off and Nginx error logging is critical-only. RSSHub DEBUG_INFO=false,
LOGGER_LEVEL=error and NO_LOGFILES=true do not by themselves prove that real token
failure logs/bodies are safe; that remains unverified.

Miniflux FETCHER_ALLOW_PRIVATE_NETWORKS must remain0. Its registered Feed must use
the real public HTTPS gateway address and verified public DNS/TLS/hairpin path.
Do not register http://rsshub:1200, map the public hostname to a private address,
disable TLS checks, add a general proxy, or use the public demo RSSHub as a
production dependency. A gateway failure leaves this optional feature unavailable;
native RSS and saved content continue independently.

## Version and evidence

`upstream.lock.json` records five fixed upstream file hashes and actual image
metadata. The immutable index digest is1945d316…; observed OCI source revision
8e94b949… matches the reviewed source. `latest` was used only to discover a
candidate digest; no runtime configuration uses a mutable image tag. The full
AGPL3 license is retained in the existing T16 directory_data license file and all
source links retain their fixed commit. Nginx1.28.3's fixed image is laboratory
infrastructure only, not a recommendation to replace the user's host Nginx.

```sh
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-t18-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_routes.py
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T18/verify_isolated.py \
  --output /tmp/t18-evidence.json
```

85 offline contracts passed. The isolated experiment used an actual pinned
RSSHub process with a synthetic token **only for health**, plus actual Nginx and
a synthetic HTTP fixture under a temporary local test CA. It temporarily changed
live=0 to1 **only in its temporary config** to verify401/200/405/421, path rejection,
header stripping,302→502 with no Location, generic500 handling and absence of
selected synthetic credentials from logs. No real publisher route was requested.
The fixture records credential **presence booleans**, never header values.

These results are not real public DNS, trusted public TLS, public hairpin,
DNS-rebinding/IPv6/private redirect safety, Miniflux publisher redirect rejection,
real GitHub token scope/object quality or end-to-end DTO/OPML/log isolation proof.
T18-A1/A3 remain BLOCKED and A2 is partial. The test creates only one unique
newshub-rss-t18-* project, random loopback ports and temporary token/CA; all project
containers/networks/volumes and temporary secrets are removed. Only aggregate
evidence.json is retained. No production action or existing service access occurs.
