# T00 local SDK and Proxy probe

This probe uses the pinned LiteLLM v1.104.2 image, an internal-only synthetic HTTP upstream, temporary Postgres storage, and the official OpenAI/Anthropic SDKs. It has no real-provider route, no host port publication, and no user key input. The synthetic master, project, and provider credentials are never printed. Compose containers and tmpfs database storage are removed on exit.

The current result is **BLOCKED** for the exact OpenAI Chat Completions streaming route tested: the controlled upstream closes without a protocol terminal, while the Proxy SDK response ends with `finish_reason=stop`. The CLI returns status `2` for this observed integrity blocker. This does not claim the same result for other Proxy routes.

## Run

From the repository root, use a disposable virtual environment and pinned SDK dependency lock:

```bash
python3 -m venv /tmp/byok-t00-sdk-venv-20261011
/tmp/byok-t00-sdk-venv-20261011/bin/python -m pip install -r tools/byok_t00_probe/requirements.lock
/tmp/byok-t00-sdk-venv-20261011/bin/python tools/byok_t00_probe/probe.py
```

The CLI explicitly uses Docker context `default`; it starts one Compose project and tears it down even when the test fails. It outputs versions, event summaries, and safe request counters as JSON. Do not edit the fixture to accept arbitrary provider keys or external URLs.

## Coverage boundary

- SDK_LOCAL runs the three real SDKs directly against the synthetic HTTP upstream, including complete and no-terminal EOF streams.
- PROXY_LOCAL checks two distinct synthetic project/provider key and model pairs, model denial, invalid project key, missing provider key, request counts, and the Chat Completions EOF behavior.
- Tool continuation, malformed/length responses, upstream transport faults, error/cancel resource assertions, concurrent dispatch, and Responses/Messages through Proxy remain untested. The partial probe is not a T00 PASS.
