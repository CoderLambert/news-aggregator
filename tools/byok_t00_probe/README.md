# BYOK T00 direct SDK probe

This isolated probe exercises the official OpenAI and Anthropic Python SDKs
against a controlled loopback HTTP upstream. It does not start a proxy or call
a provider in `sdk-local` mode. Its only credentials are synthetic fixture
keys.

## SDK_LOCAL

Create a dedicated virtual environment and install only the locked probe
dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r tools/byok_t00_probe/requirements.lock
python -m tools.byok_t00_probe.probe --mode sdk-local
```

The local upstream binds only to `127.0.0.1` on an ephemeral port. The probe
covers complete and incomplete terminal states, EOF, HTTP and SSE errors,
strict tool arguments and allowlists, two tool round trips, credential/model
isolation, retry count, cancellation, and client/stream closure.

## Prepared DeepSeek PROVIDER_REAL entrypoint

This separate entrypoint is not called by SDK_LOCAL and has not been run. It
uses only `https://api.deepseek.com`, one synthetic text request, no SDK
retries, and a fixed 16-token output cap. It refuses non-interactive stdin,
asks for the key with terminal echo disabled, and does not print or persist the
key or response body. The model must be explicitly supplied:

```sh
python -m tools.byok_t00_probe.provider_real --model deepseek-flash
```

Do not run this command until the user confirms the model and budget. The
current recommendation is `deepseek-flash`; the official DeepSeek model/pricing
page lists it as the current Flash model and documents the generic OpenAI
base URL. Pricing can change, so check it again before any real request.
