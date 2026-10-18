# NewsHub Test Rules

Read [root rules](../AGENTS.md) plus the rules for the implementation under test. This file is shared test guidance, explicitly read for `backend/api/tests/`, `frontend/tests/`, `ops/ci/tests/` and `scripts/deploy/tests/`; directory inheritance alone does not cover them.

- Regression tests should fail for the original defect and pass for the intended contract. Cover negative owner, version, retry/cancel and malformed-input cases when relevant. Update expectations only for an intentional reviewed behavior change, not to hide a bug.
- Reuse current fixtures and mock boundaries. Keep model/provider calls synthetic; tests of local HTTP/Proxy processes are not real-provider proof. Never read real keys or production data to make a test representative.
- Use disposable per-test/worker DBs, temporary directories, unique ports/Compose projects and bounded cleanup. A Git worktree does not isolate runtime resources. Do not copy live SQLite/WAL files or share mutable DB fixtures across workers.
- `conftest.py` provides `migrated_synthetic_db` / `copy_synthetic_db`; migrations under test still need their own isolated DB. `RUN_MAIN=true` is not credential isolation: Django can load `.env`, so inspect environment origin without printing secrets.
- CI uses Python 3.12, Node 22 and existing lockfiles. Do not silently invoke an incompatible system Python or reinstall into another worktree's shared venv/node_modules. Missing safe prerequisites: report NOT_RUN and use existing CI for remaining checks.
- Backend full coverage spans `tests/`, `backend/api/tests/`, `scripts/deploy/tests/`; the mixed serial/xdist algorithm is in `ops/ci/benchmark-xdist.sh`. Keep its serial-sensitive list and audit skip policy; do not impose a fixed passing count here.
- Frontend uses Vitest one-shot `test:run`, Testing Library and existing aliases. Prefer behavior assertions over snapshots of incidental markup.
- Do not run all expensive checks after every edit. First use affected tests, then the appropriate integration/CI gate; do not label a targeted run full coverage.
- Report raw exit status, test scope, failures/skips and exact SHA. Retries need a classified infrastructure cause, not repeated runs until a flaky result turns green.
- Structural Agent validation and synthetic checker tests do not validate Codex loading, rule following, code quality or token consumption. Those need separate real-session evidence.
