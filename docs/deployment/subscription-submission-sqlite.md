# Bounded SQLite submission retry

Base: e4739ce167054a8a7f3630637c47c2807c90d636 (PR49). This independent branch depends on PR49 and does not replace its scope. PR44 was read for lock-code/retry guidance only; none of its commits, worker changes or BYOK work were imported or modified.

Two first requests can each read that the unique task does not exist inside deferred SQLite transactions, then both fail their INSERT upgrades on shared-cache in-memory SQLite. The previous handler only looked for another committed task, so both could return task_storage_busy with zero rows.

Non-force, top-level submission now retries the complete DB-only atomic operation after rollback for explicit SQLite BUSY/LOCKED result codes, including extended codes found in the exception chain. At most six attempts use five jittered delays (20/40/80/160/320ms × 0.5–1.5; at most930ms extra backoff). Each attempt revalidates active connection/generation/model/user/source state and starts with fresh flags. A nested outer transaction, a non-SQLite vendor, unknown/non-lock error, or exhausted budget is not retried. Existing SQLite busy_timeout can still determine each DB-call wait, so this is an attempt/backoff bound, not a new total request deadline.

Force transactions are never replayed; the existing force attach-only lock fallback remains available only for explicit SQLite lock codes. Terminal reset/cancellation/lease/generation logic is retained. An owned shared lease is kept through rolled-back retry attempts and released only on final failure or when unused after commit. Provider dispatch remains outside the transaction. Existing process dispatch deduplication plus DB worker claim is retained: same-process concurrent calls submit one executor job; cross-process provider ownership remains enforced by the existing unique task/claim. This does not add a new global dispatcher.

Validation uses temporary databases and synthetic users/tokens; HF/Transformers offline, startup preload disabled, and fail-before-model-load/inference guards report zero calls. No real provider or user keys/DB were used.

- Before, exact e4739ce controlled race: shared-memory1 run failed with both INSERT lock errors and0 task rows; file SQLite/WAL1 run passed with one write conflict and1 task. File mode was actually verified as wal. The before probe wraps only the original target test's first task reads/INSERTs to enforce this schedule; it does not alter source.
- After: memory5/5 and WAL5/5 fresh-process controlled runs pass, exactly1 task, generation1, exactly1 same-process executor submission, no provider call. This is ten bounded runs, not a failure-rate estimate. Machine data: verification/subscription-submission-matrix.json.
- Initial subscription/connection/shared translation/mode/chat/SSE regression155 tests passed; the additional force-reset rollback test passed in the11-test focused submission suite. Existing owner/cancel/generation/shared-lease assertions remain intact. One dependency deprecation warning.
- Error tests verify finite exhaustion, lease lifetime through rollback, revalidation after generation change, non-lock/missing-code/no-SQLite rejection, nested transaction rejection and force non-replay. A failed force reset leaves generation/status rolled back and dispatch count unchanged.
- No migrations or deployment configuration changes. No full backend suite, container/runtime/production tests or remote server access. No CI was manually rerun, and prior PR49 failed/successful runs remain recorded; fresh CI is separate evidence.

Reproduce with an existing authorized dependency environment:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RUN_MAIN=true NEWS_CRAWL_ONLY=1 PYTEST_CURRENT_TEST=submission_verification PYTHONPATH=backend python -m pytest backend/api/tests/test_subscription_submission_locks.py backend/api/tests/test_subscription_recovery.py backend/api/tests/test_chatgpt_subscription.py backend/api/tests/test_shared_translations.py backend/api/tests/test_subscription_modes.py backend/api/tests/test_chat_context.py backend/api/tests/test_translation_sse.py -q
python scripts/verify_subscription_submission_sqlite.py --repetitions 5 --output /tmp/submission-matrix.json
```

The matrix script guards all model loading and asserts the actual journal mode before each controlled test. Provider work is explicitly forbidden by the race test. Deployment and merge remain separate authorized actions.

## Worker/SSE and source-lease review corrections

Review found that revalidation could silently change digest A to B while retaining lease A. Submission now freezes the initially validated digest; any later source change returns article_source_changed/409, before another task write/dispatch. The provided lease’s immutable news/source binding is also checked, covering an A→B change between lease claim and initial validation without changing token/expiry lifecycle guards. It releases only its old lease token. Two tests change the source during backoff, including a same-pk/new-token successor on source A and another source-B lease: no B task/provider dispatch is created and neither other owner is released.

PR-run38242291758 at b4c03cb failed the first-event progress assertion in the SSE test (880 passed/1 failed); push-run38242230999 passed. Both records remain. The failure occurred before the test's disconnect step, not because of disconnect. Its log only named OperationalError, so the exact CI SQL cannot be recovered from that log.

Bounded diagnosis used zero-model guards and isolated SQLite:
- Natural target: base e4739ce and head b4c03cb, each memory3 and WAL3 runs (12 total), all passed without captured SQL locks; this does not refute CI's failure.
- Exact snapshot controlled probes: e4739ce and detached b4c03cb, each provider-start UPDATE and progress UPDATE in memory/WAL once (8 runs). All four memory cases failed first-event assertions; SQL trace in test call phase, on chatgpt-translation worker, reported262 / SQLITE_LOCKED_SHAREDCACHE on api_chatgpttranslationtask UPDATE inside _mark_provider_started or _append_delta. Four WAL cases passed. Another four auxiliary probes used the b4 worktree after only the digest freeze edit; these are not part of the exact-snapshot comparison.
- The competing reader was released and joined before call completion; the reproduced SQL error preceded disconnect and teardown, so the controlled failure is not test-cleanup contention. This reproduces two possible failure stages, not proof which stage the original CI hit.

Only DB steps are retried: provider-start marker, progress append, completed-result commit and execution-guard reads reuse the same bounded, explicit SQLite lock classifier. Provider calls and the whole worker are never retried; claim, heartbeat, failure-state and cancellation lifecycle logic are not rewritten. Each attempt rechecks task/connection/generation/token/lease/source predicates; result persistence stays atomic with private/shared records. Progress/result rollback tests verify no duplicated delta or record; cancellation during retry blocks stale writes. Non-lock and missing-code worker errors still fail immediately. Logs expose fixed stage, sqlite_errorcode/name and attempt only, never source/SQL parameters/token.

The original SSE success assertions remain: first event progress, task running after disconnect, final succeeded result, exactly one fake provider invocation. Its finally now unconditionally releases the fake provider and waits for this job's dispatch key to clear, so assertion failure cannot leave a test worker running into later cleanup.

After-fix evidence:
- 49 focused subscription/race/worker/SSE tests passed, including the additional pre-validation source-binding case.
- Three controlled worker stages (provider start, progress and result commit) × memory/WAL ×3 repetitions =18 calls across6 fresh processes, all passed; actual journal mode asserted, zero model calls. Each contract finishes successfully after disconnect, one fake provider invocation, no duplicated progress. verification/subscription-worker-matrix.json.
- Final offline Python suite:891 passed,1 real-Docker-build test deselected,3 existing warnings. First collection attempt lacked crawler on PYTHONPATH and ran no tests; corrected to backend:crawler before the successful suite. Explicit model preload/load/inference guards remained zero. No manual CI rerun.
- Local environment Python3.14.8 / Django6.1 / SQLite3.53.1 differs from CI Python3.12.15 / Django6.1.2; results are not production failure-rate estimates. No production/container/server test or user data/key/model access. Main PR51 is not modified by this correction.

Re-run the worker matrix with:

```sh
python scripts/verify_subscription_submission_sqlite.py --suite worker --repetitions 3 --output /tmp/worker-matrix.json
```

This remains bounded task DB concurrency handling, not a change to lifecycle or permissions. Old failed and successful CI stays visible; a new pushed commit must be assessed separately before merge/deployment.

## PR49 merged-line claim and polling closure

Base22586f72d546a2c38c7c5e45497436e224014f2b was fetched and the owned worktree fast-forwarded; its tree1d511f49d08e401ba61c6b1da6edfcf0b89da53f equals reviewed9c131a3 (and the reported PR test merge). No merged content divergence was found. PR run38248490503/job114808336063 failed the first progress event (891 passed/1 failed), before disconnect. Push38248483757 succeeded, but does not cover that failure; neither run was manually retried.

A fixed controlled reader targeted the first task UPDATE in _run_persistent_task at this exact base. Memory1/1 failed with code262 and stack_run_persistent_task, atomic=False, during call before disconnect; WAL1/1 passed. This concretely reproduced the unprotected claim CAS path. It is not proof that the old CI hit this SQL, because its log contained only OperationalError and no stage/code.

The claim CAS is now a DB-only atomic operation with queued ownership/generation/connection/source revalidation on each bounded retry. A cancellation or superseding generation between attempts returns no claim/provider; failed writes roll back before retry and one run token wins. After-claim and article snapshots validate the claimed generation/run token instead of raw unprotected reads. Shared lease availability and task/job polling use bounded DB-only reads with unchanged user filters/expiry recovery predicates. No provider or whole-worker replay; no schema, permission or lifecycle redesign. Final worker exceptions now identify fixed stage/error type/SQLite code/name even outside retry wrappers; retry/error logs never include SQL/parameters/text/key/token.

One intermediate four-stage matrix had23 contracts pass and1 memory progress contract fail: worker progress retry succeeded but the SSE status read returnedtask_storage_busy. That is a separately observed polling-lock symptom, not the old worker exception. The intermediate record is preserved as verification/subscription-worker-before-poll-fix.json. A direct test verifies transient polling reads retry without dispatch and another user sees no task.

Final results:55 focused tests passed; offline Python suite897 passed,1 real-Docker-build test deselected,3 existing warnings; model preload/load/inference guards zero calls. Four stages (claim, provider start, progress, result commit) ×memory/WAL ×3 iterations =24 contracts passed across6 fresh processes with actual journal modes, first progress/disconnect-running/final success/one fake provider assertions intact. verification/subscription-worker-claim-matrix.json. Source/lease tests and force/cancellation/ownership checks remain present. No CI rerun, model/provider call, user DB/key, server/Docker gateway access, merge or deployment occurred. This commit is on fix/news-deployment-slow-network for PR49, not the merged PR50 branch.
