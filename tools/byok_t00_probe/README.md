# T00 SDK and Proxy probe

This isolated probe uses the official OpenAI and Anthropic SDKs, pinned LiteLLM v1.104.2, an internal-only synthetic HTTP upstream, and temporary Postgres storage. It never calls a real provider or reads an existing provider key.

## Credential contract covered

- Direct OpenAI SDK calls use the synthetic provider key as Authorization: Bearer; the probe does not add x-api-key.
- Direct Anthropic Messages calls use the provider key through the SDK api_key option, which sends x-api-key.
- Proxy SDK calls use a generated synthetic project virtual key in Authorization only. The provider key is sent per request in the official SDK's supported body field api_key (extra_body).
- The guarded Proxy loads the read-only `proxy_callback.py` CustomLogger instance. Its `async_pre_call_hook` requires a nonempty top-level body `api_key` for `acompletion`, `aresponses`, and `anthropic_messages`; it rejects missing, null, empty, whitespace-only, non-string, metadata-only, and header-only credentials with HTTP 400 before routing.
- Streaming is explicitly denied for all three tested call types through the configurable `T00_DENY_STREAMING_CALL_TYPES` setting. The probe checks Chat, Responses, and Messages streaming receives HTTP 400 and causes zero inference upstream calls.
- Both Proxy configs set `forward_client_headers_to_llm_api` and `forward_llm_provider_auth_headers` to false. Generated project keys contain only an allowed model and a non-secret alias; no team or project provider credential override is configured. OpenAI upstream requests accept Bearer only; Messages accepts x-api-key only.
- Both model entries include a synthetic deployment-default provider key as a negative control. The guarded callback rejects missing body credentials before routing; a separate profile `unguarded_proxy` reproduces default-key fallback and the raw Chat EOF issue without the callback.

Upstream records contain only test marker IDs, model/protocol labels, tenant labels, terminal names, counters, and credential-match booleans. The CLI captures container logs in memory and checks them for synthetic credentials before emitting output. Neither keys nor request text are printed.

## Run

Create the disposable venv and install only the pinned SDK dependencies:

    python3 -m venv /tmp/byok-t00-sdk-venv-20261011
    /tmp/byok-t00-sdk-venv-20261011/bin/python -m pip install -r tools/byok_t00_probe/requirements.lock

Run evaluator self-tests:

    cd tools/byok_t00_probe
    /tmp/byok-t00-sdk-venv-20261011/bin/python -m unittest -v test_probe

Run the full subset probe from the repository root:

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py

Recheck only image evidence without issuing model requests:

    /tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py --images-only

The probe uses Docker context default, a unique Compose project name, pinned image references, and an internal-only network. For each service it reads only the container ID, .Image, .Config.Image, and service label. It then runs docker image inspect by the actual .Image ID and by the configured fixed reference, recording each image .Id and .RepoDigests separately. Image validation passes only when the runtime image-inspect ID and fixed-reference-resolved ID both equal the container .Image ID, and .Config.Image equals the fixed reference. It does not compare a manifest/index digest string directly with an image config ID. Narrow Docker format strings avoid outputting container Env.

Both modes tear down only their own unique Compose project, then assert that its containers and network are gone. Any failed check, including cleanup, makes the CLI exit nonzero.

## Current result boundary

The CLI covers direct SDK complete/EOF flows for all three protocols; guarded Proxy complete requests for Chat, Responses, and Messages; same-model Chat A/B concurrency; wrong project-key rejection; 21 key-denial cases across the three routes; and streaming denial across those routes. The unguarded proxy profile separately reproduces deployment-default fallback and the v1.104.2 Chat EOF path. It is intentionally a subset of T00 and is not a product feature.

Latest local guard probe: 152 checks PASS and the raw unguarded Chat EOF integrity check FAILS, so the CLI exits 1. The observed behavior remains: the raw upstream ends without a protocol terminal while the Proxy SDK yields `finish_reason=stop`. The separate unguarded missing-key request also reaches the upstream once with the configured deployment-default credential; the guarded path returns 400 with zero inference calls. No local result claims real-provider compatibility. PROVIDER_REAL remains NOT_RUN.
