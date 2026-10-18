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
    litellm.__path__ = []
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


def run_hook(data, call_type, env=None, *, patch_ready=True):
    """Return ("allowed", data) or ("rejected", status, code)."""
    hook = guard.ProviderKeyGuard().async_pre_call_hook(
        user_api_key_dict=SimpleNamespace(), cache=None, data=dict(data), call_type=call_type
    )
    with patch.dict(os.environ, env or {}, clear=False):
        if env is not None and "BYOK_DENY_STREAMING_CALL_TYPES" in env:
            os.environ["BYOK_DENY_STREAMING_CALL_TYPES"] = env["BYOK_DENY_STREAMING_CALL_TYPES"]
        with patch.object(guard, "_ensure_router_provenance_patch", return_value=patch_ready):
            try:
                result = asyncio.run(hook)
            except guard.HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                return ("rejected", exc.status_code, detail.get("code"))
            except Exception as exc:
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
    def _fake_router_modules(self, original_method):
        litellm = ModuleType("litellm")
        litellm.__path__ = []
        router_module = ModuleType("litellm.router")
        streaming_package = ModuleType("litellm.litellm_core_utils")
        streaming_package.__path__ = []
        streaming_module = ModuleType("litellm.litellm_core_utils.streaming_handler")

        class CustomStreamWrapper:
            def __init__(self, provider="deepseek"):
                self.custom_llm_provider = provider

        class FallbackAwareStreamWrapper(CustomStreamWrapper):
            fallback_headers_adopted = False

        CustomStreamWrapper.__module__ = "litellm.litellm_core_utils.streaming_handler"
        FallbackAwareStreamWrapper.__module__ = "litellm.router"
        FallbackWrapper = type(
            "FallbackStreamWrapper",
            (FallbackAwareStreamWrapper,),
            {
                "__module__": "litellm.router",
                "__qualname__": "Router._acompletion_streaming_iterator.<locals>.FallbackStreamWrapper",
            },
        )
        Router = type(
            "Router",
            (),
            {
                "__module__": "litellm.router",
                "_acompletion_streaming_iterator": original_method,
            },
        )
        router_module.FallbackAwareStreamWrapper = FallbackAwareStreamWrapper
        router_module.Router = Router
        streaming_module.CustomStreamWrapper = CustomStreamWrapper
        return (
            {
                "litellm": litellm,
                "litellm.router": router_module,
                "litellm.litellm_core_utils": streaming_package,
                "litellm.litellm_core_utils.streaming_handler": streaming_module,
            },
            Router,
            CustomStreamWrapper,
            FallbackWrapper,
        )

    def test_router_patch_keeps_raw_source_per_request_and_is_idempotent(self):
        outputs = {}
        calls = []

        async def original(self, model_response, messages, initial_kwargs, deployment_slot=None):
            calls.append((model_response, initial_kwargs["request_label"]))
            await asyncio.sleep(0)
            return outputs[initial_kwargs["request_label"]]

        original.__module__ = "litellm.router"
        original.__qualname__ = "Router._acompletion_streaming_iterator"
        modules, Router, CustomStreamWrapper, FallbackWrapper = self._fake_router_modules(original)
        outputs["a"] = FallbackWrapper()
        outputs["b"] = FallbackWrapper()
        raw_a, raw_b = CustomStreamWrapper(), CustomStreamWrapper()
        router = Router()
        with patch.object(guard.importlib.metadata, "version", return_value="1.105.0"), patch.object(
            guard, "_ensure_deepseek_parser_patch", return_value=True,
        ), patch.object(guard, "_attach_parser_provenance", return_value=True):
            with patch.object(
                guard.inspect, "getsourcefile", return_value="/fake/site-packages/litellm/router.py",
            ):
                with patch.dict(sys.modules, modules):
                    self.assertTrue(guard._ensure_router_provenance_patch())
                    patched = Router._acompletion_streaming_iterator
                    self.assertTrue(guard._ensure_router_provenance_patch())
                    self.assertIs(Router._acompletion_streaming_iterator, patched)

                    async def invoke(raw, label):
                        return await router._acompletion_streaming_iterator(
                            raw, [], {
                                "model": "deepseek/deepseek-chat",
                                "stream": True,
                                "request_label": label,
                            },
                        )

                    async def invoke_both():
                        return await asyncio.gather(invoke(raw_a, "a"), invoke(raw_b, "b"))

                    wrapped_a, wrapped_b = asyncio.run(invoke_both())
                    self.assertIs(wrapped_a._byok_raw_terminal_source, raw_a)
                    self.assertIs(wrapped_b._byok_raw_terminal_source, raw_b)
                    self.assertIs(wrapped_a._byok_terminal_provenance_token, guard._ROUTER_PROVENANCE_TOKEN)
                    self.assertIs(wrapped_b._byok_terminal_provenance_token, guard._ROUTER_PROVENANCE_TOKEN)
                    self.assertEqual([label for _, label in calls], ["a", "b"])

    def test_router_patch_refuses_version_or_method_shape_drift(self):
        async def original(self, model_response, messages, initial_kwargs, deployment_slot=None):
            return object()

        original.__module__ = "litellm.router"
        original.__qualname__ = "Router._acompletion_streaming_iterator"
        modules, Router, _, _ = self._fake_router_modules(original)
        untouched = Router._acompletion_streaming_iterator
        with patch.object(guard.importlib.metadata, "version", return_value="1.106.0"), patch.object(
            guard, "_ensure_deepseek_parser_patch", return_value=True,
        ):
            with patch.dict(sys.modules, modules):
                self.assertFalse(guard._ensure_router_provenance_patch())
                self.assertIs(Router._acompletion_streaming_iterator, untouched)

        async def mismatched(self, model_response, messages, initial_kwargs):
            return object()

        mismatched.__module__ = "litellm.router"
        mismatched.__qualname__ = "Router._acompletion_streaming_iterator"
        modules, Router, _, _ = self._fake_router_modules(mismatched)
        untouched = Router._acompletion_streaming_iterator
        with patch.object(guard.importlib.metadata, "version", return_value="1.105.0"), patch.object(
            guard, "_ensure_deepseek_parser_patch", return_value=True,
        ):
            with patch.object(guard.inspect, "getsourcefile", return_value="/tmp/foreign/router.py"):
                with patch.dict(sys.modules, modules):
                    self.assertFalse(guard._ensure_router_provenance_patch())
                    self.assertIs(Router._acompletion_streaming_iterator, untouched)

    def test_exact_stream_fails_closed_when_router_provenance_patch_is_unavailable(self):
        exact = {
            "api_key": "sk-synthetic-provider",
            "model": "deepseek/deepseek-chat",
            "stream": True,
        }
        result = run_hook(
            exact, "acompletion", patch_ready=False,
            env={
                "BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat",
                "BYOK_DENY_STREAMING_CALL_TYPES": "",
            },
        )
        self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_exact_stream_rejects_request_level_retry_and_fallback_overrides(self):
        exact = {
            "api_key": "sk-synthetic-provider",
            "model": "deepseek/deepseek-chat",
            "stream": True,
        }
        env = {
            "BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat",
            "BYOK_DENY_STREAMING_CALL_TYPES": "",
        }
        for override in (
            {"num_retries": 1},
            {"num_retries": "0"},
            {"fallbacks": ["other/model"]},
            {"context_window_fallbacks": ["other/model"]},
            {"content_policy_fallbacks": ["other/model"]},
            {"silent_model": "other/model"},
        ):
            with self.subTest(override=override):
                result = run_hook({**exact, **override}, "acompletion", env=env)
                self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))
        for harmless in (
            {"num_retries": 0},
            {"num_retries": None},
            {"fallbacks": []},
            {"fallbacks": None},
            {"context_window_fallbacks": []},
            {"content_policy_fallbacks": None},
        ):
            with self.subTest(harmless=harmless):
                result = run_hook({**exact, **harmless}, "acompletion", env=env)
                self.assertEqual(result[0], "allowed")

    def test_terminal_guard_diagnostics_are_opt_in_and_finitely_allowlisted(self):
        response = SimpleNamespace()
        source = SimpleNamespace(custom_llm_provider="arbitrary-provider-label")
        with patch.dict(os.environ, {}, clear=True):
            detail = guard._terminal_error_detail("boundary_type_mismatch", response, source, "1.105.0")
        self.assertEqual(detail, {"code": "T00_STREAM_TERMINAL_UNVERIFIED"})

        with patch.dict(
            os.environ, {"BYOK_T00_SYNTHETIC_GUARD_DIAGNOSTICS": "1"}, clear=True,
        ):
            detail = guard._terminal_error_detail("boundary_type_mismatch", response, source, "1.105.0")
        self.assertEqual(detail["code"], "T00_STREAM_TERMINAL_UNVERIFIED")
        self.assertEqual(detail["diagnostic"]["reason"], "boundary_type_mismatch")
        self.assertEqual(detail["diagnostic"]["litellm_version"], "1.105.0")
        self.assertEqual(detail["diagnostic"]["response_type"], "types.SimpleNamespace")
        self.assertEqual(detail["diagnostic"]["source_type"], "types.SimpleNamespace")
        self.assertEqual(detail["diagnostic"]["source_provider"], "other")
        self.assertNotIn("arbitrary-provider-label", repr(detail))

    def test_only_exact_deepseek_chat_stream_alias_is_exceptionally_allowed(self):
        exact = {
            "api_key": "sk-synthetic-provider",
            "model": "deepseek/deepseek-chat",
            "stream": True,
            "n": 1,
        }
        allowed = run_hook(
            exact, "acompletion",
            env={
                "BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat",
                "BYOK_DENY_STREAMING_CALL_TYPES": "",
            },
        )
        self.assertEqual(allowed[0], "allowed")
        for value in ("deepseek/other", "other/deepseek-chat", "deepseek/*"):
            with self.subTest(model=value):
                result = run_hook(
                    {**exact, "model": value}, "acompletion",
                    env={
                        "BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat",
                        "BYOK_DENY_STREAMING_CALL_TYPES": "",
                    },
                )
                self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_explicit_deny_still_overrides_exact_chat_stream_allowlist(self):
        exact = {
            "api_key": "sk-synthetic-provider",
            "model": "deepseek/deepseek-chat",
            "stream": True,
        }
        result = run_hook(
            exact, "acompletion",
            env={
                "BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat",
                "BYOK_DENY_STREAMING_CALL_TYPES": "acompletion",
            },
        )
        self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

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


class ParserRawTerminalEvidence(unittest.TestCase):
    def parser(self, allow_usage=False):
        return SimpleNamespace(
            _byok_raw_json_stop=False,
            _byok_exact_sse_done=False,
            _byok_terminal_invalid=False,
            _byok_terminal_usage_seen=False,
            _byok_terminal_usage_allowed=allow_usage,
        )

    @staticmethod
    def chunk(finish=None, *, index=0, content=None):
        return {
            "choices": [{
                "index": index,
                "finish_reason": finish,
                "delta": {"content": content} if content is not None else {},
            }],
        }

    def test_exact_raw_stop_and_done_are_independent_evidence(self):
        parser = self.parser()
        guard._record_raw_json_chunk(parser, self.chunk("stop"))
        self.assertTrue(parser._byok_raw_json_stop)
        self.assertFalse(parser._byok_exact_sse_done)
        guard._observe_sse_line(parser, "data: [DONE]")
        self.assertTrue(parser._byok_exact_sse_done)
        self.assertFalse(parser._byok_terminal_invalid)

    def test_done_without_raw_stop_is_invalid_and_cannot_prove_terminal(self):
        parser = self.parser()
        guard._observe_sse_line(parser, "data: [DONE]")
        self.assertFalse(parser._byok_raw_json_stop)
        self.assertTrue(parser._byok_terminal_invalid)

    def test_done_substring_inside_json_content_is_never_a_transport_marker(self):
        parser = self.parser()
        guard._observe_sse_line(
            parser,
            'data: {"choices":[{"index":0,"finish_reason":null,"delta":{"content":"literal [DONE]"}}]}',
        )
        self.assertFalse(parser._byok_exact_sse_done)
        self.assertTrue(parser._byok_terminal_invalid)

    def test_one_requested_usage_chunk_may_precede_or_follow_raw_stop(self):
        usage = {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
        for before_stop in (True, False):
            with self.subTest(before_stop=before_stop):
                parser = self.parser(allow_usage=True)
                if before_stop:
                    guard._record_raw_json_chunk(parser, usage)
                guard._record_raw_json_chunk(parser, self.chunk("stop"))
                if not before_stop:
                    guard._record_raw_json_chunk(parser, usage)
                self.assertTrue(parser._byok_raw_json_stop)
                self.assertFalse(parser._byok_terminal_invalid)

    def test_malformed_post_stop_json_is_rejected(self):
        parser = self.parser()
        guard._record_raw_json_chunk(parser, self.chunk("stop"))
        guard._observe_sse_line(parser, "data: {malformed-json")
        self.assertTrue(parser._byok_terminal_invalid)

    def test_only_exact_data_done_is_a_transport_marker(self):
        parser = self.parser()
        guard._record_raw_json_chunk(parser, self.chunk("stop"))
        guard._observe_sse_line(parser, "[DONE]")
        self.assertFalse(parser._byok_exact_sse_done)
        self.assertTrue(parser._byok_terminal_invalid)

    def test_rejects_unrequested_duplicate_or_nonusage_frames_after_stop(self):
        usage = {"choices": [], "usage": {"prompt_tokens": 2}}
        cases = (
            ([usage], False),
            ([usage, usage], True),
            ([self.chunk("stop"), usage, self.chunk(None, content="late content")], True),
            ([self.chunk("stop"), self.chunk("stop")], False),
            ([self.chunk("stop", index=1)], False),
            ([self.chunk("length")], False),
        )
        for sequence, allow_usage in cases:
            with self.subTest(sequence=sequence, allow_usage=allow_usage):
                parser = self.parser(allow_usage=allow_usage)
                for item in sequence:
                    guard._record_raw_json_chunk(parser, item)
                self.assertTrue(parser._byok_terminal_invalid)




class NativeParserPatch(unittest.TestCase):
    def test_exact_native_parser_patch_is_idempotent_and_token_gated(self):
        litellm = ModuleType("litellm")
        litellm.__path__ = []
        llms = ModuleType("litellm.llms")
        llms.__path__ = []
        openai = ModuleType("litellm.llms.openai")
        openai.__path__ = []
        chat = ModuleType("litellm.llms.openai.chat")
        chat.__path__ = []
        base_llm = ModuleType("litellm.llms.base_llm")
        base_llm.__path__ = []
        base_module = ModuleType("litellm.llms.base_llm.base_model_iterator")
        parser_module = ModuleType("litellm.llms.openai.chat.gpt_transformation")

        class BaseModelResponseIterator:
            async def __anext__(self):
                return "ordinary"

            def _handle_string_chunk(self, str_line):
                return str_line

            async def aclose(self):
                self.closed = True

        class OpenAIChatCompletionStreamingHandler(BaseModelResponseIterator):
            def chunk_parser(self, chunk):
                return chunk

        BaseModelResponseIterator.__module__ = "litellm.llms.base_llm.base_model_iterator"
        BaseModelResponseIterator._handle_string_chunk.__module__ = BaseModelResponseIterator.__module__
        BaseModelResponseIterator._handle_string_chunk.__qualname__ = "BaseModelResponseIterator._handle_string_chunk"
        BaseModelResponseIterator.__anext__.__module__ = BaseModelResponseIterator.__module__
        BaseModelResponseIterator.__anext__.__qualname__ = "BaseModelResponseIterator.__anext__"
        OpenAIChatCompletionStreamingHandler.__module__ = "litellm.llms.openai.chat.gpt_transformation"
        OpenAIChatCompletionStreamingHandler.__qualname__ = "OpenAIChatCompletionStreamingHandler"
        OpenAIChatCompletionStreamingHandler.chunk_parser.__module__ = OpenAIChatCompletionStreamingHandler.__module__
        OpenAIChatCompletionStreamingHandler.chunk_parser.__qualname__ = (
            "OpenAIChatCompletionStreamingHandler.chunk_parser"
        )
        base_module.BaseModelResponseIterator = BaseModelResponseIterator
        parser_module.OpenAIChatCompletionStreamingHandler = OpenAIChatCompletionStreamingHandler
        litellm.llms = llms
        llms.openai = openai
        llms.base_llm = base_llm
        openai.chat = chat
        chat.gpt_transformation = parser_module
        base_llm.base_model_iterator = base_module
        modules = {
            "litellm": litellm,
            "litellm.llms": llms,
            "litellm.llms.openai": openai,
            "litellm.llms.openai.chat": chat,
            "litellm.llms.openai.chat.gpt_transformation": parser_module,
            "litellm.llms.base_llm": base_llm,
            "litellm.llms.base_llm.base_model_iterator": base_module,
        }

        def source_file(method):
            if method.__module__ == OpenAIChatCompletionStreamingHandler.__module__:
                return "/fake/site-packages/litellm/llms/openai/chat/gpt_transformation.py"
            return "/fake/site-packages/litellm/llms/base_llm/base_model_iterator.py"

        with patch.object(guard.importlib.metadata, "version", return_value="1.105.0"), patch.object(
            guard.inspect, "getsourcefile", side_effect=source_file,
        ), patch.dict(sys.modules, modules):
            self.assertTrue(guard._ensure_deepseek_parser_patch())
            patched = OpenAIChatCompletionStreamingHandler.__dict__["__anext__"]
            self.assertIs(patched, guard._PARSER_PATCHED_ANEXT)
            self.assertTrue(guard._ensure_deepseek_parser_patch())
            self.assertIs(OpenAIChatCompletionStreamingHandler.__dict__["__anext__"], patched)

            ordinary = OpenAIChatCompletionStreamingHandler()
            self.assertEqual(asyncio.run(ordinary.__anext__()), "ordinary")

            done = OpenAIChatCompletionStreamingHandler()
            done._byok_raw_terminal_parser_token = guard._PARSER_PROVENANCE_TOKEN
            done._byok_terminal_invalid = False
            done._byok_exact_sse_done = True
            with self.assertRaises(StopAsyncIteration):
                asyncio.run(done.__anext__())
            self.assertTrue(done.closed)

            async def replacement(self):
                return "replaced"

            OpenAIChatCompletionStreamingHandler.__anext__ = replacement
            try:
                self.assertFalse(guard._ensure_deepseek_parser_patch())
            finally:
                OpenAIChatCompletionStreamingHandler.__anext__ = patched



if __name__ == "__main__":
    unittest.main()
