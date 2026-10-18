"""Negative controls for the T00 runner; no provider, Docker, or DB required."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import signal
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_runtime
import probe
import protocol_cases
import proxy_process


class ProbeContracts(unittest.TestCase):
    def test_cli_help_has_no_runtime_side_effects(self):
        with patch.object(local_runtime.LocalProxy, "start") as start:
            with self.assertRaises(SystemExit) as stopped:
                probe.main(["--help"])
            self.assertEqual(stopped.exception.code, 0)
            start.assert_not_called()

    def test_unknown_arguments_fail_before_runtime(self):
        with patch.object(local_runtime.LocalProxy, "start") as start:
            with self.assertRaises(SystemExit) as stopped:
                probe.main(["--proxy-python", sys.executable, "--provider-real"])
            self.assertEqual(stopped.exception.code, 2)
            start.assert_not_called()

    def test_fixture_import_opens_no_listener(self):
        with patch("socket.socket") as construct:
            module = importlib.import_module("upstream")
            importlib.reload(module)
            construct.assert_not_called()

    def test_isolated_environment_drops_keys_proxy_and_database(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic", "ANTHROPIC_API_KEY": "synthetic", "DATABASE_URL": "synthetic", "HTTPS_PROXY": "synthetic", "LITELLM_MASTER_KEY": "synthetic"}):
            env = local_runtime.isolated_env()
        self.assertEqual(set(env), {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "DO_NOT_TRACK"})
        self.assertNotIn("synthetic", env.values())

    def test_urls_are_loopback_only_before_creating_sdk(self):
        for url in ("https://api.openai.com/v1", "http://localhost:40", "http://127.0.0.1.evil:40", "http://user:secret@127.0.0.1:40", "file:///tmp/key"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                protocol_cases.openai_client("synthetic", url)
        self.assertEqual(protocol_cases.validate_loopback_url("http://127.0.0.1:123/v1"), "http://127.0.0.1:123/v1")

    def test_proxy_audit_hook_blocks_non_loopback(self):
        fake_socket = SimpleNamespace(family=socket.AF_INET)
        for address in ("api.anthropic.com", "192.0.2.1"):
            with self.subTest(address=address), self.assertRaises(PermissionError):
                proxy_process.loopback_only("socket.connect", (fake_socket, (address, 443)))
        proxy_process.loopback_only("socket.connect", (fake_socket, ("127.0.0.1", 4000)))

    def test_proxy_uses_audited_asyncio_even_when_uvloop_is_installed(self):
        fake_uvicorn = MagicMock()
        fake_app = object()
        modules = {"uvicorn": fake_uvicorn, "litellm.proxy.proxy_server": SimpleNamespace(app=fake_app)}
        with patch.dict(sys.modules, modules), patch.object(sys, "argv", ["proxy_process.py", "--config", "synthetic", "--port", "12345"]), patch.object(proxy_process.importlib.metadata, "version", return_value="1.105.0"), patch.object(sys, "addaudithook") as audit, patch.dict(os.environ):
            proxy_process.main()
        audit.assert_called_once_with(proxy_process.loopback_only)
        self.assertEqual(fake_uvicorn.run.call_args.kwargs["loop"], "asyncio")

    def test_native_terminal_requires_complete_protocol_evidence(self):
        self.assertFalse(probe.stream_complete("responses", {"event_types": ["response.completed"], "terminals": []}))
        self.assertFalse(probe.stream_complete("messages", {"event_types": ["message_stop"], "terminals": ["max_tokens"]}))
        self.assertFalse(probe.stream_complete("chat", {"event_types": ["chat.chunk"], "terminals": []}))
        self.assertTrue(probe.stream_complete("messages", {"event_types": ["message_stop"], "terminals": ["end_turn"]}))

    def test_responses_failed_requires_native_failed_status(self):
        event = SimpleNamespace(type="response.failed", response=SimpleNamespace(status="failed"))
        self.assertEqual(protocol_cases._stream_event_facts("responses", event), ("response.failed", "failed"))
        self.assertTrue(probe.stream_error_detected({"success": True, "event_types": ["response.failed"], "terminals": ["failed"]}))
        self.assertFalse(probe.stream_error_detected({"success": True, "event_types": ["response.failed"], "terminals": []}))

    def test_scope_cannot_pass_without_executed_cases(self):
        self.assertEqual(probe.scope_status([], "PROXY", started=False, completed=False), "NOT_RUN")
        self.assertEqual(probe.scope_status([], "PROXY", started=True, completed=True), "FAIL")
        checks = [{"case": "PROXY_CHAT_COMPLETE", "status": "PASS"}]
        self.assertEqual(probe.scope_status(checks, "PROXY", started=True, completed=False), "FAIL")

    def test_shared_cleanup_or_resource_failure_fails_each_executed_scope(self):
        for failure in ("LOCAL_RUNTIME_CLEANUP", "ALL_SDK_CLIENTS_CLOSED", "UPSTREAM_PRODUCERS_CLOSED", "RUNTIME"):
            checks = [{"case": "SDK_COMPLETE", "status": "PASS"}, {"case": "PROXY_COMPLETE", "status": "PASS"}, {"case": failure, "status": "FAIL"}]
            for scope in ("SDK", "PROXY"):
                self.assertEqual(probe.scope_status(checks, scope, started=True, completed=True), "FAIL")

    def test_invalid_tool_requires_zero_actual_dispatch(self):
        for result in (
            {"success": False, "dispatched": True, "tool_dispatch_count": 1},
            {"success": False, "dispatched": False},
            {"success": False, "dispatched": False, "tool_dispatch_count": 0, "error_type": "APIConnectionError"},
            {"success": True, "dispatched": False, "tool_dispatch_count": 0},
        ):
            self.assertFalse(probe.invalid_tool_rejected(result))
        self.assertTrue(probe.invalid_tool_rejected({"success": True, "dispatched": False, "tool_dispatch_count": 0, "rejection": "not_allowlisted"}))

    def test_partial_and_unknown_tool_arguments_never_dispatch(self):
        before = protocol_cases.TOOL_DISPATCH_COUNT
        for name, args in (("lookup_weather", '{"city":'), ("lookup_weather", "{nope}"), ("not_allowed", '{}'), ("lookup_weather", {"city": "synthetic-city", "extra": True})):
            status, output = protocol_cases.dispatch_synthetic_tool(name, args)
            self.assertNotEqual(status, "dispatched")
            self.assertIsNone(output)
        self.assertEqual(protocol_cases.TOOL_DISPATCH_COUNT, before)

    def test_incomplete_tool_turn_fails_before_dispatch(self):
        reply = SimpleNamespace(choices=[SimpleNamespace(finish_reason="length")])
        client = MagicMock()
        client.chat.completions.create.return_value = reply
        before = protocol_cases.TOOL_DISPATCH_COUNT
        with patch.object(protocol_cases, "openai_client", return_value=client):
            result = protocol_cases.proxy_tool_roundtrip("chat", "http://127.0.0.1:1", "project", "provider")
        self.assertIs(result["success"], False)
        self.assertEqual(protocol_cases.TOOL_DISPATCH_COUNT, before)
        client.chat.completions.create.assert_called_once()
        client.close.assert_called_once()

    def test_safe_terminal_guard_diagnostic_is_limited_to_synthetic_allowlisted_fields(self):
        body = {
            "detail": {
                "code": "T00_STREAM_TERMINAL_UNVERIFIED",
                "diagnostic": {
                    "reason": "router_wrapper_type_mismatch",
                    "litellm_version": "1.105.0",
                    "response_type": "litellm.proxy.utils._UpstreamStreamBoundary",
                    "source_type": "litellm.router.Router._acompletion_streaming_iterator.<locals>.FallbackStreamWrapper",
                    "source_provider": "deepseek",
                    "provider_key": "sk-synthetic-secret",
                    "prompt": "private prompt",
                },
            },
            "private": "must not escape",
        }
        error = SimpleNamespace(response=SimpleNamespace(status_code=502, json=lambda: body))
        self.assertEqual(probe._safe_terminal_guard_diagnostic(error), {
            "reason": "router_wrapper_type_mismatch",
            "litellm_version": "1.105.0",
            "response_type": "litellm.proxy.utils._UpstreamStreamBoundary",
            "source_type": "litellm.router.Router._acompletion_streaming_iterator.<locals>.FallbackStreamWrapper",
            "source_provider": "deepseek",
        })
        wrong_status = SimpleNamespace(response=SimpleNamespace(status_code=400, json=lambda: body))
        self.assertIsNone(probe._safe_terminal_guard_diagnostic(wrong_status))
        unknown_reason_body = {
            "detail": {"code": "T00_STREAM_TERMINAL_UNVERIFIED", "diagnostic": {
                "reason": "arbitrary provider exception",
                "litellm_version": "1.105.0",
                "response_type": "types.SimpleNamespace",
                "source_type": "types.SimpleNamespace",
                "source_provider": "deepseek",
            }},
        }
        unknown_reason = SimpleNamespace(response=SimpleNamespace(
            status_code=502, json=lambda: unknown_reason_body,
        ))
        self.assertIsNone(probe._safe_terminal_guard_diagnostic(unknown_reason))
        unknown_provider_body = {
            "detail": {"code": "T00_STREAM_TERMINAL_UNVERIFIED", "diagnostic": {
                "reason": "router_wrapper_type_mismatch",
                "litellm_version": "1.105.0",
                "response_type": "types.SimpleNamespace",
                "source_type": "types.SimpleNamespace",
                "source_provider": "arbitrary-provider-name",
            }},
        }
        unknown_provider = SimpleNamespace(response=SimpleNamespace(
            status_code=502, json=lambda: unknown_provider_body,
        ))
        self.assertIsNone(probe._safe_terminal_guard_diagnostic(unknown_provider))
        malformed = SimpleNamespace(response=SimpleNamespace(status_code=502, json=lambda: {
            "detail": {"code": "T00_STREAM_TERMINAL_UNVERIFIED", "diagnostic": {
                "reason": "router_wrapper_type_mismatch", "litellm_version": "1.105.0",
                "response_type": "x\nsk-secret", "source_type": "litellm.router.Router._acompletion_streaming_iterator.<locals>.FallbackStreamWrapper",
            }},
        }))
        self.assertIsNone(probe._safe_terminal_guard_diagnostic(malformed))

    def test_exception_report_excludes_body_keys_and_continuation(self):
        error = RuntimeError("synthetic-secret-and-private-continuation")
        result = protocol_cases.safe_exception(error)
        self.assertEqual(result, {"success": False, "status_code": None, "error_type": "RuntimeError"})

    def test_all_protocols_reject_incomplete_final_answer(self):
        def block(**values):
            value = SimpleNamespace(**values)
            value.model_dump = lambda **_kwargs: values
            return value
        for protocol in ("chat", "responses", "messages"):
            client = MagicMock()
            turns = []
            for i, (name, arg) in enumerate((("lookup_weather", {"city": "synthetic-city"}), ("format_weather", {"summary": "synthetic-weather"})), start=1):
                if protocol == "chat":
                    item = block(role="assistant", tool_calls=[block(id=f"call_{i}", function=block(name=name, arguments=json.dumps(arg)))])
                    turns.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=item)]))
                elif protocol == "responses":
                    turns.append(SimpleNamespace(status="completed", output=[block(type="function_call", name=name, arguments=json.dumps(arg), call_id=f"call_{i}")]))
                else:
                    turns.append(SimpleNamespace(stop_reason="tool_use", content=[block(type="tool_use", name=name, input=arg, id=f"call_{i}")]))
            if protocol == "chat":
                turns.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="length", message=block(content="partial answer"))]))
                client.chat.completions.create.side_effect = turns
            elif protocol == "responses":
                turns.append(SimpleNamespace(status="incomplete", output_text="partial answer"))
                client.responses.create.side_effect = turns
            else:
                turns.append(SimpleNamespace(stop_reason="max_tokens", content=[block(type="text", text="partial answer")]))
                client.messages.create.side_effect = turns
            factory = "anthropic_client" if protocol == "messages" else "openai_client"
            with self.subTest(protocol=protocol), patch.object(protocol_cases, factory, return_value=client):
                result = protocol_cases.proxy_tool_roundtrip(protocol, "http://127.0.0.1:1", "project", "provider")
                self.assertIs(result["success"], False)
                self.assertNotIn("public_output", result)
                client.close.assert_called_once()

    def test_receipts_reject_wrong_model_protocol_extra_requests(self):
        row = {"tenant": "tenant-b", "provider_key_match": True, "project_key_match": False, "model": "other-test-model", "protocol": "completions"}
        self.assertTrue(probe.receipt_matches([row], 1, "tenant-b", "completions"))
        self.assertFalse(probe.receipt_matches([{**row, "model": "test-model"}], 1, "tenant-b", "completions"))
        self.assertFalse(probe.receipt_matches([{**row, "protocol": "messages"}], 1, "tenant-b", "completions"))
        self.assertFalse(probe.receipt_matches([row, row], 1, "tenant-b", "completions"))
        expected = [("SDK", "T00_EXPECTED", 1, "tenant-a", None)]
        self.assertTrue(probe.receipts_exhaustive([{"test_id": "T00_EXPECTED"}], expected))
        self.assertFalse(probe.receipts_exhaustive([{"test_id": "T00_EXPECTED"}, {"test_id": "T00_UNKNOWN"}], expected))

    def test_sigterm_is_a_controlled_interrupt(self):
        with self.assertRaises(KeyboardInterrupt):
            probe.interrupted(signal.SIGTERM, None)

    def test_interrupt_before_or_during_stream_always_closes_sdk(self):
        for protocol in ("chat", "responses", "messages"):
            for stage in ("create", "iterate"):
                client = MagicMock()
                method = client.chat.completions.create if protocol == "chat" else client.responses.create if protocol == "responses" else client.messages.create
                stream = MagicMock()
                if stage == "create":
                    method.side_effect = KeyboardInterrupt("T00_INTERRUPTED")
                else:
                    method.return_value = stream
                    stream.__iter__.side_effect = KeyboardInterrupt("T00_INTERRUPTED")
                with self.subTest(protocol=protocol, stage=stage), patch.object(protocol_cases, "protocol_client", return_value=client):
                    with self.assertRaisesRegex(KeyboardInterrupt, "T00_INTERRUPTED"):
                        protocol_cases.run_protocol_stream_case("http://127.0.0.1:1", protocol, "COMPLETE", "synthetic")
                    client.close.assert_called_once()
                    if stage == "iterate":
                        stream.close.assert_called_once()


class ProviderKeyGuardFailClosed(unittest.TestCase):
    """Only the exact raw-terminal DeepSeek route may pass the stream guard.

    The guard file lives in ops/shared-litellm-proxy; LiteLLM/FastAPI are
    stubbed when absent (SDK venv) so this runs in the CI T00 step.
    Other Chat aliases remain fail-closed; native Responses/Messages preserve
    their prior behavior. Runtime router provenance is verified only by the
    disposable real LocalProxy integration, not by this unit fixture.
    """

    @staticmethod
    def _load_guard():
        guard_path = Path(__file__).resolve().parents[2] / "ops/shared-litellm-proxy/provider_key_guard.py"
        fastapi = ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code, detail):
                super().__init__(detail)
                self.status_code, self.detail = status_code, detail

        fastapi.HTTPException = HTTPException
        custom_logger = ModuleType("litellm.integrations.custom_logger")
        custom_logger.CustomLogger = type("CustomLogger", (), {})
        integrations = ModuleType("litellm.integrations")
        integrations.custom_logger = custom_logger
        litellm = ModuleType("litellm")
        litellm.integrations = integrations
        stubs = {"fastapi": fastapi, "litellm": litellm, "litellm.integrations": integrations,
                 "litellm.integrations.custom_logger": custom_logger}
        spec = importlib.util.spec_from_file_location("provider_key_guard_t00_test", guard_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(module)
        return module

    @classmethod
    def setUpClass(cls):
        cls.guard = cls._load_guard()

    def run_hook(self, data, call_type, env=None, *, patch_ready=True):
        hook = self.guard.ProviderKeyGuard().async_pre_call_hook(
            user_api_key_dict=SimpleNamespace(), cache=None, data=dict(data), call_type=call_type)
        values = {"BYOK_TERMINAL_STREAMING_MODELS": "", "BYOK_DENY_STREAMING_CALL_TYPES": ""}
        values.update(env or {})
        with patch.dict(os.environ, values, clear=False), patch.object(
            self.guard, "_ensure_router_provenance_patch", return_value=patch_ready,
        ):
            try:
                asyncio.run(hook)
            except Exception as exc:
                detail = getattr(exc, "detail", {})
                return ("rejected", getattr(exc, "status_code", None),
                        detail.get("code") if isinstance(detail, dict) else None)
        return ("allowed", None, None)

    def test_chat_stream_unknown_route_rejected_before_upstream(self):
        data = {"api_key": "sk-synthetic-provider", "model": "t00-chat", "stream": True}
        self.assertEqual(self.run_hook(data, "acompletion", {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat"}),
                         ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_rejected_despite_empty_or_omitting_deny_env(self):
        data = {"api_key": "sk-synthetic-provider", "model": "deepseek/deepseek-chat", "stream": True}
        allow = {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat"}
        for env in (
                    {**allow, "BYOK_DENY_STREAMING_CALL_TYPES": "acompletion"},
                    {**allow, "BYOK_DENY_STREAMING_CALL_TYPES": "ACOMPLETION"}):
            with self.subTest(env=env):
                self.assertEqual(self.run_hook(data, "acompletion", env), ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_stream_string_and_numeric_flags_rejected(self):
        for flag in ("true", "True", "1", 1):
            with self.subTest(flag=flag):
                result = self.run_hook({"api_key": "sk-synthetic-provider", "model": "deepseek/deepseek-chat", "stream": flag}, "acompletion", {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat"})
                self.assertEqual(result, ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))
        self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider", "model": "deepseek/deepseek-chat", "stream": True}, "completion", {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat"}),
                         ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))

    def test_chat_short_truth_aliases_and_unknown_shapes_are_denied(self):
        for flag in ("t", "T", "y", "Y", "unknown", "", 2, -1, {}, []):
            with self.subTest(flag=flag):
                self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider", "stream": flag}, "acompletion"),
                                 ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"))
        for flag in ("f", "n", "no", "off", "0", 0, False, None):
            with self.subTest(non_stream_flag=flag):
                self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider", "stream": flag}, "acompletion")[0],
                                 "allowed")

    def test_only_exact_deepseek_route_without_overrides_is_allowlisted(self):
        allow = {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat"}
        valid = {"api_key": "sk-synthetic-provider", "model": "deepseek/deepseek-chat", "stream": True}
        self.assertEqual(self.run_hook(valid, "acompletion", allow), ("allowed", None, None))
        for invalid in (
            {**valid, "model": "deepseek/another-model"},
            {**valid, "model": "deepseek/*"},
            {**valid, "api_base": "http://127.0.0.1:9999"},
            {**valid, "base_url": "http://127.0.0.1:9999"},
            {**valid, "n": 2},
            {**valid, "tools": [{"type": "function"}]},
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.run_hook(invalid, "acompletion", allow)[0], "rejected")
        self.assertEqual(
            self.run_hook(valid, "acompletion", {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/*"})[0],
            "rejected",
        )
        self.assertEqual(
            self.run_hook(valid, "completion", allow),
            ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"),
        )

    def test_exact_route_rejected_if_router_provenance_patch_is_unavailable(self):
        data = {"api_key": "sk-synthetic-provider", "model": "deepseek/deepseek-chat", "stream": True}
        allow = {"BYOK_TERMINAL_STREAMING_MODELS": "deepseek/deepseek-chat"}
        self.assertEqual(
            self.run_hook(data, "acompletion", allow, patch_ready=False),
            ("rejected", 400, "T00_CHAT_STREAMING_DISABLED"),
        )

    def test_native_responses_and_messages_streaming_keep_existing_behavior(self):
        self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider"}, "acompletion")[0], "allowed")
        self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider", "stream": False}, "acompletion")[0], "allowed")
        for call_type in ("aresponses", "anthropic_messages"):
            self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider", "stream": False}, call_type)[0], "allowed")
            self.assertEqual(self.run_hook({"api_key": "sk-synthetic-provider", "stream": True}, call_type)[0], "allowed")
            self.assertEqual(
                self.run_hook(
                    {"api_key": "sk-synthetic-provider", "stream": True},
                    call_type,
                    {"BYOK_DENY_STREAMING_CALL_TYPES": call_type},
                ),
                ("rejected", 400, "T00_STREAMING_DISABLED"),
            )



    def _iterator_guard(
        self,
        *,
        source_reason="stop",
        response_kind="boundary",
        version="1.105.0",
        post_terminal_error=False,
        tool_calls=False,
        provenance_token="valid",
        raw_source="valid",
        fallback_activated=False,
        fallback_activated_after_first=False,
    ):
        guard = self.guard

        class FakeCustomStreamWrapper:
            def __init__(self):
                self.custom_llm_provider = "deepseek"
                self.received_finish_reason = None
                self.raw_finish_reason = source_reason
                self.failure = None
                self.closed = False
                delta = SimpleNamespace(
                    content="hello",
                    tool_calls=[{"id": "call"}] if tool_calls else None,
                    refusal=None,
                )
                self.chunks = [
                    SimpleNamespace(choices=[SimpleNamespace(finish_reason=None, delta=delta)], usage=None),
                    SimpleNamespace(
                        choices=[SimpleNamespace(
                            finish_reason="stop",
                            delta=SimpleNamespace(content=None, tool_calls=None, refusal=None),
                        )],
                        usage=None,
                    ),
                ]

            def __aiter__(self):
                async def iterate():
                    for item in self.chunks:
                        choices = getattr(item, "choices", None) or []
                        if choices and getattr(choices[0], "finish_reason", None) is not None:
                            self.received_finish_reason = self.raw_finish_reason
                        yield item
                    if post_terminal_error:
                        raise RuntimeError("synthetic error after provider stop")
                return iterate()

            async def aclose(self):
                self.closed = True

        class FakeFallbackAwareStreamWrapper(FakeCustomStreamWrapper):
            pass

        FakeCustomStreamWrapper.__module__ = "litellm.litellm_core_utils.streaming_handler"
        FakeFallbackAwareStreamWrapper.__module__ = "litellm.router"

        class FakeRouterFallbackStreamWrapper(FakeFallbackAwareStreamWrapper):
            def __init__(self, source):
                self.custom_llm_provider = "deepseek"
                self.failure = None
                self.fallback_headers_adopted = bool(fallback_activated)
                self._test_source = source
                if raw_source == "valid":
                    setattr(self, guard._ROUTER_RAW_SOURCE_ATTR, source)
                elif raw_source == "missing":
                    setattr(self, guard._ROUTER_RAW_SOURCE_ATTR, None)
                if provenance_token == "valid":
                    setattr(
                        self,
                        guard._ROUTER_PROVENANCE_TOKEN_ATTR,
                        guard._ROUTER_PROVENANCE_TOKEN,
                    )
                elif provenance_token == "wrong":
                    setattr(self, guard._ROUTER_PROVENANCE_TOKEN_ATTR, object())

            def __aiter__(self):
                async def iterate():
                    count = 0
                    async for item in self._test_source:
                        yield item
                        if count == 0 and fallback_activated_after_first:
                            self.fallback_headers_adopted = True
                        count += 1
                return iterate()

            async def aclose(self):
                await self._test_source.aclose()

        FakeRouterFallbackStreamWrapper.__module__ = "litellm.router"
        FakeRouterFallbackStreamWrapper.__qualname__ = (
            "Router._acompletion_streaming_iterator.<locals>.FallbackStreamWrapper"
        )

        class FakeBoundary:
            def __init__(self, source):
                self._source = source

            def __getattr__(self, name):
                return getattr(self._source, name)

            def __aiter__(self):
                return self._source.__aiter__()

            async def aclose(self):
                await self._source.aclose()

        class UnknownBoundary(FakeBoundary):
            pass

        litellm = ModuleType("litellm")
        litellm.__path__ = []
        proxy_pkg = ModuleType("litellm.proxy")
        proxy_pkg.__path__ = []
        proxy_utils = ModuleType("litellm.proxy.utils")
        proxy_utils._UpstreamStreamBoundary = FakeBoundary
        proxy_pkg.utils = proxy_utils
        router_module = ModuleType("litellm.router")
        router_module.FallbackAwareStreamWrapper = FakeFallbackAwareStreamWrapper
        streaming_pkg = ModuleType("litellm.litellm_core_utils")
        streaming_pkg.__path__ = []
        streaming_handler = ModuleType("litellm.litellm_core_utils.streaming_handler")
        streaming_handler.CustomStreamWrapper = FakeCustomStreamWrapper
        litellm.proxy = proxy_pkg
        litellm.router = router_module
        litellm.litellm_core_utils = streaming_pkg
        source = FakeCustomStreamWrapper()
        router_source = FakeRouterFallbackStreamWrapper(source)
        boundary_class = UnknownBoundary if response_kind == "unknown" else FakeBoundary
        response = boundary_class(router_source)
        patch_modules = {
            "litellm": litellm,
            "litellm.proxy": proxy_pkg,
            "litellm.proxy.utils": proxy_utils,
            "litellm.router": router_module,
            "litellm.litellm_core_utils": streaming_pkg,
            "litellm.litellm_core_utils.streaming_handler": streaming_handler,
        }
        yielded = []

        async def collect():
            async for item in guard.ProviderKeyGuard().async_post_call_streaming_iterator_hook(
                response=response,
                user_api_key_dict=SimpleNamespace(),
                request_data={"model": "deepseek/deepseek-chat", "stream": True},
            ):
                yielded.append(item)

        with patch.dict(sys.modules, patch_modules), patch.object(
            guard.importlib.metadata, "version", return_value=version,
        ):
            try:
                asyncio.run(collect())
                error = None
            except Exception as exc:
                error = exc
        return yielded, error, source

    @staticmethod
    def _has_stop_frame(output):
        return any(
            choices and getattr(choices[0], "finish_reason", None) == "stop"
            for choices in (getattr(item, "choices", None) or [] for item in output)
        )

    def test_whole_iterator_releases_only_verified_raw_stop_after_clean_eof(self):
        output, error, source = self._iterator_guard(source_reason="stop")
        self.assertIsNone(error)
        self.assertEqual(len(output), 2)
        self.assertTrue(self._has_stop_frame(output))
        self.assertTrue(source.closed)

    def test_whole_iterator_rejects_missing_provenance_and_fallbacks(self):
        cases = (
            {"source_reason": None},
            {"response_kind": "unknown"},
            {"version": "1.106.0"},
            {"provenance_token": "missing"},
            {"provenance_token": "wrong"},
            {"raw_source": "missing"},
            {"raw_source": "absent"},
            {"fallback_activated": True},
            {"fallback_activated_after_first": True},
        )
        for case in cases:
            with self.subTest(case=case):
                output, error, source = self._iterator_guard(**case)
                self.assertFalse(self._has_stop_frame(output))
                self.assertEqual(getattr(error, "status_code", None), 502)
                self.assertEqual(
                    getattr(error, "detail", {}).get("code"),
                    "T00_STREAM_TERMINAL_UNVERIFIED",
                )
                self.assertTrue(source.closed)

    def test_whole_iterator_never_releases_stop_if_source_errors_or_emits_tools(self):
        for case in ({"post_terminal_error": True}, {"tool_calls": True}):
            with self.subTest(case=case):
                output, error, source = self._iterator_guard(**case)
                self.assertFalse(self._has_stop_frame(output))
                self.assertIsNotNone(error)
                self.assertTrue(source.closed)




class RuntimeCleanup(unittest.TestCase):
    def runtime(self):
        with patch.object(local_runtime, "free_port", return_value=4444):
            return local_runtime.LocalProxy(sys.executable, "http://127.0.0.1:1")

    def test_poll_kill_race_still_closes_every_resource(self):
        runtime = self.runtime()
        child = MagicMock(pid=12345)
        child.poll.side_effect = [None, 0]
        handle = MagicMock()
        runtime.processes = [child]
        runtime.handles = [handle]
        runtime.runtime = Path("/tmp/t00-owned-runtime")
        runtime.pgroot = Path("/tmp/t00-owned-postgres")
        with patch.object(local_runtime.os, "killpg", side_effect=ProcessLookupError), patch.object(local_runtime.shutil, "rmtree") as remove:
            runtime.close()
        self.assertTrue(runtime.cleanup_complete)
        handle.close.assert_called_once()
        self.assertEqual(remove.call_count, 2)

    def test_one_cleanup_failure_does_not_abandon_later_resources(self):
        runtime = self.runtime()
        children = [MagicMock(pid=1), MagicMock(pid=2)]
        for child in children:
            child.poll.return_value = None
        runtime.processes = children
        runtime.handles = [MagicMock(), MagicMock()]
        runtime.runtime = Path("/tmp/t00-owned-runtime")
        runtime.pgroot = Path("/tmp/t00-owned-postgres")
        with patch.object(local_runtime.os, "killpg", side_effect=PermissionError), patch.object(local_runtime.shutil, "rmtree", side_effect=[PermissionError, None]) as remove:
            runtime.close()
        self.assertFalse(runtime.cleanup_complete)
        self.assertEqual(remove.call_count, 2)
        for handle in runtime.handles:
            handle.close.assert_called_once()

    def test_start_failure_always_runs_cleanup(self):
        runtime = self.runtime()
        with patch.object(runtime, "start", side_effect=RuntimeError("T00_INIT_FAILED")), patch.object(runtime, "close") as close:
            with self.assertRaises(RuntimeError):
                runtime.__enter__()
        close.assert_called_once()

    def test_exited_leader_still_terminates_live_descendant_group(self):
        runtime = self.runtime()
        child = MagicMock(pid=12345)
        child.poll.return_value = 0
        runtime.processes = [child]
        with patch.object(local_runtime.os, "killpg") as kill, patch.object(local_runtime, "group_has_live_members", side_effect=[True, False, False, False, False]), patch.object(local_runtime.time, "sleep"):
            runtime.close()
        kill.assert_any_call(child.pid, signal.SIGTERM)
        self.assertTrue(runtime.cleanup_complete)

    def test_real_orphaned_descendant_is_stopped(self):
        runtime = self.runtime()
        code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); print(p.pid,flush=True)"
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        runtime.processes = [child]
        try:
            child.communicate(timeout=5)
            self.assertIsNotNone(child.poll())
            self.assertTrue(local_runtime.group_has_live_members(child.pid))
            runtime.close()
            self.assertTrue(runtime.cleanup_complete)
            self.assertFalse(local_runtime.group_has_live_members(child.pid))
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    unittest.main()
