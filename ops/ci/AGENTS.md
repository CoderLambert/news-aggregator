# NewsHub CI Rules

Read [root rules](../../AGENTS.md). These rules also apply to `.github/**`, root Agent rules and `.agents/**`, even when the file is outside `ops/ci/`.

- Workflow triggers and Job conditions live in `.github/workflows/ci.yml`; `change_scope.py` owns path classification. Read [routing guide](change-routing.md), then inspect actual code. Do not duplicate classification tables in Skills or weaken docs-only/unknown-path behavior.
- Keep the existing frontend listener without DinD access, backend private socket/volumes and trusted same-repo/non-Draft policy. No production secrets, host Docker socket, global prune or service restart while a job is busy.
- Keep `benchmark-xdist.sh`'s serial-sensitive modules and limited parallel remainder, dynamic collected/executed identity reconciliation and JUnit checks. Test counts and approved skips belong to the existing audit implementation, not Agent files.
- Route ordinary frontend/backend changes as before. Agent/CI root changes require both stacks; child rules follow their existing path. Run the dependency-free `agent_rules.py` in frontend fast preflight and existing backend unittest discovery so a frontend-only rule edit cannot miss validation.
- Update classifier tests, CI contracts, release-operation workflow contracts and the routing guide together only when the routing contract actually changes. Do not change CI for ordinary feature development.
- Keep manual `workflow_dispatch` as full verification. A skipped/missing job is not PASS; distinguish intentional path suppression from detection/Runner failure. A failure in the changes job cannot be reported as successful routing fallback.
- For review, verify all required selected jobs for the exact head SHA and current base; if the base moved, revalidate the merged result. Do not merge merely because GitHub says mergeable or one job is green.
- Validate Agent files with `python3 ops/ci/agent_rules.py`; regressions: `python3 -m unittest discover -s ops/ci/tests -p 'test_agent_rules.py'`. New owned rules/Skills must be registered and covered by negative tests. These checks are structural, not proof of model compliance or token savings.

## Code Review Rules
Flag loss of coverage, unsafe skip rules, untrusted Runner execution, leaked secrets or weakened gate semantics. Reuse the existing Actions workflow and dependencies rather than adding a separate Agent CI service.
