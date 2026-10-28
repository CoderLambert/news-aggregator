---
name: newshub-stage-commit
description: "Locally commit a completed NewsHub stage directly or with optional delegation; push only after the user acceptance gate."
---

# NewsHub stage commit

Use after a feature or independently reviewable implementation/documentation stage is complete and its applicable minimum checks pass, before the next stage or handoff. This grants a local commit for that stage only. Default to local-only delivery. A push, PR creation/promotion or CI dispatch must wait for the root AGENTS.md user-acceptance gate; this Skill does not supply that authorization. An earlier stage's acceptance does not carry over to new or changed behavior. A newer read-only/no-commit/pause instruction blocks the commit; no-push/local-only blocks only the push. No empty commits: failed required checks mean incomplete, and a recovery patch does not replace the commit.

## Execution choice

The current agent may commit directly after the checks below. Delegate when useful; no particular model, reasoning level or delegate count is required. Keep a clear writer for the index and refs so executors do not race.

Record the absolute worktree, task/stage ID, allowed files or hunks and exclusions, expected branch/base SHA, candidate-bound check evidence and local-only or user-accepted push authorization. If delegating, pass this context and verify the resulting commit and remaining dirty state before handoff. Unavailable optional agents do not block direct execution.

## Commit the stage

Read applicable `AGENTS.md` files. Confirm worktree, branch and exact base SHA match the recorded task context; inspect staged, unstaged and untracked changes. If they changed, there are unrelated pre-staged edits, a conflict, a suspected secret, or uncertain ownership, preserve the work and report the blocker. Never reset, clean, stash, amend, rebase, merge or force-push.

Stage only authorized files or reviewed hunks; never use `git add .` or `git add -A`. Split unrelated hunks, or stop if they cannot be separated. Inspect status, staged diff/stat and `git diff --cached --check`; review for secrets without printing suspected values. Reuse validation only while it still matches the candidate, run missing applicable checks, and always run `git diff --check`. A required failure stops before commit.

Before committing, inspect branch, HEAD, upstream, GitHub remotes, and incoming/outgoing commits. Safely fetch or query actual refs; do not rely on stale tracking data. Do not print remote URLs or credential-bearing errors. Without an upstream, use `git push -u <remote> <branch>` only for a non-detached branch and one unambiguous GitHub remote. Do not push a default/base branch without explicit authorization or include unrelated outgoing commits.

Create a clear stage-specific commit. If the current branch has unrelated or unclear outgoing commits, do not push or rewrite its existing history. When push is authorized, use a separate worktree and task branch from the freshly checked GitHub base, transplant only this stage commit or exact authorized hunks, inspect the resulting task-only diff, and rerun applicable checks. A no-push/local-only instruction still allows the stage commit but prohibits delivery branches and pushes.

Push only after the user has accepted this feature for remote delivery (or explicitly requested this push now), with an ordinary, non-forced push and an authorized outgoing range. Do not push just to obtain CI evidence before that acceptance. Genuine network unavailability leaves the local commit unsynced. Authentication denial, divergence, non-fast-forward, and other refusals are specific blockers; keep the local commit and do not force, merge, or rebase. After a successful push, query the remote ref and confirm it equals HEAD.

Report commit SHA and subject, files/hunks, checks and results, actual remote branch/ref verification or blocker, and remaining dirty or excluded work.
