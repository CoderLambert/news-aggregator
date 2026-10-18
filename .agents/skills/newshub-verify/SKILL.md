---
name: newshub-verify
description: "Verify changed NewsHub code, tests, migrations, dependencies, CI or Agent rules before reporting readiness. Not for read-only questions; docs-only edits need link/fact checks, not product suites."
---

# NewsHub verification

Reuse unchanged rules already loaded; otherwise read [root rules](../../../AGENTS.md), [test rules](../../../tests/AGENTS.md), relevant module rules and the [CI guide](../../../ops/ci/change-routing.md). Commands are repository-relative unless a subshell changes directory.

1. Determine the real diff: PR merge-base to head plus staged, unstaged and untracked edits (`git status --short`, `git diff`, `git diff --cached`, `git ls-files --others --exclude-standard`). Include deleted/renamed paths. Local edits do not appear in remote CI until committed/pushed.
2. Check Python/Node/venv/dependency availability against CI and lockfiles. Use a credential-free worktree with disposable DB/ports; do not read/print secrets, copy real `.env`, install over shared caches or trigger real network/model/production work.
3. Select actual affected tests and negative cases by behavior, not only file names. Use existing tests and fixtures; broaden for owner/CSRF, versions, content, migrations, terminal/streaming or API consumers. Do not invent a `--scope` interface for `scripts/run_tests.sh`.
4. On a cheaply reproducible bug, demonstrate the original defect with a focused failing-before test or executable repro, then passing-after evidence. Do not force slow/flaky, production-only or mock-only tests; state when pre-fix reproduction is NOT_RUN and use the nearest safe check.
5. When claiming a performance change, record the metric and user-facing end-to-end path, data/load/build and cache conditions, error count and work actually completed. Compare repeated equivalent runs (alternating baselines when practical); report sample size, median/range and limiting bottleneck. If unmeasured or not comparable, label INCONCLUSIVE, not faster.
6. Execute feasible one-shot checks, preserve exit status and bounded logs. Example AI backend invocation: `PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q backend/api/tests/test_ai_connections.py backend/api/tests/test_ai_worker_fencing.py` (only in the isolated environment). Example frontend: `(cd frontend && npm run typecheck && npm run lint && npm run test:run -- tests/pages/AIModelSettingsPage.test.tsx tests/services/aiConnectionsApi.test.ts)`. For other tasks use their real tests; build when the shipped UI/bundle is affected.
7. For Agent/rule changes run `python3 ops/ci/agent_rules.py` and `python3 -m unittest discover -s ops/ci/tests -p 'test_agent_rules.py'`. These are static/regression checks, not a Codex behavior benchmark.
8. Predict CI from `.github/workflows/ci.yml` / `ops/ci/change_scope.py` only, without copying a rule table. A missing PR test run is not PASS. If semantic risk needs additional checks, request/run the authorized manual full workflow instead of bypassing or relabeling jobs.
9. Before readiness, inspect actual selected jobs and failures for the delivered head/base, not a previous commit's green badge. Full CI includes the existing three backend roots, coverage reconciliation, image/G1 and frontend checks when selected. Do not retry to hide flakiness or weaken gates.

Output: tested SHA/dirty state; command, scope and PASS/FAIL/SKIPPED/NOT_RUN, including red/green defect evidence or performance limits when relevant; actual CI proof, risks and next gate. Real providers, production and human UAT remain separate. Small changes do not require all suites locally when the applicable CI provides the remaining evidence.
