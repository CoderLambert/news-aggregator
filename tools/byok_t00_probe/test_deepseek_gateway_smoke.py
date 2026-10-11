"""No-provider-network tests for the opt-in DeepSeek gateway smoke."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx2

import deepseek_gateway_smoke as gateway
from deepseek_smoke import EXPECTED_ANSWER, MODEL, PROMPT


def completion(content: str, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl_synthetic",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": 57,
            "completion_tokens": 19,
            "total_tokens": 76,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


class GatewayConfigTests(unittest.TestCase):
    def test_route_uses_only_the_nonfunctional_sentinel_and_guarded_request_key(self):
        config = gateway._proxy_config_yaml()
        self.assertIn("api_base: https://api.deepseek.com", config)
        self.assertIn("model: deepseek/deepseek-flash", config)
        self.assertIn("api_key: sk-t00-deployment-default-synthetic", config)
        self.assertIn("callbacks: proxy_callback.proxy_handler_instance", config)
        callback = (gateway.TOOL_DIR / "proxy_callback.py").read_text(encoding="utf-8")
        self.assertIn('provider_key = data.get("api_key")', callback)
        self.assertIn('"BYOK_PROVIDER_KEY_REQUIRED"', callback)
        self.assertIn("num_retries: 0", config)
        self.assertIn("fallbacks: []", config)

    def test_ephemeral_compose_binds_only_loopback_and_separates_provider_egress(self):
        with tempfile.TemporaryDirectory(prefix="t00-gateway-test-") as directory:
            rendered = gateway._compose_yaml(gateway.Path(directory))
        self.assertIn('"127.0.0.1::4000"', rendered)
        self.assertIn("control:\n    internal: true", rendered)
        self.assertIn("provider_egress:\n    driver: bridge", rendered)
        self.assertIn("/var/lib/postgresql/data:rw,size=256m", rendered)

    def test_compose_port_must_be_a_loopback_ephemeral_port(self):
        self.assertEqual(gateway._local_port("127.0.0.1:32768"), 32768)
        with self.assertRaises(gateway.ProxySetupError):
            gateway._local_port("0.0.0.0:32768")
        with self.assertRaises(gateway.ProxySetupError):
            gateway._local_port("127.0.0.1:0")


class GatewaySDKWireTests(unittest.TestCase):
    def _run(self, *, status_code: int = 200, content: str | None = None, finish_reason: str = "stop"):
        requests = []

        def handler(request):
            requests.append(request)
            body = completion(
                content if content is not None else json.dumps(EXPECTED_ANSWER),
                finish_reason,
            )
            if status_code != 200:
                body = {"error": {"message": "synthetic provider error"}}
            return httpx2.Response(status_code, json=body)

        transport = httpx2.MockTransport(handler)

        def http_client_factory(**kwargs):
            return httpx2.Client(transport=transport, **kwargs)

        status, exit_code, result = gateway.run_gateway_request(
            "sk-synthetic-provider-never-print",
            "sk-synthetic-project-never-print",
            "http://127.0.0.1:41239",
            http_client_factory=http_client_factory,
        )
        return status, exit_code, result, requests

    def test_one_bounded_request_uses_project_auth_and_provider_body_key(self):
        status, exit_code, result, requests = self._run()
        self.assertEqual((status, exit_code), ("PASS", 0))
        self.assertEqual(result["request_count"], 1)
        self.assertEqual(result["answer_assertion"], "json_object_fields_match")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.url.host, "127.0.0.1")
        self.assertEqual(request.url.path, "/v1/chat/completions")
        self.assertEqual(
            request.headers.get("authorization"),
            "Bearer sk-synthetic-project-never-print",
        )
        body = json.loads(request.content)
        self.assertEqual(body["model"], gateway.MODEL_ALIAS)
        self.assertEqual(body["messages"], [{"role": "user", "content": PROMPT}])
        self.assertEqual(body["max_tokens"], gateway.MAX_OUTPUT_TOKENS)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["api_key"], "sk-synthetic-provider-never-print")
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertNotIn("sk-synthetic-provider-never-print", json.dumps(result))
        self.assertNotIn("sk-synthetic-project-never-print", json.dumps(result))

    def test_invalid_answer_and_incomplete_terminal_fail(self):
        for content, terminal in (("", "stop"), ("not-json", "stop"), ("{}", "length")):
            with self.subTest(content=content, terminal=terminal):
                status, exit_code, result, requests = self._run(
                    content=content,
                    finish_reason=terminal,
                )
                self.assertEqual(status, "FAIL")
                self.assertEqual(exit_code, 1)
                self.assertEqual(result["request_count"], 1)
                self.assertEqual(len(requests), 1)

    def test_gateway_http_error_is_redacted(self):
        status, exit_code, result, requests = self._run(status_code=503)
        self.assertEqual(status, "FAIL")
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["http_status"], 503)
        self.assertEqual(len(requests), 1)
        self.assertNotIn("synthetic provider error", json.dumps(result))


class GatewayOptInTests(unittest.TestCase):
    def _main(self, args, *, is_tty: bool, entered_key: str = ""):
        output = io.StringIO()
        stdin = SimpleNamespace(isatty=lambda: is_tty)
        with contextlib.redirect_stdout(output), patch.object(gateway.sys, "stdin", stdin), patch(
            "deepseek_gateway_smoke.start_ephemeral_proxy"
        ) as start_proxy, patch("deepseek_gateway_smoke.getpass.getpass", return_value=entered_key), patch(
            "deepseek_gateway_smoke.cleanup_ephemeral_proxy", return_value=True
        ) as cleanup:
            session = gateway.ProxySession(
                project_name="t00-ds-smoke-test",
                compose_file=gateway.Path("/tmp/compose.yaml"),
                private_dir=gateway.Path("/tmp/t00-ds-smoke-test"),
                base_url="http://127.0.0.1:41239",
                master_key="sk-synthetic-master",
                project_key="sk-synthetic-project",
            )
            start_proxy.return_value = session
            exit_code = gateway.main(args)
        return exit_code, json.loads(output.getvalue()), start_proxy, cleanup

    def test_default_path_does_not_start_proxy_or_prompt(self):
        exit_code, result, start_proxy, cleanup = self._main([], is_tty=True)
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["gateway_smoke"], "NOT_RUN")
        start_proxy.assert_not_called()
        cleanup.assert_not_called()

    def test_noninteractive_opt_in_is_blocked_before_proxy_start(self):
        exit_code, result, start_proxy, cleanup = self._main(
            ["--send-one-request"],
            is_tty=False,
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["gateway_smoke"], "BLOCKED")
        self.assertEqual(result["request_count"], 0)
        start_proxy.assert_not_called()
        cleanup.assert_not_called()

    def test_empty_key_cleans_up_without_model_request(self):
        with patch("deepseek_gateway_smoke.run_gateway_request") as run_request:
            exit_code, result, start_proxy, cleanup = self._main(
                ["--send-one-request"],
                is_tty=True,
                entered_key="   ",
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["gateway_smoke"], "BLOCKED")
        self.assertEqual(result["reason"], "empty_key")
        self.assertEqual(result["request_count"], 0)
        start_proxy.assert_called_once()
        cleanup.assert_called_once()
        run_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
