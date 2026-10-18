---
name: newshub-impact-analysis
description: "Analyze complex NewsHub architecture and change impact, including read-only cross-module design reviews, API/schema, RSS/BYOK, concurrency and security; exclude trivial lookups and simple edits."
---

# NewsHub impact analysis

Reuse unchanged rules already loaded; otherwise read [root rules](../../../AGENTS.md) and the relevant module rules. Complex read-only review is allowed but never authorizes writes. Paths are repository-relative.

1. Confirm the requested goal/authorization, actual base SHA and existing dirty work. Preserve task IDs; do not open a replacement planning system.
2. Inspect relevant entry points, callers, consumers and existing tests. Code/tests show current behavior; the approved task contract supplies the desired behavior. Do not treat old completion tables as current facts.
3. Trace data owner, article/source version, API/DTO/SSE contract, DB/network boundaries and background task authority. For RSS use `backend/api/rss/`; for BYOK inspect `ai_execution.py`, explicit binding and the shared worker fence; do not infer end-to-end readiness from helper tests.
4. For risky cross-boundary changes, name the 1–2 falsifiable assumptions that would make them safe. Inspect non-obvious consumers beyond imports (DTO, persisted state, retries, other workers, viewer caches). Give file/test evidence and the cheapest real negative or runtime proof. Label each assumption SOURCE_ONLY, PROVEN, UNPROVEN or NOT_RUN; an unrun test or convincing description is not proof.
5. Check mature existing modules/dependencies before adding new infrastructure. Propose the smallest compatible delta, not a broad rewrite.
6. Identify shared writers: schema/migrations/routes/lockfiles/fixtures. Parallelize at most two independent writing goals with separate worktrees AND isolated runtime resources; otherwise sequence them.
7. Read CI classification only when needed. Do not infer semantic API compatibility from directory names; name additional cross-stack tests for real shared behavior.

Return one compact plan: goal/base, affected files/contracts, critical safety assumptions and evidence level, cheapest executable negative checks, ownership/order, blockers. This Skill only analyzes; it does not independently authorize edits, merges, provider calls or deployment. Continue implementation when the current user task already authorizes it.
