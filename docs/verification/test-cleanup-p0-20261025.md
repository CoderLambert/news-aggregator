# Test cleanup P0 verification — 2026-10-25

Base: `e74f7b1a4d0964680f90a4b808f59a7b180dce9e`.
Branch: `chore/test-cleanup-p0-20261025`.

## Changes

1. SecretStore writes new files privately, then sets the existing container-readable final mode on the owned file descriptor. This removes dependence on process umask for creation and pending-secret replacement. Directory ownership/mode validation, symlink rejection, exclusive creation, sanitized errors, and atomic replacement remain in force.
2. The three-round pytest performance benchmark becomes manual-only. It reuses the normal isolated Redis wrapper and removes the retired crawler path from PYTHONPATH. Normal CI and merge-gate behavior are unchanged.
3. Remove the unused `frontend/package.test.json` manifest, which points at a nonexistent validation script. Existing `frontend/package.json` scripts and all business/security regressions remain unchanged.
4. Replace stale frontend-count and xdist-experiment instructions with current scoped/full verification boundaries.

## Executed evidence

Verification used an isolated source subset in the assistant container, **not a full repository checkout**. Original `local_full_runtime.py` and its actual `app_network_unit.py` dependency were checked against their Git blob hashes before editing. No stub dependency replaced those modules.

Runtime: Python 3.13.5. CI remains Python 3.12; these results are supplemental and do not establish CI-runtime parity.

- Six new SecretStore cases cover creation/replacement under umask 0027 and 0077, plus failure to set final permissions without false success or sensitive error disclosure.
- Two new benchmark-contract cases check manual-only triggering and reuse of the isolated Redis setup.
- Before the changes, all eight new cases failed for the intended reasons; after the changes, all eight passed.
- The six previously failing activation tests were copied unchanged to an external temporary harness and replayed with umask 0077. The original implementation failed all six; the patched implementation passed all six. Those copied tests are not added to the repository, avoiding duplicate regression coverage.
- Python syntax compilation and whitespace/diff checks passed.

Scoped test command:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  scripts/deploy/tests/test_secret_store_umask.py \
  ops/ci/tests/test_pytest_benchmark_scope.py --tb=short
```

## Not verified in this container

The complete activation module, the full repository suite, canonical CI on Python 3.12, live Redis/Docker behavior, production image/G1, and real deployments were not run. This record must not be reported as full CI acceptance or evidence of a measured whole-pipeline speedup.

The deletion removes an invalid entrypoint; it does not itself speed up Vitest. Removing benchmark PR triggers avoids additional three-round experiments for matching CI-script PRs; the normal backend test coverage is not reduced.

## Delivery boundary

This is a reviewable P0 cleanup candidate, not a merge/release approval. No main update, deployment, credential rotation, branch-protection change, or production-data access is part of this change. Vitest runtime splitting, BYOK dependency caching, and NewsHub business Scenario Matrix integration remain separate work.
