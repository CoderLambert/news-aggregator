---
name: newshub-verify
description: "Verify changed NewsHub code, tests, migrations, dependencies, CI or Agent rules before reporting readiness. Not for read-only questions; docs-only edits need link/fact checks, not product suites."
---

# NewsHub verification

Reuse unchanged rules already loaded; otherwise read [root rules](../../../AGENTS.md), [test rules](../../../tests/AGENTS.md), relevant module rules and the [CI guide](../../../ops/ci/change-routing.md). Commands are repository-relative unless a subshell changes directory.

1. Determine the real diff: PR merge-base to head plus staged, unstaged and untracked edits (`git status --short`, `git diff`, `git diff --cached`, `git ls-files --others --exclude-standard`). Include deleted/renamed paths. Local edits do not appear in remote CI until committed/pushed.
2. Check Python/Node/venv/dependency availability against CI and lockfiles. Use a credential-free worktree with disposable DB/ports; do not read/print secrets, copy real `.env`, install over shared caches or trigger real network/model/production work.
3. Select actual affected tests and negative cases by behavior, not only file names. Use existing tests and fixtures; broaden for owner/CSRF, versions, content, migrations, terminal/streaming or API consumers. Do not invent a `--scope` interface for `scripts/run_tests.sh`.
4. Execute feasible one-shot checks, preserve exit status and bounded logs. Example AI backend invocation: `PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q backend/api/tests/test_ai_connections.py backend/api/tests/test_ai_worker_fencing.py` (only in the isolated environment). Example frontend: `(cd frontend && npm run typecheck && npm run lint && npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts)`. For other tasks use their real tests; build when the shipped UI/bundle is affected.
5. For Agent/rule changes run `python3 ops/ci/agent_rules.py` and `python3 -m unittest discover -s ops/ci/tests -p 'test_agent_rules.py'`. These are static/regression checks, not a Codex behavior benchmark.
6. Predict CI from `.github/workflows/ci.yml` / `ops/ci/change_scope.py` only, without copying a rule table. A missing PR test run is not PASS. If semantic risk needs additional checks, request/run the authorized manual full workflow instead of bypassing or relabeling jobs.
7. Before readiness, inspect actual selected jobs and failures for the delivered head/base, not a previous commit's green badge. Full CI includes the existing three backend roots, coverage reconciliation, image/G1 and frontend checks when selected. Do not retry to hide flakiness or weaken gates.

Output: tested SHA/dirty status; command, scope and PASS/FAIL/SKIPPED/NOT_RUN for each check; actual CI evidence; uncovered behavior and next required gate. Real providers, production and human UAT remain separate. Small changes do not require all suites locally when the applicable CI provides the remaining evidence.
