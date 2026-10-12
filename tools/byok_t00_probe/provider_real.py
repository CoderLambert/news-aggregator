"""Optional, explicitly invoked one-request DeepSeek text smoke test.

This file is intentionally not called by the SDK_LOCAL probe. It prompts for
the API key with terminal echo disabled, uses DeepSeek's official generic API
endpoint, and never prints or stores the key or response body.
"""

from __future__ import annotations

import argparse
import getpass
import sys

import httpx2
from openai import OpenAI


BASE_URL = "https://api.deepseek.com"
MAX_OUTPUT_TOKENS = 16
TIMEOUT_SECONDS = 20.0
SYNTHETIC_PROMPT = "Reply with the single word OK. This is a synthetic connectivity check."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Explicit DeepSeek model name, for example deepseek-flash.")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("PROVIDER_REAL=NOT_RUN reason=interactive_terminal_required", file=sys.stderr)
        return 2

    api_key = getpass.getpass("DeepSeek API key (input hidden): ")
    if not api_key:
        print("PROVIDER_REAL=NOT_RUN reason=empty_key", file=sys.stderr)
        return 2

    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        max_retries=0,
        timeout=TIMEOUT_SECONDS,
        http_client=httpx2.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=TIMEOUT_SECONDS,
        ),
    )
    del api_key
    try:
        response = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": SYNTHETIC_PROMPT}],
            max_tokens=MAX_OUTPUT_TOKENS,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        output_tokens = getattr(getattr(response, "usage", None), "completion_tokens", None)
        print(f"PROVIDER_REAL=PASS provider=DeepSeek model={args.model} requests=1 max_output_tokens={MAX_OUTPUT_TOKENS} output_tokens={output_tokens}")
        return 0
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        status_text = str(status) if isinstance(status, int) else "unavailable"
        print(f"PROVIDER_REAL=FAIL provider=DeepSeek model={args.model} exception_type={type(exc).__name__} http_status={status_text}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
