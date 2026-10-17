"""Direct regression tests for the fail-closed Chat streaming guard.

These tests load ``provider_key_guard.py`` by path and stub the LiteLLM /
FastAPI imports when they are not installed, so they run in any plain
Python 3 environment (``python -m pytest`` or ``python -m unittest``).
No network, Docker, provider key, or upstream is used: a request that is
allowed by the hook is, by definition, a request that would have been
sent upstream, so "allowed" is the observable pre-fix failure here.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


GUARD_PATH = Path(__file__).resolve().parents[1] / "provider_key_guard.py"


def _load_guard():
    fastapi = ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi.HTTPException = HTTPException
    litellm = ModuleType("litellm")
    integrations = ModuleType("litellm.integrations")
    custom_logger = ModuleType("litellm.integrations.custom_logger")

    class CustomLogger:
        pass

    custom_logger.CustomLogger = CustomLogger
    integrations.custom_logger = custom_logger
    litellm.integrations = integrations
    stubs = {
        "fastapi": fastapi,
        "litellm": litellm,
        "litellm.integrations": integrations,
        "litellm.integrations.custom_logger": custom_logger,
    }
    spec = importlib.util.spec_from_file_location("provider_key_guard_under_test", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


guard = _load_guard()


def run_hook(data, call_type, env=None):
    """Return ("allowed", data) or ("rejected", status, code)."""
    hook = guard.ProviderKeyGuard().async_pre_call_hook(
        user_api_key_dict=SimpleNamespace(), cache=None, data=dict(data), call_type=call_type
    )
    with patch.dict(os.environ, env or {}, clear=False):
        # The hook reads the deny-list env var at call time; ensure a
        # caller-supplied empty value really reaches it.
        if env is not None and "BYOK_DENY_STREAMING_CALL_TYPES" in env:
            os.environ["BYOK_DENY_STREAMING_CALL_TYPES"] = env["BYOK_DENY_STREAMING_CALL_TYPES"]
        try:
            result = asyncio.run(hook)
        except guard.HTTPException as exc:  # stub or real FastAPI exception
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            return ("rejected", exc.status_code, detail.get("code"))
        except Exception as exc:  # real FastAPI HTTPException class differs
            status = getattr(exc, "status_code", None)
            detail = getattr(exc, "detail", {})
            code = detail.get("code") if isinstance(detail, dict) else None
            if status is not None:
                return ("rejected", status, code)
            raise
    return ("allowed", result)


CHAT = {"api_key": "sk-synthetic-provider", "stream": True}
# The EOF defect scenario: this exact request, if allowed, is the one the
# §12 harness showed upstream closing without a terminal while the proxy
# synthesised finish_reason=stop + [DONE].
EOF_CHAT = {"api_key": "sk-synthetic-provider", "stream": True, "messages": "T00_PROXY_CHAT_STREAM_EOF_A"}


class ChatStreamingFailClosed(unittest.TestCase):
    def test_chat_stream_eof_scenario_rejected_before_upstream(self):
        self.assertEqual(run_hook(EOF_CHAT, "acompletion"), ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_rejected_even_if_deny_env_is_empty(self):
        result = run_hook(CHAT, "acompletion", env={"BYOK_DENY_STREAMING_CALL_TYPES": ""})
        self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_rejected_even_if_deny_env_omits_chat(self):
        result = run_hook(CHAT, "acompletion", env={"BYOK_DENY_STREAMING_CALL_TYPES": "aresponses"})
        self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_rejected_with_misscased_deny_env(self):
        result = run_hook(CHAT, "acompletion", env={"BYOK_DENY_STREAMING_CALL_TYPES": "ACOMPLETION"})
        self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_string_flag_rejected(self):
        for flag in ("true", "True", " TRUE ", "1"):
            with self.subTest(flag=flag):
                result = run_hook({**CHAT, "stream": flag}, "acompletion")
                self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_short_boolean_aliases_and_unknown_shapes_fail_closed(self):
        for flag in ("t", "T", "y", "Y", "unknown", "", -1, 2, 0.5, [], {}):
            with self.subTest(flag=flag):
                result = run_hook({**CHAT, "stream": flag}, "acompletion")
                self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_numeric_flag_rejected(self):
        self.assertEqual(run_hook({**CHAT, "stream": 1}, "acompletion"), ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_sync_completion_stream_rejected(self):
        self.assertEqual(run_hook(CHAT, "completion"), ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))


class UnaffectedPaths(unittest.TestCase):
    def test_non_streaming_chat_allowed(self):
        for data in ({"api_key": "sk-synthetic-provider"}, {"api_key": "sk-synthetic-provider", "stream": False},
                     {"api_key": "sk-synthetic-provider", "stream": "false"}, {"api_key": "sk-synthetic-provider", "stream": 0},
                     *({"api_key": "sk-synthetic-provider", "stream": value}
                       for value in ("f", "F", "n", "N", "no", "off", "0", 0.0, None))):
            with self.subTest(data=data):
                self.assertEqual(run_hook(data, "acompletion")[0], "allowed")

    def test_responses_and_messages_streaming_allowed(self):
        for call_type in ("aresponses", "anthropic_messages"):
            with self.subTest(call_type=call_type):
                self.assertEqual(run_hook(CHAT, call_type)[0], "allowed")

    def test_extra_env_denied_types_still_denied(self):
        result = run_hook(CHAT, "aresponses", env={"BYOK_DENY_STREAMING_CALL_TYPES": "aresponses"})
        self.assertEqual(result, ("rejected", 400, "T00_STREAMING_DISABLED"))

    def test_missing_provider_key_still_rejected_first(self):
        self.assertEqual(run_hook({"stream": False}, "acompletion"), ("rejected", 400, "BYOK_PROVIDER_KEY_REQUIRED"))
        self.assertEqual(run_hook({"api_key": "  ", "stream": True}, "acompletion"), ("rejected", 400, "BYOK_PROVIDER_KEY_REQUIRED"))


if __name__ == "__main__":
    unittest.main()
