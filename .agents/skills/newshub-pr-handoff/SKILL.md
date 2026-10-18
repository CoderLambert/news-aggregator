---
name: newshub-pr-handoff
description: "Prepare a requested NewsHub PR review or implementation handoff with exact-SHA evidence, risks and rollback. Does not authorize committing, merging or deploying; not for ordinary code search."
---

# NewsHub PR handoff

Read [root rules](../../../AGENTS.md) and the applicable module review rules. Reuse existing task/PR IDs instead of creating duplicates.

1. Inspect the final diff, base/head and dirty state. Exclude unrelated edits, runtime databases, credentials and generated output. Recheck base movement before any authorized merge.
2. Review concrete owner/CSRF/feature, version/lease/epoch, API/DTO/SSE, network, migration and rollback failure scenarios. Cite file paths, impact and minimal reproduction for findings; avoid style-only bot churn.
3. Reuse verified evidence from [$newshub-verify](../newshub-verify/SKILL.md), but verify it belongs to the delivered revision. Static Agent checks, synthetic Proxy/G1, live provider calls and production UAT are different claims.
4. For each finding, state fixed with regression, not applicable with evidence, or unresolved. Do not mark review threads resolved merely because tests pass.
5. Prepare a concise PR/body update: original task; behavior change; files/contracts; tests and CI URLs/SHA; known limitations; code/config rollback and any separate data rollback requirements.
6. Only perform writes already authorized by the current task. Instructions to summarize/review do not authorize git commit, push, merge, release, database migration or paid calls. For an authorized merge, selected required checks must be successful for the current head and compatible base; docs-path skip is an explicit exception, never fabricated PASS.

Report completion by layer: implemented, automatically tested, integrated, real-environment accepted. Do not collapse a helper-only or fail-closed transitional implementation into an end-to-end feature.
