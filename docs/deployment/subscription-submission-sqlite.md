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
