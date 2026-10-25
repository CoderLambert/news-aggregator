# NewsHub Deployment Rules

Read [root rules](../../AGENTS.md), [CI rules](../../ops/ci/AGENTS.md) and [test rules](../../tests/AGENTS.md). These apply to `deploy/`, Dockerfile/Compose, release scripts and their tests as well as this directory.

- Keep implementation/synthetic release tests separate from operator actions. Do not deploy, migrate real data, change DNS/TLS, stop services, rotate credentials or remove volumes without the authorization for that action.
- Preserve release identity, same-SHA image/static assets, non-root runtime, backup/restore checks and active-volume protection. Code revert is not schema/data rollback.
- Build/tests may use only explicitly named disposable resources. No global prune, cache replacement or production endpoints. Dry-run can still have effects: read the existing script contract before invoking it.
- Validate shell syntax and the relevant `scripts/deploy/tests/` regression. Keep production image and isolated G1 checks in the canonical workflow; do not substitute mocks for actual G1.
- G1 uses synthetic fixtures (including its SSE probe); it does not prove real paid upstream streaming, production readiness or manual browser UAT.
- Final release requests require a full, exact-SHA workflow even if ordinary path routing would skip a stack. Keep the documented manual `workflow_dispatch` path; do not weaken path filtering or manufacture successful required checks.
- Preserve the accepted local NewsHub runtime instead of replacing it with Compose defaults: reuse its database, environment, project and published port unless the user requests a change. The current manual-acceptance runtime is `newshub-local-main` on `127.0.0.1:19527`, with `PUBLIC_SITE_MODE=full`, `PUBLIC_AI_ENABLED=1`, `AI_BYOK_ENABLED=1`, `CHATGPT_AUTH_MODE=local_oss` and `CHATGPT_PLAN_USAGE_ENABLED=1`. Its `DJANGO_CSRF_TRUSTED_ORIGINS` must include the active exact loopback origin so ChatGPT Subscription follows the address in the browser. Inspect these effective settings before and after recreation; never silently fall back to disabled defaults or another database.

## Code Review Rules
Flag unsafe resource targeting, non-atomic backup/restore, missing version identity and loss of rollback safeguards. Separate test evidence from operator acceptance in the handoff.
