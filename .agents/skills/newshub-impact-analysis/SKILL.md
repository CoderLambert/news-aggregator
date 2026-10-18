---
name: newshub-impact-analysis
description: "Analyze complex NewsHub architecture and change impact, including read-only cross-module design reviews, API/schema, RSS/BYOK, concurrency and security; exclude trivial lookups and simple edits."
---

# NewsHub impact analysis

Reuse unchanged rules already loaded; otherwise read [root rules](../../../AGENTS.md) and the relevant module rules. Complex read-only review is allowed but never authorizes writes. Paths are repository-relative.

1. Confirm the requested goal/authorization, actual base SHA and existing dirty work. Preserve task IDs; do not open a replacement planning system.
2. Inspect relevant entry points, callers, consumers and existing tests. Code/tests show current behavior; the approved task contract supplies the desired behavior. Do not treat old completion tables as current facts.
3. Trace data owner, article/source version, API/DTO/SSE contract, DB/network boundaries and background task authority. For RSS use `backend/api/rss/`; for BYOK inspect `ai_execution.py`, explicit binding and the shared worker fence; do not infer end-to-end readiness from helper tests.
4. Check mature existing modules/dependencies before adding new infrastructure. Propose the smallest compatible delta, not a broad rewrite.
5. Identify shared writers: schema/migrations/routes/lockfiles/fixtures. Parallelize at most two independent writing goals with separate worktrees AND isolated runtime resources; otherwise sequence them.
6. Read CI classification only when needed. Do not infer semantic API compatibility from directory names; name additional cross-stack tests for real shared behavior.

Return one compact plan: goal/base, affected files and contracts, preserved invariants, test/negative cases, ownership/order, concrete blockers. This Skill only analyzes; it does not independently authorize edits, merges, provider calls or deployment. Continue implementation when the current user task already authorizes it.
