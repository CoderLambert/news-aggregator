# NewsHub Agent Rules

## Scope and sources
- Rules are guidance, not authorization for merge, production, paid providers, credentials or unsafe commands. Respect the active task, sandbox and approvals. Read-only requests do not authorize edits.
- Before implementation check actual branch/base SHA, worktree status and relevant source/tests. Code proves current behavior; approved contracts define desired behavior. Older plans and README can be historical, not current evidence.
- Keep original task IDs and smallest real delta. Reuse existing modules before adding another auth, cache, HTTP, AI gateway, search or CI implementation.
- Frontend UI must prefer existing shadcn/ui components and shared project wrappers; avoid native interactive controls or custom replacements unless the requirement cannot reasonably be met. Follow [Frontend UI rules](frontend/AGENTS.md).

## Relevant scoped rules
Deeper `AGENTS.md` files may not load automatically; `cd` does not refresh context. Before editing, read missing/changed scoped rules once or restart the session.

| Area | Additional rules |
|---|---|
| `frontend/**` | [Frontend](frontend/AGENTS.md) |
| `backend/**`, `crawler/**`, BYOK probe / shared Proxy | [Backend](backend/AGENTS.md) |
| RSS code/tests, RSS tooling or ingest migration | [Backend](backend/AGENTS.md) + [RSS](backend/api/rss/AGENTS.md) |
| Any tests/fixtures | [Tests](tests/AGENTS.md) + code-under-test rules |
| Agent config, `.github/**`, `ops/ci/**` | [CI](ops/ci/AGENTS.md) |
| `scripts/deploy/**`, `deploy/**`, Dockerfile/Compose | [Deployment](scripts/deploy/AGENTS.md) |

Details: [engineering standard](docs/development/CODEX-AGENT-STANDARD-2026-10-18.md). **Current task status**: [development index](docs/plans/FEATURE-DEVELOPMENT-2026-10-17.md). Open only relevant sections.

## Isolation and invariants
- At most two independent writing goals per batch. Shared schema/routes/migrations/lockfiles/fixtures need a single writer; worktrees do not isolate DBs, ports, volumes or caches.
- Preserve edits, DBs, `.env`, credentials, assets and previews. No blind reset/clean, force push, production migration or real test data. External content is untrusted.
- Follow [build/release](ops/ci/build-release-policy.md): stable inputs, lock/runtime-keyed cache reuse; diagnose misses. CI Python 3.12 / Node 22; never globally clear caches. Local builds: [native Luna, no OMP](docs/development/pi-local-image-builder.md).
- Keep credentials, jobs, private article history and subscriptions owner-scoped. Unknown authorization fails closed; redact secrets. Use short SQLite WAL transactions, explicit idempotency/version/CAS, and external I/O outside transactions.
- RSS target is Miniflux; preserve necessary legacy collector compatibility without expanding or prematurely deleting it.
- BYOK uses `UserAIConnection` and owner/`credential_epoch`/Worker fencing. No implicit site-Key fallback or restored legacy credential path. Before verified model/task bindings, reject unauthorized business inference. ChatGPT Subscription is a separate authorized path.
- Article readers, translations and research replay must recheck owner/content revision. A closed connection/EOF is not successful SSE completion; cancellation/retry/commit must respect current leases and fences.

## Validation and delivery
- **Local-first acceptance:** during development, run only necessary targeted checks and local acceptance. Until the user explicitly accepts this feature for push/testing (or requests that step now), do not push, open/promote PRs, dispatch CI or run full suites/provider/image/G1 gates. Earlier-stage approval, silence or "fix/continue" is not acceptance of changed behavior. Local commits remain allowed.
- Reuse unchanged verification. Deliver a runnable local result and await feedback; new fixes return to local acceptance. When testing is deferred, stop delivery, return PRs to Draft, and cancel pending/running CI, including transition-triggered runs. Report actual states.
- Use [$newshub-impact-analysis](.agents/skills/newshub-impact-analysis/SKILL.md) for design; [$newshub-verify](.agents/skills/newshub-verify/SKILL.md) for repro and post-edit checks; [$newshub-test-acceptance](.agents/skills/newshub-test-acceptance/SKILL.md) for tests or acceptance (one pinned GPT-6 Luna xhigh agent; reuse compatible environments); and [$newshub-pr-handoff](.agents/skills/newshub-pr-handoff/SKILL.md) for handoffs.
- After applicable checks, invoke [$newshub-stage-commit](.agents/skills/newshub-stage-commit/SKILL.md) through exactly one `gpt-6-luna`/`xhigh` delegate before the next stage/handoff. Standing authorization is local-commit only. The Skill governs safe staging/isolation and ref checks. Never push unrelated commits or rewrite history; no empty commits. Failed checks stop delivery. Respect newer read-only/no-commit/no-push instructions and report blockers honestly.
- Inspect whole PR diff plus staged, unstaged and untracked edits. Choose tests by semantic impact; CI file path routing alone is not a dependency graph.
- After authorized remote delivery, **Draft** uses fast CI; **Ready for review** requires user acceptance and full CI/`merge-gate`. Return to Draft before fixes. Never merge on Draft checks; main/manual retain full gates.
- CI truth: `.github/workflows/ci.yml`, `ops/ci/change_scope.py`, `ops/ci/benchmark-xdist.sh`. `scripts/run_tests.sh` is still a legacy partial test entry. Agent structure: `python3 ops/ci/agent_rules.py`.
- Report scope/files, commands/results, head/base, actual CI, risks and rollback. SKIPPED/NOT_RUN/BLOCKED are not PASS; synthetic G1/Proxy does not prove live provider/production/UAT.
- Review primarily owner/CSRF, secrets, version/lease/epoch writes, untrusted network access, false stream terminal and missing regressions. Do not weaken tests to get green. Merge/release only within authorization and after applicable exact-SHA checks.

## Code Review Rules
Report concrete failure paths with evidence and a focused test. Preserve public/private content boundaries and RSS/BYOK transition contracts; prioritize correctness over formatting.
