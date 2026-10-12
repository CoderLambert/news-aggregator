#!/usr/bin/env python3
"""Opt-in, one-request DeepSeek direct diagnostic.

The API key is read with getpass and used only in this process. This direct
diagnostic does not exercise LiteLLM and cannot satisfy the T00 PROXY_LOCAL
gate or the T13 provider matrix.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Any

import httpx2
from openai import APIStatusError, OpenAI


BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
EXPECTED_ANSWER = {"probe_id": "byok-deepseek-smoke-v1", "ok": True}
PROMPT = (
    'Return only a JSON object with exactly these fields: '
    '{"probe_id":"byok-deepseek-smoke-v1","ok":true}.'
)
MAX_OUTPUT_TOKENS = 24
MAX_RETRIES = 0
TIMEOUT_SECONDS = 30.0


def emit(status: str, **details: object) -> None:
    print(json.dumps({"direct_baseline": status, **details}, sort_keys=True))


def _valid_completion(response: Any, request_count: int) -> tuple[bool, str, str | None]:
    """Require one complete non-streaming answer with the expected JSON shape."""
    if request_count != 1:
        return False, "request_count_mismatch", None

    choices = getattr(response, "choices", None)
    if not isinstance(choices, (list, tuple)) or len(choices) != 1:
        return False, "choice_count_mismatch", None

    choice = choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason != "stop":
        # Do not allow length, missing, or unknown terminal states to pass.
        safe_finish = (
            finish_reason
            if isinstance(finish_reason, str)
            and finish_reason in {"length", "tool_calls", "content_filter"}
            else None
        )
        return False, "incomplete_or_unexpected_terminal", safe_finish

    message = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        return False, "empty_answer", "stop"

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return False, "invalid_json_answer", "stop"

    if (
        not isinstance(payload, dict)
        or set(payload) != set(EXPECTED_ANSWER)
        or payload.get("probe_id") != EXPECTED_ANSWER["probe_id"]
        or type(payload.get("ok")) is not bool
        or payload.get("ok") is not True
    ):
        return False, "answer_assertion_failed", "stop"

    return True, "json_object_fields_match", "stop"


def _usage_fields(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(completion_details, "reasoning_tokens", None),
    }


def run_direct_request(
    provider_key: str,
    *,
    client_factory=OpenAI,
    http_client_factory=httpx2.Client,
    emit_result=emit,
) -> int:
    request_count = 0

    def count_request(_request: httpx2.Request) -> None:
        nonlocal request_count
        request_count += 1

    http_client = None
    client = None
    result: dict[str, object] = {
        "model": MODEL,
        "protocol": "openai_chat_completions_non_streaming",
        "request_count": 0,
        "request_count_semantics": "SDK HTTP request attempts",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "thinking": "disabled",
    }
    status = "FAIL"
    exit_code = 1
    try:
        http_client = http_client_factory(
            trust_env=False,
            follow_redirects=False,
            timeout=TIMEOUT_SECONDS,
            event_hooks={"request": [count_request]},
        )
        client = client_factory(
            api_key=provider_key,
            base_url=BASE_URL,
            max_retries=MAX_RETRIES,
            http_client=http_client,
        )
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        valid, assertion, finish_reason = _valid_completion(response, request_count)
        result.update(_usage_fields(response))
        result["request_count"] = request_count
        result["finish_reason"] = finish_reason
        result["answer_assertion"] = assertion
        if valid:
            status = "PASS"
            exit_code = 0
        else:
            result["failure_reason"] = assertion
    except APIStatusError as exc:
        result.update({
            "request_count": request_count,
            "failure_reason": "provider_http_error",
            "http_status": exc.status_code,
        })
    except KeyboardInterrupt:
        # The provider may already have processed this attempt, so report a
        # failure with the observed SDK request count instead of hiding it.
        result.update({
            "request_count": request_count,
            "failure_reason": "request_interrupted",
        })
        exit_code = 130
    except Exception as exc:
        # Never emit exception text, request headers, response bodies, or the key.
        result.update({
            "request_count": request_count,
            "failure_reason": type(exc).__name__,
        })
    finally:
        close_failed = False
        try:
            if client is not None:
                client.close()
            elif http_client is not None:
                http_client.close()
        except Exception:
            close_failed = True
        provider_key = ""

    if close_failed:
        status = "FAIL"
        exit_code = 1
        result["failure_reason"] = "resource_close_failed"
    emit_result(status, **result)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send-one-request",
        action="store_true",
        help="send exactly one bounded direct request to the official DeepSeek API",
    )
    args = parser.parse_args(argv)
    if not args.send_one_request:
        emit("NOT_RUN", request_count=0, requires="--send-one-request")
        return 0
    if not sys.stdin.isatty():
        emit("BLOCKED", request_count=0, reason="interactive_terminal_required")
        return 2

    try:
        provider_key = getpass.getpass("DeepSeek API key (hidden; not saved): ")
    except (EOFError, KeyboardInterrupt):
        emit("NOT_RUN", request_count=0, reason="key_input_cancelled")
        return 130
    if not provider_key.strip():
        provider_key = ""
        emit("BLOCKED", request_count=0, reason="empty_key")
        return 2

    provider_key = provider_key.strip()
    exit_code = run_direct_request(provider_key)
    provider_key = ""
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
