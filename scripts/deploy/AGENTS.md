# NewsHub Deployment Rules

Read [root rules](../../AGENTS.md), [CI rules](../../ops/ci/AGENTS.md) and [test rules](../../tests/AGENTS.md). These apply to `deploy/`, Dockerfile/Compose, release scripts and their tests as well as this directory.

- Keep implementation/synthetic release tests separate from operator actions. Do not deploy, migrate real data, change DNS/TLS, stop services, rotate credentials or remove volumes without the authorization for that action.
- Preserve release identity, same-SHA image/static assets, non-root runtime, backup/restore checks and active-volume protection. Code revert is not schema/data rollback.
- Build/tests may use only explicitly named disposable resources. No global prune, cache replacement or production endpoints. Dry-run can still have effects: read the existing script contract before invoking it.
- Validate shell syntax and the relevant `scripts/deploy/tests/` regression. Keep production image and isolated G1 checks in the canonical workflow; do not substitute mocks for actual G1.
- G1 uses synthetic fixtures (including its SSE probe); it does not prove real paid upstream streaming, production readiness or manual browser UAT.
- Final release requests require a full, exact-SHA workflow even if ordinary path routing would skip a stack. Keep the documented manual `workflow_dispatch` path; do not weaken path filtering or manufacture successful required checks.

## Code Review Rules
Flag unsafe resource targeting, non-atomic backup/restore, missing version identity and loss of rollback safeguards. Separate test evidence from operator acceptance in the handoff.
