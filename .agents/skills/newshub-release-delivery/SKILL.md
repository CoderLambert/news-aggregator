---
name: newshub-release-delivery
description: "Coordinate explicitly authorized NewsHub push, PR, full CI, gated merge and main synchronization, directly or with optional delegates. Not for local commits, read-only reviews or production deployment."
---

# NewsHub release delivery

## Authorization

Follow [root rules](../../../AGENTS.md) and the current user instruction. The user's established “发布上传” request covers upload, PR, full CI, gated merge and local/remote main synchronization for the accepted feature; it is not permission to publish every implementation automatically. Newer no-push/no-merge/Draft-only/testing-deferred instructions narrow that scope. Production deployment, provider inference, migrations, release tags/registry publication and destructive Git operations require separate authorization.

## Execution choice

The current agent may execute authorized delivery directly or delegate bounded work when useful. Model, reasoning level and delegate count are task choices, not gates. Optional global templates do not override this project-local workflow. Keep clear ownership of mutable refs and reuse successful candidate-matching evidence; do not create competing test or merge writers.

Record absolute candidate worktree, branch/head/base, original task and PR/run IDs, authorized commit scope, local acceptance evidence, local main worktree/dirty paths and exclusions. If delegating, pass this context, coordinate overlapping writers and verify the returned refs and evidence. Unavailable optional agents do not block direct execution. Follow [handoff](../newshub-pr-handoff/SKILL.md); use [stage commit](../newshub-stage-commit/SKILL.md) for uncommitted changes before remote delivery.

## Completion criteria

1. Intended commits alone uploaded; existing PR reused or created with truthful scope and evidence. Check the user-acceptance gate before push, PR promotion or CI dispatch.
2. Current accepted head/base tested by canonical full CI and applicable merge-gate. Distinguish head, test merge and actual merged SHA; skipped/missing is not PASS. Recheck refs, reviews/conflicts/policies before expected-head-guarded PR merge; no admin bypass/direct unverified push main.
3. Remote main contains the verified PR merge; local main safely fast-forwards to it. Never create duplicate merge history. No reset/stash/autostash to hide user edits, no force push. Divergence, overlapping dirty paths, untracked collisions or uncertain ownership block synchronization. Unrelated dirty databases may remain untouched; do not read contents.
4. PR merge already pushes remote main: report main push NOT_NEEDED if it already contains the result. An additional non-forcing main push requires authorization and validated commits without unrelated history. Observe main-triggered CI separately from PR CI.
5. Report PR/CI URLs and actual states, head/base/testmerge/merged SHA, local/remote main refs, preserved dirty paths, upload/push results, risks and rollback. No default deletion of branches/worktrees or runtime data.

On failure preserve evidence, return PR to Draft before fixes and cancel only this task's redundant runs. Do not retry-until-green, weaken gates or implement unaccepted fixes during delivery. Return to local acceptance for new fixes. No production deployment is implied.

## Decision cases

- “发布上传”: perform the authorized gated delivery directly or with optional delegates, not production deployment.
- “只上传成 Draft，先别测试或合并”: honor the narrower scope; cancel/defer full checks, no merge.
- CI fails or base/head moves: retain evidence and block/revalidate; no stale-green merge.
- Unrelated dirty DB: preserve it. Overlapping paths or diverged main: report local-sync BLOCKED, not force/reset/stash.
