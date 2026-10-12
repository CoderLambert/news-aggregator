# Subscription full-translation recovery

This feature persists the lifecycle of each user's full-article ChatGPT subscription translation in `ChatGPTTranslationTask`. It reuses the existing two-worker executor, shared-translation publication lease, and translation SSE protocol; it does not add a general-purpose queue, usage limit, fee ledger, or provider fallback. The implementation follows ADR-026 and `contracts/SUBSCRIPTION-TRANSLATION-RECOVERY.md`.

## Lifecycle and recovery

A task is unique per owner, subscription connection, article, and source digest. Its stored connection generation and selected model are snapshots, independent from the task generation. Repeated submissions attach to the existing task. `force=true` is the only retry operation: it increments the task generation and clears prior progress/result/error only after a task is terminal. An active task still attaches when force is requested.

Executor threads claim only queued rows with a conditional `queued -> running` update; a queued task therefore does not hold a run lease while waiting for a worker slot. Before entering token refresh or model translation, the worker commits `provider_started=true`. A valid run token and a 60-second private lease fence progress, heartbeats, cancellation, and finalization; heartbeats run every 20 seconds and cannot extend an expired lease. An expired unstarted run returns to `queued`; an expired started run becomes `interrupted` and is never replayed automatically. Old handles remain bound to their captured task generation and cannot read a retried generation's progress or result.

Successful private and existing shared translation publication are committed with the task result in one transaction. The transaction first performs the private task CAS to acquire SQLite's write reservation, then revalidates the owner, connection/model snapshot, article digest, and shared lease. Cancellation similarly CASes the requested private generation before finishing only its stored shared lease token. A stale worker's cleanup must win its original task-generation/run-token CAS before it may finish a shared lease.

## API and privacy

The authenticated owner endpoints are:

- `GET /api/chatgpt-subscription/jobs/<job_id>/`
- `POST /api/chatgpt-subscription/jobs/<job_id>/cancel/` with a strict integer `generation` from 1 through 9223372036854775807.

The GET and cancel DTO contains only `id`, `status`, `generation`, `progress`, `result`, `error_code`, `error_message`, `updated_at`, and `finished_at`. Nonowners receive 404; normal session authentication and CSRF checks apply. Stale cancellation generations return 409 without changing either lease. These responses and translation SSE responses use `Cache-Control: no-store`. Translation SSE retains progress/complete/error payloads, adds `Job-ID`, supports reattachment to persisted state, and does not cancel the worker when a subscriber disconnects.

No provider access token, refresh token, shared lease token, or raw provider exception is stored in task state or returned in its DTO. Worker logs record exception type only. Cancellation and snapshot guards run before credential decryption, discovery GETs, token/model POSTs, deltas, completion, and final save. An HTTP operation already in progress may finish within the existing timeout, but the cancelled or stale run cannot continue to later I/O or persist a result.

## Verification boundary

The added recovery tests use fake provider responses only. Real website OAuth and model requests remain **NOT_RUN** and **EXTERNAL_BLOCKED**: required hosted OAuth and subscription-plan approvals and their exact client/redirect/protocol terms have not been provided. Website mode remains fail-closed. No deployment, real provider call, or migration against the user's database is part of this implementation; migration `0030` only creates the new task table on a fresh/isolated database. Source preparation is not a claim that the overall G3 release or production acceptance has passed.
