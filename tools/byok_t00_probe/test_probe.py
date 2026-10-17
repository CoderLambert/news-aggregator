"""Negative controls for the T00 runner; no provider, Docker, or DB required."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import signal
import sys
import tempfile
from types import SimpleNamespace
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
