# BYOK T00 CI dependency-cache optimization (P1)

Base PR: #169, branch: `chore/test-cleanup-p0-20261025`.

## Diagnosis
Prior complete CI #1016 spent approximately 194 seconds inside the T00 isolated SDK/Proxy contract step, including creating and reinstalling two venvs and generating Prisma. That was not an isolated dependency-install timing; real savings remain to be measured.

## Change
- Extract just dependency preparation into `ops/ci/install-t00-deps.sh`, using one private content-addressed cache per pinned SDK/Proxy locks, Prisma preparer, Python/Node versions, and platform.
- Cache miss or invalid cached environment recreates the two venvs, installs the exact pinned dependencies, and generates Prisma. Cache hit checks stamp, interpreter, Prisma manifest, `pip check`, and core package metadata before reuse.
- Both protocol probes, SDK comparisons, Django synthetic proof, isolated Redis, empty credential environment, and per-run temporary report/DB/HOME are unchanged; no tests are skipped on a cache hit.
- Protect the cache with a private root, `flock`, a symlink check, and a success-only marker. The cache stores dependencies and generated Prisma artifacts, not synthetic runtime reports or provider credentials.

## Evidence
An isolated, dependency-free fake-toolchain harness ran 4 tests: cold/hit/lock invalidation; missing Prisma manifest; interrupted install; symlink-root refusal. All 4 failed as expected while the script was missing, then 4/4 passed after implementation. These checks do not verify real pip/Prisma or workflow success.

Full job runtime should be compared on the same self-hosted runner: cold run vs subsequent warm run, splitting the new dependency cache step from the full protocol step. The previous 194 seconds included both and is not a guaranteed saving.

## Boundaries
No change to production code, release image, normal backend Pytest gate, safety assertions, or merge requirements. Do not merge or claim full CI success until exact-SHA Ready/full verification succeeds. No automatic workflow dispatch is introduced.

## PR #169 integration with main / #171

Integration base: `main@7e55c45a99a4ec593ac070bfd9704e8681b49558`;
original PR head: `9c3107a58832d3368bfff5416878dd39a6d5617d`.
The integration uses a non-rewriting merge and preserves the existing lifecycle
and T00 CI assertions together.

- T00 now supports the existing `--status` / `--cache-only` maintenance contract,
  `.newshub-ready` and `.current-key`. Valid legacy `.ready` entries migrate
  without reinstalling; Prisma manifest/schema content changes invalidate reuse.
- Existing `cache-backend` and its CI-only persistent volume provide status,
  prewarming and targeted GC. No additional service or cleanup framework is added.
  Explicit GC keeps the latest two successful keys plus the current key, and
  retains download caches. Keys can accumulate between explicit maintenance runs;
  this is not an automatic byte quota.
- Protocol consumers share the existing installation lock for their entire
  lifetime. Preparation and GC take the exclusive lock. The existing idle-runner
  checks and listener pause also remain mandatory for managed maintenance.
- The main cache regression inherited `npm_config_cache` from its runner while
  changing only XDG_CACHE_HOME. A pre-existing synthetic `downloaded` marker then
  suppressed the fake network event, leaving `installs.log` absent. Before the
  fix the isolated poisoned-parent case raised FileNotFoundError; the same test
  passed without that override. Fixtures now explicitly own all npm/pip and
  installed-environment cache roots. The negative parent-cache case and the
  download/fail/resume/hit assertions remain enforced.

### Local candidate verification

The code candidate was original HEAD plus the above merge and integration edits,
not the historical green CI candidate. One persistent GPT-6 Luna / xhigh session
used a Python 3.12.14 environment with versions from the unchanged CI lock.

- Offline CI unittest discovery: **75 tests passed** (includes lifecycle, GC lock,
  benchmark trigger and both generations of CI contracts).
- SecretStore umask and runtime activation pytest modules: **31 passed**.
- Replayed poisoned-parent npm retry: **1 passed**, with the external synthetic
  sentinel unchanged. No real npm downloads or shared-cache writes were involved.
- Shell syntax, Agent structure and unstaged whitespace checks passed. The merge
  exposed two existing main-document EOF whitespace errors; only those trailing
  blank lines were removed before staging.
- Pytest emitted an unknown-DJANGO_SETTINGS_MODULE warning because the minimal
  offline environment intentionally did not load Django plugins. These selected
  deployment/cache tests do not use Django or a live database.

Historical CI #1022 attempt 1's T06 failure is not considered fixed merely because
attempt 2 passed. Dedicated synthetic reproduction and final exact-head/base CI
must be reported separately; local fake-cache tests do not establish real
SDK/Proxy readiness or whole-pipeline performance gains.
