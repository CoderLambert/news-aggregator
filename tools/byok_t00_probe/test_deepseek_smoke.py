"""No-network checks for the opt-in DeepSeek direct diagnostic."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import httpx2
import deepseek_smoke
from deepseek_smoke import (
    BASE_URL,
    EXPECTED_ANSWER,
    MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    MODEL,
    PROMPT,
    _valid_completion,
    run_direct_request,
)


def completion(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content),
        )],
        usage=SimpleNamespace(
            prompt_tokens=28,
            completion_tokens=12,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )


class DeepSeekCompletionAssertionTests(unittest.TestCase):
    def test_expected_json_object_and_complete_stop_pass(self):
        valid, reason, terminal = _valid_completion(
            completion(json.dumps(EXPECTED_ANSWER)), 1
        )
        self.assertTrue(valid)
        self.assertEqual(reason, "json_object_fields_match")
        self.assertEqual(terminal, "stop")

    def test_exact_free_text_is_not_a_valid_answer(self):
        valid, reason, _terminal = _valid_completion(completion("OK"), 1)
        self.assertFalse(valid)
        self.assertEqual(reason, "invalid_json_answer")

    def test_empty_and_invalid_json_fail(self):
        for content in ("", "   ", "{not-json"):
            with self.subTest(content=content):
                valid, _reason, _terminal = _valid_completion(completion(content), 1)
                self.assertFalse(valid)

    def test_wrong_shape_values_or_extra_fields_fail(self):
        invalid_answers = (
            {"probe_id": "other", "ok": True},
            {"probe_id": EXPECTED_ANSWER["probe_id"], "ok": False},
            {"probe_id": EXPECTED_ANSWER["probe_id"], "ok": 1},
            {"probe_id": EXPECTED_ANSWER["probe_id"], "ok": True, "extra": "x"},
            {"probe_id": EXPECTED_ANSWER["probe_id"]},
        )
        for answer in invalid_answers:
            with self.subTest(answer=answer):
                valid, reason, _terminal = _valid_completion(
                    completion(json.dumps(answer)), 1
                )
                self.assertFalse(valid)
                self.assertEqual(reason, "answer_assertion_failed")

    def test_missing_length_and_unknown_terminals_fail(self):
        for finish_reason in (None, "length", "tool_calls", "unexpected"):
            with self.subTest(finish_reason=finish_reason):
                valid, reason, _terminal = _valid_completion(
                    completion(json.dumps(EXPECTED_ANSWER), finish_reason), 1
                )
                self.assertFalse(valid)
                self.assertEqual(reason, "incomplete_or_unexpected_terminal")

    def test_zero_or_multiple_requests_fail(self):
        for count in (0, 2):
            with self.subTest(count=count):
                valid, reason, _terminal = _valid_completion(
                    completion(json.dumps(EXPECTED_ANSWER)), count
                )
                self.assertFalse(valid)
                self.assertEqual(reason, "request_count_mismatch")

    def test_missing_or_multiple_choices_fail(self):
        for choices in (None, [], [completion("{} ").choices[0]] * 2):
            response = SimpleNamespace(choices=choices)
            valid, reason, _terminal = _valid_completion(response, 1)
            self.assertFalse(valid)
            self.assertEqual(reason, "choice_count_mismatch")


class FakeHttpClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def close(self):
        self.closed = True


class FakeOpenAI:
    response = completion(json.dumps(EXPECTED_ANSWER))
    error = None
    close_error = None
    instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.http_client = kwargs["http_client"]
        self.closed = False
        self.call_kwargs = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )
        type(self).instance = self

    def create_completion(self, **kwargs):
        self.call_kwargs = kwargs
        hook = self.http_client.kwargs["event_hooks"]["request"][0]
        hook(object())
        if type(self).error is not None:
            raise type(self).error
        return type(self).response

    def close(self):
        self.closed = True
        self.http_client.close()
        if type(self).close_error is not None:
            raise type(self).close_error


class DeepSeekDirectRequestTests(unittest.TestCase):
    def setUp(self):
        FakeOpenAI.response = completion(json.dumps(EXPECTED_ANSWER))
        FakeOpenAI.error = None
        FakeOpenAI.close_error = None
        FakeOpenAI.instance = None

    def _run(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = run_direct_request(
                "sk-synthetic-test-only",
                client_factory=FakeOpenAI,
                http_client_factory=FakeHttpClient,
            )
        return exit_code, json.loads(output.getvalue())

    def test_success_uses_fixed_endpoint_no_retries_and_matches_exit_status(self):
        exit_code, result = self._run()
        client = FakeOpenAI.instance
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["direct_baseline"], "PASS")
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["answer_assertion"], "json_object_fields_match")
        self.assertEqual(client.kwargs["api_key"], "sk-synthetic-test-only")
        self.assertEqual(client.kwargs["base_url"], BASE_URL)
        self.assertEqual(client.kwargs["max_retries"], MAX_RETRIES)
        self.assertEqual(client.call_kwargs["model"], MODEL)
        self.assertEqual(client.call_kwargs["messages"][0]["content"], PROMPT)
        self.assertEqual(client.call_kwargs["max_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(client.call_kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(
            client.call_kwargs["extra_body"], {"thinking": {"type": "disabled"}}
        )
        self.assertTrue(client.closed)
        self.assertNotIn("sk-synthetic-test-only", json.dumps(result))

    def test_invalid_response_emits_fail_and_nonzero_exit(self):
        FakeOpenAI.response = completion("{}")
        exit_code, result = self._run()
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["direct_baseline"], "FAIL")
        self.assertEqual(result["failure_reason"], "answer_assertion_failed")

    def test_interrupted_request_emits_fail_with_matching_nonzero_exit(self):
        FakeOpenAI.error = KeyboardInterrupt()
        exit_code, result = self._run()
        self.assertEqual(exit_code, 130)
        self.assertEqual(result["direct_baseline"], "FAIL")
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(result["failure_reason"], "request_interrupted")
        self.assertTrue(FakeOpenAI.instance.closed)

    def test_exception_text_is_never_emitted(self):
        FakeOpenAI.error = RuntimeError("synthetic key must not print")
        exit_code, result = self._run()
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["direct_baseline"], "FAIL")
        self.assertEqual(result["failure_reason"], "RuntimeError")
        self.assertNotIn("synthetic key must not print", json.dumps(result))

    def test_close_failure_overrides_a_valid_response(self):
        FakeOpenAI.close_error = RuntimeError("close failure")
        exit_code, result = self._run()
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["direct_baseline"], "FAIL")
        self.assertEqual(result["failure_reason"], "resource_close_failed")


class DeepSeekOfficialSDKWireTests(unittest.TestCase):
    def _run_sdk(self, status_code=200):
        requests = []

        def handler(request):
            requests.append(request)
            if status_code == 200:
                body = {
                    "id": "chatcmpl_synthetic",
                    "object": "chat.completion",
                    "created": 1,
                    "model": MODEL,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(EXPECTED_ANSWER),
                        },
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": 28,
                        "completion_tokens": 12,
                        "total_tokens": 40,
                        "completion_tokens_details": {"reasoning_tokens": 0},
                    },
                }
            else:
                body = {"error": {"message": "synthetic error contains no real credential"}}
            return httpx2.Response(status_code, json=body)

        transport = httpx2.MockTransport(handler)

        def client_factory(**kwargs):
            return httpx2.Client(transport=transport, **kwargs)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = run_direct_request(
                "sk-synthetic-wire-test",
                http_client_factory=client_factory,
                emit_result=lambda status, **details: print(
                    json.dumps({"direct_baseline": status, **details}, sort_keys=True)
                ),
            )
        return exit_code, json.loads(output.getvalue()), requests

    def test_official_sdk_serializes_bounded_nonthinking_json_request(self):
        exit_code, result, requests = self._run_sdk()
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["direct_baseline"], "PASS")
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.url.host, "api.deepseek.com")
        self.assertEqual(request.url.path, "/chat/completions")
        self.assertEqual(request.headers.get("authorization"), "Bearer sk-synthetic-wire-test")
        self.assertIsNone(request.headers.get("x-api-key"))
        body = json.loads(request.content)
        self.assertEqual(body["model"], MODEL)
        self.assertEqual(body["messages"], [{"role": "user", "content": PROMPT}])
        self.assertEqual(body["max_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("temperature", body)
        self.assertNotIn("sk-synthetic-wire-test", json.dumps(result))

    def test_official_sdk_http_error_is_redacted_and_nonzero(self):
        exit_code, result, requests = self._run_sdk(status_code=503)
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["direct_baseline"], "FAIL")
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(result["http_status"], 503)
        self.assertEqual(len(requests), 1)
        self.assertNotIn("synthetic error", json.dumps(result))


class DeepSeekOptInTests(unittest.TestCase):
    def _run_main(self, args, *, is_tty=True, entered_key="sk-synthetic-test-only", key_error=None):
        output = io.StringIO()
        stdin = SimpleNamespace(isatty=lambda: is_tty)
        with contextlib.redirect_stdout(output), patch.object(deepseek_smoke.sys, "stdin", stdin), patch(
            "deepseek_smoke.getpass.getpass",
            side_effect=key_error if key_error is not None else None,
            return_value=entered_key,
        ), patch("deepseek_smoke.run_direct_request", return_value=0) as run_request:
            exit_code = deepseek_smoke.main(args)
        return exit_code, json.loads(output.getvalue()) if output.getvalue() else None, run_request

    def test_default_path_is_not_run_and_does_not_prompt(self):
        exit_code, result, run_request = self._run_main([], entered_key="")
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["direct_baseline"], "NOT_RUN")
        run_request.assert_not_called()

    def test_noninteractive_invocation_is_blocked_without_prompt_or_request(self):
        exit_code, result, run_request = self._run_main(
            ["--send-one-request"], is_tty=False
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["direct_baseline"], "BLOCKED")
        self.assertEqual(result["request_count"], 0)
        run_request.assert_not_called()

    def test_empty_key_is_blocked_without_request(self):
        exit_code, result, run_request = self._run_main(
            ["--send-one-request"], entered_key="   "
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["direct_baseline"], "BLOCKED")
        self.assertEqual(result["request_count"], 0)
        run_request.assert_not_called()

    def test_key_input_cancellation_is_not_run(self):
        exit_code, result, run_request = self._run_main(
            ["--send-one-request"], key_error=KeyboardInterrupt()
        )
        self.assertEqual(exit_code, 130)
        self.assertEqual(result["direct_baseline"], "NOT_RUN")
        self.assertEqual(result["request_count"], 0)
        run_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
