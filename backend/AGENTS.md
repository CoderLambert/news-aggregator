# NewsHub Backend Rules

Read [root rules](../AGENTS.md). These also apply when working on backend-related code under `crawler/`, `tools/byok_t00_probe/` or `ops/shared-litellm-proxy/`; no automatic cross-directory inheritance is assumed.

## Responsibilities
- Django/DRF views validate inputs, owner, Session/CSRF and public-mode gates; services own business actions; models/constraints own persistence. Reuse `public_policy.py`, `safe_http.py`, `http_execution.py` and `request_budget.py` instead of raw HTTP bypasses.
- Main Django data currently uses SQLite WAL; Miniflux's PostgreSQL is a separate engine database. Use short transactions, existing writer reservations/CAS and idempotency. Do not assume `select_for_update()` supplies SQLite row locks. Never hold a transaction over network/model calls or refresh an expired task's authority implicitly.
- Add forward migrations using the current graph; preserve model registration/re-exports and existing rows. Do not copy old BYOK migration numbers, edit applied migrations or treat a code revert as a database rollback.
- Keep `UserAIConnection`, neutral crypto, trusted gateway and `ai_worker_fencing` as the shared BYOK contracts. Model/task bindings must be explicit, versioned and owner-authorized. No restored legacy credential service, implicit paid call or site-key fallback.
- Keep ChatGPT Subscription isolated. Preserve the gateway's conservative terminal guard until a separately verified replacement exists. Cancellation is best effort for in-flight billing but must fence final persistence.
- Use `stored_readers.py`/RSS access and content versions for detail, translation, chat, research and TTS. Shared public translations never expose private results. Search vectors are rebuildable derived state, not the news database.
- Channel topics need trusted, versioned provenance; manual correction and private group ownership survive recomputation. Catalog GET paths must not trigger model/network work or incidental writes.
- For RSS or collector migration, read [RSS rules](api/rss/AGENTS.md). Do not expand the retired extraction stack or remove still-used legacy paths without the migration gate.

## Local verification
- Read [test rules](../tests/AGENTS.md). `settings.py` can load repository/backend `.env`; development mode alone does NOT isolate credentials. Use a credential-free disposable worktree and synthetic DB fixtures, not a running site's data.
- From the repository root, with the existing compatible venv and isolated test environment: `PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q backend/api/tests/test_ai_connections.py backend/api/tests/test_ai_worker_fencing.py` (select files for the actual change).
- Related tests live in `backend/api/tests/`, `tests/`, and `scripts/deploy/tests/`; the CI hybrid collects all three. Do not switch all tests to `-n auto`, share migration DBs or change the skip budget to hide a failure.
- Changed views/services can affect the frontend even without changing a URL/serializer file. Inspect corresponding parsers/types and add contract regressions; CI classification is not complete dependency analysis.

## Code Review Rules
Flag owner/version/terminal/network boundary violations with a negative test scenario. Distinguish implemented helper contracts from integrated consumers and real-environment acceptance. Consult the current task contract before enabling unfinished model bindings.
