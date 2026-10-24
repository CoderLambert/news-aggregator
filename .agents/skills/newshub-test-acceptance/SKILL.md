---
name: newshub-test-acceptance
description: "Run requested NewsHub tests or local acceptance through one reusable GPT-6 Luna xhigh task."
---

# NewsHub test acceptance

Use whenever the user asks to test, verify, reproduce, regression-check or locally accept a NewsHub change. Routine planning questions about tests do not trigger this Skill.

## Delegate

The main Agent must spawn exactly one `newshub-test-acceptance-luna` task agent. Its persistent definition pins `openai-codex/gpt-6-luna` with `xhigh` reasoning. Do not substitute another agent/model, split one acceptance run among multiple agents, or rerun the same successful checks in the main Agent. If that agent or configuration is unavailable, stop without downgrade.

Provide the absolute repository/worktree, requested behavior and acceptance boundary, branch plus exact candidate SHA or dirty-file state, applicable checks already run, exclusions, and whether provider, image, full-suite, CI or production gates have explicit authorization. The delegate must read the repository test and verification rules before acting.

## Reuse the test environment

Prefer reuse over installation or rebuilding, in this order:

1. Candidate-matching successful evidence that still covers the unchanged code and configuration.
2. An already running isolated test service owned by this task, after verifying its source revision, command, ports and synthetic data boundary.
3. Existing compatible repository environments (`backend/venv`, `frontend/node_modules`) or a previously built local image whose dependency inputs and runtime versions match.
4. A content-addressed environment under `${NEWSHUB_TEST_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/newshub-test-acceptance}` keyed by Python/Node versions and relevant lockfile hashes, shared read-only across worktrees where practical.

The shared test home may contain dependency environments, non-secret manifests and bounded logs. It must not contain copied `.env` files, credentials, user databases, private content or mutable business state. Put disposable databases, browser profiles, ports and run state in a unique per-run directory. Record enough manifest data to reject stale or incompatible caches; a matching directory name alone is not proof.

Never run `pip install`, `npm ci`, package downloads, Docker pulls or image rebuilds when a compatible environment already exists. If no compatible environment exists, create it once in the shared test home only when the requested gate and network/build authorization allow it; otherwise report `BLOCKED` with the exact missing prerequisite. Do not mutate host runtimes or another worktree's environment.

## Execute and report

- Inspect branch, HEAD, staged, unstaged and untracked changes before selecting checks. Preserve user changes.
- Choose the smallest semantically sufficient tests, including meaningful negative cases. A bug fix should use the failing-before/passing-after regression when safely available.
- Use synthetic credentials and disposable resources. Do not read real `.env` files or call providers, production, full suites, CI, image or G1 gates without their explicit approval.
- Exercise the changed surface, not only its tests. Use a real browser for UI, the actual command for CLI/TUI, or a focused runtime smoke for backend behavior.
- Do not weaken tests, install into shared project environments, or edit production code unless implementation was also explicitly requested.
- Report candidate SHA/dirty state; reused environment identity and compatibility evidence; exact commands, scope, exits and warnings; PASS/FAIL/BLOCKED/NOT_RUN separately; cleanup; risks and the next authorized gate. Skipped or synthetic checks are never provider, production, CI or human-UAT proof.

Reusable invocation: `/skill:newshub-test-acceptance`, or ask “用 Luna xhigh 验证这次修改”。
