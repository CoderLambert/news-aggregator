# T00 SDK and Proxy probe

This isolated probe uses the official OpenAI and Anthropic SDKs, pinned LiteLLM v1.104.2, an internal-only synthetic HTTP upstream, and temporary Postgres storage. It never calls a real provider or reads an existing provider key.

## Credential contract covered

- Direct OpenAI SDK calls use the synthetic provider key as Authorization: Bearer; the probe does not add x-api-key.
- Direct Anthropic Messages calls use the provider key through the SDK api_key option, which sends x-api-key.
- Proxy SDK calls use a generated synthetic project virtual key in Authorization only. The provider key is sent per request in the official SDK's supported body field api_key (extra_body).
- LiteLLM has forward_client_headers_to_llm_api and forward_llm_provider_auth_headers disabled. OpenAI upstream requests accept Bearer only; Messages accepts x-api-key only.
- Both Proxy model entries include a synthetic deployment default provider key. Omitting the per-request provider key deliberately checks whether LiteLLM falls back to it.

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

The CLI covers direct SDK complete/EOF flows for all three protocols, Proxy Chat A/B same-model concurrency, Proxy Messages auth, wrong project key rejection, missing provider key behavior with the deployment default control, and the v1.104.2 Chat EOF path. It is intentionally a subset of T00; passing these checks would not complete the original T00 acceptance matrix.

For the tested v1.104.2 image the known EOF integrity check fails: the raw Chat upstream ends without a protocol terminal, but the Proxy SDK yields finish_reason=stop. The missing-provider check also fails because the upstream receives the configured deployment default key. These failures are surfaced individually and cause exit code 1. No local result is a claim of real-provider compatibility. PROVIDER_REAL remains NOT_RUN.
