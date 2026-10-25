# Pytest hybrid runner and manual performance benchmark

## Normal CI

The canonical workflow `.github/workflows/ci.yml` runs one full hybrid round (`CI_XDIST_REPEATS=1`) for each selected full backend gate. Draft checks remain scoped and do not invoke the full runner.

`ops/ci/benchmark-xdist.sh` owns the execution policy:

- State/seed-sensitive modules in its `SERIAL_FILES` array run serially. Keep this as the single source of truth instead of copying a file count into documentation.
- The remaining files use two isolated xdist workers with `--dist=loadfile` and `--max-worker-restart=0`.
- All three test roots are covered: `tests/`, `backend/api/tests/`, and `scripts/deploy/tests/`.
- Collected and executed test identities, terminal outcomes, and JUnit reports are reconciled. Skip policy lives in `xdist_summary.py`; do not replace the identity audit with a fixed passing count.

The existing isolated Redis wrapper prepares the translation transport for the whole round. Production image and G1 checks remain in the normal workflow and are not replaced by this benchmark.

## Manual profiling

`.github/workflows/ci-pytest-benchmark.yml` is **workflow_dispatch only**. It runs three full rounds with the same isolated Redis wrapper when an operator explicitly requests profiling. It does not automatically queue three more rounds when a PR changes CI scripts, and it is not a merge gate.

The benchmark shares the dedicated backend runner with normal CI. Run it only when investigating performance or validating a deliberate parallelism change; do not use it for every development iteration.

## Safety and history

The original unrestricted parallel experiment failed seed-sensitive tests. That is why the hybrid serial list remains authoritative. Do not remove entries or increase workers without fixture-isolation evidence and repeated passing runs.

Current tooling versions are pinned by the runner script. Historical pass counts and experiment timings are not acceptance criteria for new commits. Report the exact commit, selected scope, raw exit status, failures/skips, and observed timings. No live providers, production data, or production credentials are required.
