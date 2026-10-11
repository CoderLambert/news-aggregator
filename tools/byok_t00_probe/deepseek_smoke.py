#!/usr/bin/env python3
"""A deliberately bounded, opt-in DeepSeek smoke probe.

This script does not call a provider unless --send-one-request is provided.
The API key is requested with getpass and is never persisted or printed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import httpx2
from openai import APIStatusError, OpenAI


BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
PROMPT = "Reply with exactly the word OK."
MAX_OUTPUT_TOKENS = 16
MAX_RETRIES = 0


def emit(status: str, **details: object) -> None:
    print(json.dumps({"provider_real": status, **details}, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send-one-request",
        action="store_true",
        help="send exactly one bounded request to the official DeepSeek API",
    )
    args = parser.parse_args(argv)
    if not args.send_one_request:
        emit("NOT_RUN", request_count=0, requires="--send-one-request")
        return 0
    if not sys.stdin.isatty():
        emit("BLOCKED", request_count=0, reason="interactive_terminal_required")
        return 2

    try:
        api_key = getpass.getpass("DeepSeek API key (hidden; not saved): ")
    except (EOFError, KeyboardInterrupt):
        emit("NOT_RUN", request_count=0, reason="key_input_cancelled")
        return 130
    if not api_key:
        emit("BLOCKED", request_count=0, reason="empty_key")
        return 2

    request_count = 0

    def count_request(_request: httpx2.Request) -> None:
        nonlocal request_count
        request_count += 1

    http_client = httpx2.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=30.0,
        event_hooks={"request": [count_request]},
    )
    client: OpenAI | None = None
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=BASE_URL,
            max_retries=MAX_RETRIES,
            http_client=http_client,
        )
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=MAX_OUTPUT_TOKENS,
            reasoning_effort="none",
            temperature=0,
        )
        usage = response.usage
        emit(
            "PASS" if request_count == 1 else "FAIL",
            model=MODEL,
            request_count=request_count,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            prompt_tokens=None if usage is None else usage.prompt_tokens,
            completion_tokens=None if usage is None else usage.completion_tokens,
            response_text="[omitted]",
        )
        return 0 if request_count == 1 else 1
    except APIStatusError as exc:
        emit(
            "FAIL",
            request_count=request_count,
            error_category="provider_http_error",
            http_status=exc.status_code,
        )
        return 1
    except Exception as exc:
        # Deliberately omit str(exc), repr(exc), headers, and response bodies.
        emit(
            "FAIL",
            request_count=request_count,
            error_category=type(exc).__name__,
        )
        return 1
    finally:
        if client is not None:
            client.close()
        else:
            http_client.close()
        # Drop references promptly; no file, environment variable, or cache is used.
        api_key = ""


if __name__ == "__main__":
    raise SystemExit(main())
