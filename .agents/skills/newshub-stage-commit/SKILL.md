---
name: newshub-stage-commit
description: "Commit and safely push a completed NewsHub feature or independently reviewable stage through the required Luna xhigh delegate."
---

# NewsHub stage commit

Use after a feature or independently reviewable implementation/documentation stage is complete and its applicable minimum checks pass, before the next stage or handoff. This grants a local commit and ordinary GitHub push for that stage only. A newer read-only/no-commit/pause instruction blocks the commit; no-push/local-only blocks only the push. No empty commits: failed required checks mean incomplete, and a recovery patch does not replace the commit.

## Delegate

Unless the request includes `ROLE=delegated-stage-commit`, the main Agent must spawn exactly one child with `fork_turns=none`, model `gpt-6-luna`, and `reasoning_effort=xhigh`. Provide the absolute worktree, task/stage ID and boundary, allowed files or hunks and exclusions, expected branch/base SHA, applicable checks and candidate-bound evidence, and commit/push authorization to the current work branch or an isolated task branch described below. If Luna, xhigh, or delegation is unavailable, stop without downgrade. A worker with the role executes directly and never re-delegates.

## Commit the stage

Read applicable `AGENTS.md` files. Confirm worktree, branch and exact base SHA match the handoff; inspect staged, unstaged and untracked changes. If they changed, there are unrelated pre-staged edits, a conflict, a suspected secret, or uncertain ownership, preserve the work and report the blocker. Never reset, clean, stash, amend, rebase, merge or force-push.

Stage only authorized files or reviewed hunks; never use `git add .` or `git add -A`. Split unrelated hunks, or stop if they cannot be separated. Inspect status, staged diff/stat and `git diff --cached --check`; review for secrets without printing suspected values. Reuse validation only while it still matches the candidate, run missing applicable checks, and always run `git diff --check`. A required failure stops before commit.

Before committing, inspect branch, HEAD, upstream, GitHub remotes, and incoming/outgoing commits. Safely fetch or query actual refs; do not rely on stale tracking data. Do not print remote URLs or credential-bearing errors. Without an upstream, use `git push -u <remote> <branch>` only for a non-detached branch and one unambiguous GitHub remote. Do not push a default/base branch without explicit authorization or include unrelated outgoing commits.

Create a clear stage-specific commit. If the current branch has unrelated or unclear outgoing commits, do not push or rewrite its existing history. When push is authorized, use a separate worktree and task branch from the freshly checked GitHub base, transplant only this stage commit or exact authorized hunks, inspect the resulting task-only diff, and rerun applicable checks. A no-push/local-only instruction still allows the stage commit but prohibits delivery branches and pushes.

Push only with an ordinary, non-forced push after confirming the outgoing range is authorized. Genuine network unavailability leaves the local commit unsynced. Authentication denial, divergence, non-fast-forward, and other refusals are specific blockers; keep the local commit and do not force, merge, or rebase. After a successful push, query the remote ref and confirm it equals HEAD.

Report commit SHA and subject, files/hunks, checks and results, actual remote branch/ref verification or blocker, and remaining dirty or excluded work.
