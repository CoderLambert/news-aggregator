# T00 SDK and Proxy probe

The isolated `probe.py` uses the official OpenAI and Anthropic SDKs, pinned LiteLLM v1.104.2, an internal-only synthetic HTTP upstream, and temporary Postgres storage. It never calls a real provider or reads an existing provider key. `deepseek_smoke.py` is a separate, opt-in direct diagnostic described below.

## Credential contract covered

- Direct OpenAI SDK calls use the synthetic provider key as Authorization: Bearer; the probe does not add x-api-key.
- Direct Anthropic Messages calls use the provider key through the SDK api_key option, which sends x-api-key.
- Proxy SDK calls use a generated synthetic project virtual key in Authorization only. The provider key is sent per request in the official SDK's supported body field api_key (extra_body).
- The guarded Proxy loads the read-only `proxy_callback.py` CustomLogger instance. Its `async_pre_call_hook` requires a nonempty top-level `api_key` in LiteLLM's pre-call `data` mapping for `acompletion`, `aresponses`, and `anthropic_messages`; that mapping is not guaranteed to be the original HTTP request body. It rejects missing, null, empty, whitespace-only, non-string, metadata-only, and header-only credentials with HTTP 400 before routing.
- The main guarded fixture denies Chat streaming. A separate `native-stream` Proxy profile uses the same callback and model setup to exercise Responses and Messages native streaming with complete, EOF, incomplete, SSE-error, and client-cancel cases. Chat streaming remains rejected before routing.
- Both Proxy configs set `forward_client_headers_to_llm_api` and `forward_llm_provider_auth_headers` to false. Generated project keys contain only an allowed model and a non-secret alias; no team or project provider credential override is configured. OpenAI upstream requests accept Bearer only; Messages accepts x-api-key only.
- Both model entries include a synthetic deployment-default provider key as a negative control. The guarded callback rejects missing body credentials before routing; a separate profile `unguarded_proxy` reproduces default-key fallback and the raw Chat EOF issue without the callback.

Upstream records contain only test marker IDs, model/protocol labels, tenant labels, terminal names, counters, and credential-match booleans. The CLI captures container logs in memory and checks them for synthetic credentials before emitting output. Neither keys nor request text are printed.

## Run

Create the disposable venv and install only the pinned SDK dependencies:

    python3 -m venv /tmp/byok-t00-smoke-20261012
    /tmp/byok-t00-smoke-20261012/bin/python -m pip install -r tools/byok_t00_probe/requirements.lock

Run evaluator self-tests:

    cd tools/byok_t00_probe
    /tmp/byok-t00-smoke-20261012/bin/python -m unittest -v test_probe test_deepseek_smoke

Run the full subset probe from the repository root:

    /tmp/byok-t00-smoke-20261012/bin/python tools/byok_t00_probe/probe.py

Recheck only image evidence without issuing model requests:

    /tmp/byok-t00-smoke-20261012/bin/python tools/byok_t00_probe/probe.py --images-only

`deepseek_smoke.py` is a separate, opt-in **direct diagnostic**. It uses a hidden terminal prompt, validates a structured answer and the non-streaming `finish_reason`, and emits only sanitized status and usage metadata. It does not call LiteLLM and cannot satisfy the T00 PROXY_LOCAL gate or certify T13 compatibility. The user ran it once on 2026-10-12 and reported a passing DeepSeek direct baseline; details are recorded in `docs/features/byok/tests/T00-sdk-protocol.md`. The current PROXY_LOCAL result still has one preserved Chat EOF failure, so the LiteLLM route remains NOT_RUN. The isolated `probe.py` makes no real-provider calls.

The probe uses Docker context default, a unique Compose project name, pinned image references, and an internal-only network. For each service it reads only the container ID, .Image, .Config.Image, and service label. It then runs docker image inspect by the actual .Image ID and by the configured fixed reference, recording each image .Id and .RepoDigests separately. Image validation passes only when the runtime image-inspect ID and fixed-reference-resolved ID both equal the container .Image ID, and .Config.Image equals the fixed reference. It does not compare a manifest/index digest string directly with an image config ID. Narrow Docker format strings avoid outputting container Env.

Both modes tear down only their own unique Compose project, then assert that its containers and network are gone. Any failed check, including cleanup, makes the CLI exit nonzero.

## Current result boundary

The CLI covers direct SDK and guarded Proxy errors, incomplete outcomes, two-round tool continuation, key/model isolation, and terminal checks. A separate `native-stream` Compose service tests Responses and Messages complete/EOF/incomplete/SSE-error/cancel paths; main admission denies Chat streaming. The unguarded proxy profile separately reproduces deployment-default fallback and the v1.104.2 Chat EOF path. It is intentionally a subset of T00 and is not a product feature.

The latest local synthetic run has 395 PASS / 0 FAIL across 395 checks and exits 0 with overall status `PARTIAL`. The raw unguarded Chat EOF still reproduces `finish_reason=stop` without an upstream protocol terminal. The guarded route is separately verified to return HTTP 400 `T00_STREAMING_DISABLED` with zero upstream calls; this contains the risk by disabling that route and does not establish Chat streaming compatibility or a LiteLLM fix. Standard Responses tool turns use realistic `fc_...` item IDs and `call_...` call IDs, with strict round-trip comparison. The old `resp_item...` item IDs remain in a separate foreign-ID normalization case: LiteLLM v1.104.2 removes those item IDs while preserving `call_id`, tool-result association, and the rest of the continuation.

Cancellation probes use a bounded synthetic long stream and a 2-second local observation window. SDK_LOCAL and native-stream Proxy cancellation cases close the downstream SDK response, observe an upstream socket disconnect and producer exit within the window, and report zero active fixture producers; the native-stream Proxy health endpoint remains available. The recorded frame counts are writes accepted by the local fixture socket, not a count of vendor-side generation or billing. Responses and Messages terminate with their protocol events and do not receive Chat's `[DONE]` sentinel. This proves only the local SDK/Proxy path. The DeepSeek direct baseline is separately recorded; the LiteLLM provider route remains NOT_RUN.
