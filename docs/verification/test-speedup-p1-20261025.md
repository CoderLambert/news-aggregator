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
