"""End-to-end tests using installed official SDKs and a loopback HTTP server."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from .adapters import ChatCompletionsAdapter, MessagesAdapter, ResponsesAdapter
from .contracts import ModelEvent, ProviderError
from .upstream import LoopbackUpstream


SYNTHETIC_A = "synthetic-provider-key-a"
SYNTHETIC_B = "synthetic-provider-key-b"
MODEL_A = "synthetic-model-alpha"
MODEL_B = "synthetic-model-beta"


class SDKProtocolProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = LoopbackUpstream()
        cls.upstream.__enter__()
        cls.base_url = cls.upstream.base_url

    @classmethod
    def tearDownClass(cls):
        cls.upstream.__exit__(None, None, None)

    def setUp(self):
        state = self.upstream.state
        with state.lock:
            state.records.clear()
            state.counts.clear()
        state.cancel_observed.clear()

    def adapters(self, key: str = SYNTHETIC_A):
        return [
            (
                "chat",
                ChatCompletionsAdapter(key, self.base_url + "/v1"),
                lambda adapter, marker, **kwargs: adapter.turn(
                    model=kwargs.get("model", MODEL_A),
                    messages=[{"role": "user", "content": marker}],
                    **{k: v for k, v in kwargs.items() if k != "model"},
                ),
            ),
            (
                "responses",
                ResponsesAdapter(key, self.base_url + "/v1"),
                lambda adapter, marker, **kwargs: adapter.turn(
                    model=kwargs.get("model", MODEL_A),
                    input=marker,
                    **{k: v for k, v in kwargs.items() if k != "model"},
                ),
            ),
            (
                "messages",
                MessagesAdapter(key, self.base_url),
                lambda adapter, marker, **kwargs: adapter.turn(
                    model=kwargs.get("model", MODEL_A),
                    messages=[{"role": "user", "content": marker}],
                    **{k: v for k, v in kwargs.items() if k != "model"},
                ),
            ),
        ]

    def _request(self, protocol: str, call, adapter, marker: str, **kwargs):
        return call(adapter, marker, **kwargs)

    def _count(self, marker: str) -> int:
        _records, counts = self.upstream.state.snapshot()
        return counts.get(marker, 0)

    def test_complete_terminal_states_and_public_continuation_boundary(self):
        expected = {
            "chat": "stop",
            "responses": "completed",
            "messages": "end_turn",
        }
        for protocol, adapter, call in self.adapters():
            marker = f"T00:CASE:COMPLETE:{protocol}"
            with self.subTest(protocol=protocol), adapter:
                turn = self._request(protocol, call, adapter, marker)
                self.assertEqual(turn.finish_reason, expected[protocol])
                self.assertEqual(turn.text, "sdk-local-ok")
                self.assertTrue(any(event.kind == "terminal" for event in turn.events))
                public = turn.public_message()
                self.assertEqual(public, {"role": "assistant", "content": "sdk-local-ok"})
                self.assertNotIn("continuation", public)
                self.assertNotIn("reasoning_content", public)
                self.assertNotIn("signature", str(public))
                self.assertEqual(self._count(marker), 1)

    def test_eof_and_native_incomplete_reasons_fail_closed(self):
        allowed_eof_codes = {"stream_eof_without_terminal", "provider_stream_error"}
        for protocol, adapter, call in self.adapters():
            eof_marker = f"T00:CASE:EOF:{protocol}"
            with self.subTest(protocol=protocol, case="eof"), adapter:
                with self.assertRaises(ProviderError) as raised:
                    self._request(protocol, call, adapter, eof_marker)
                self.assertIn(raised.exception.code, allowed_eof_codes)
                self.assertEqual(self._count(eof_marker), 1)
            length_marker = f"T00:CASE:LENGTH:{protocol}"
            with self.subTest(protocol=protocol, case="length"):
                with self._adapter_for(protocol) as fresh:
                    with self.assertRaises(ProviderError) as raised:
                        self._request(protocol, call, fresh, length_marker)
                    self.assertEqual(raised.exception.code, "incomplete_turn")
                    expected_reason = {"chat": "length", "responses": "max_output_tokens", "messages": "max_tokens"}[protocol]
                    self.assertEqual(raised.exception.finish_reason, expected_reason)
                    self.assertEqual(self._count(length_marker), 1)

    def test_http_and_in_stream_errors_are_sanitized_and_not_retried(self):
        for protocol, adapter, call in self.adapters():
            http_marker = f"T00:CASE:HTTP_ERROR:{protocol}"
            with self.subTest(protocol=protocol, case="http"), adapter:
                with self.assertRaises(ProviderError) as raised:
                    self._request(protocol, call, adapter, http_marker)
                self.assertEqual(raised.exception.code, "provider_http_error")
                self.assertEqual(raised.exception.http_status, 503)
                self.assertNotIn(SYNTHETIC_A, str(raised.exception))
                self.assertNotIn(SYNTHETIC_A, str(raised.exception.public_projection()))
                self.assertEqual(self._count(http_marker), 1)
            stream_marker = f"T00:CASE:STREAM_ERROR:{protocol}"
            with self.subTest(protocol=protocol, case="stream"):
                with self._adapter_for(protocol) as fresh:
                    with self.assertRaises(ProviderError) as raised:
                        self._request(protocol, call, fresh, stream_marker)
                    self.assertEqual(raised.exception.code, "provider_stream_error")
                    self.assertNotIn(SYNTHETIC_A, str(raised.exception))
                    self.assertEqual(self._count(stream_marker), 1)

    def _adapter_for(self, protocol: str, key: str = SYNTHETIC_A):
        if protocol == "chat":
            return ChatCompletionsAdapter(key, self.base_url + "/v1")
        if protocol == "responses":
            return ResponsesAdapter(key, self.base_url + "/v1")
        return MessagesAdapter(key, self.base_url)

    def _conversation(self, protocol: str):
        marker = "T00:TOOL:ROUNDTRIP"
        if protocol == "chat":
            return [{"role": "user", "content": marker}]
        if protocol == "responses":
            return [{"role": "user", "content": [{"type": "input_text", "text": marker}]}]
        return [{"role": "user", "content": marker}]

    def _tool_turn(self, protocol: str, adapter, call, conversation):
        if protocol in {"chat", "messages"}:
            return adapter.turn(model=MODEL_A, messages=conversation, allow_tools=True)
        return adapter.turn(model=MODEL_A, input=conversation, allow_tools=True)

    def _append_tool_continuation(self, protocol: str, conversation, turn):
        call = turn.tool_calls[0]
        if protocol == "chat":
            conversation.append(turn.continuation.payload["assistant_message"])
            conversation.append({"role": "tool", "tool_call_id": call.call_id, "content": "synthetic lookup result"})
        elif protocol == "responses":
            conversation.extend(turn.continuation.payload["output_items"])
            conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": "synthetic lookup result"})
        else:
            message = turn.continuation.payload["message"]
            conversation.append({"role": "assistant", "content": message["content"]})
            conversation.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.call_id, "content": "synthetic lookup result"}]})

    def test_two_tool_roundtrips_preserve_native_private_state(self):
        dispatched = 0
        for protocol in ("chat", "responses", "messages"):
            with self.subTest(protocol=protocol), self._adapter_for(protocol) as adapter:
                conversation = self._conversation(protocol)
                for round_index in range(2):
                    turn = self._tool_turn(protocol, adapter, None, conversation)
                    self.assertEqual(len(turn.tool_calls), 1)
                    self.assertEqual(turn.tool_calls[0].name, "lookup")
                    self.assertEqual(turn.tool_calls[0].arguments["query"], f"synthetic-{'one' if round_index == 0 else 'two'}")
                    dispatched += 1
                    self._append_tool_continuation(protocol, conversation, turn)
                final = self._tool_turn(protocol, adapter, None, conversation)
                self.assertEqual(final.text, "two-rounds-complete")
                self.assertEqual(final.tool_calls, ())
                self.assertEqual(dispatched, 2 * (list(("chat", "responses", "messages")).index(protocol) + 1))

                continuation_record = str(turn.continuation.private_record())
                public = str(turn.public_message())
                self.assertNotIn(continuation_record, public)
                self.assertNotIn("private reasoning", public)
                if protocol == "chat":
                    self.assertEqual(turn.continuation.payload["assistant_message"].get("reasoning_content"), "private reasoning")
                elif protocol == "responses":
                    items = turn.continuation.payload["output_items"]
                    self.assertEqual(items[0]["type"], "reasoning")
                    self.assertEqual(items[0]["encrypted_content"], "opaque-synthetic-2")
                    self.assertEqual(items[1]["type"], "function_call")
                else:
                    thinking = next(block for block in turn.continuation.payload["message"]["content"] if block["type"] == "thinking")
                    self.assertEqual(thinking["signature"], "synthetic-signature")
                self.assertEqual(self._count("T00:TOOL:ROUNDTRIP"), 3 * (list(("chat", "responses", "messages")).index(protocol) + 1))

    def test_incomplete_and_non_allowlisted_tools_never_return_a_dispatchable_turn(self):
        for protocol in ("chat", "responses", "messages"):
            for variant, expected in (("INVALID", "tool_arguments_invalid"), ("NOT_ALLOWLISTED", "tool_not_allowlisted")):
                marker = f"T00:TOOL:{variant}:{protocol}"
                with self.subTest(protocol=protocol, variant=variant), self._adapter_for(protocol) as adapter:
                    with self.assertRaises(ProviderError) as raised:
                        if protocol == "chat":
                            adapter.turn(model=MODEL_A, messages=[{"role": "user", "content": marker}], allow_tools=True)
                        elif protocol == "responses":
                            adapter.turn(model=MODEL_A, input=marker, allow_tools=True)
                        else:
                            adapter.turn(model=MODEL_A, messages=[{"role": "user", "content": marker}], allow_tools=True)
                    self.assertEqual(raised.exception.code, expected)
                    self.assertEqual(self._count(marker), 1)

    def test_explicit_key_and_model_are_isolated_between_clients(self):
        barrier = threading.Barrier(2)

        def request(key: str, model: str, marker: str):
            with ChatCompletionsAdapter(key, self.base_url + "/v1") as adapter:
                barrier.wait(timeout=2)
                return adapter.turn(model=model, messages=[{"role": "user", "content": marker}]).text

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(request, SYNTHETIC_A, MODEL_A, "T00:ISOLATION:A")
            two = pool.submit(request, SYNTHETIC_B, MODEL_B, "T00:ISOLATION:B")
            self.assertEqual(one.result(timeout=5), "sdk-local-ok")
            self.assertEqual(two.result(timeout=5), "sdk-local-ok")

        records, counts = self.upstream.state.snapshot()
        paired = {(row["marker"], row["credential_label"], row["model"]) for row in records}
        self.assertEqual(paired, {
            ("T00:ISOLATION:A", "tenant-a", MODEL_A),
            ("T00:ISOLATION:B", "tenant-b", MODEL_B),
        })
        self.assertEqual(counts["T00:ISOLATION:A"], 1)
        self.assertEqual(counts["T00:ISOLATION:B"], 1)

    def test_cancellation_closes_sdk_and_stream_resources(self):
        for protocol, _unused, call in self.adapters():
            with self.subTest(protocol=protocol):
                adapter = self._adapter_for(protocol)
                cancel = threading.Event()
                results: list[str] = []

                def on_event(event: ModelEvent) -> None:
                    if event.kind == "text_delta":
                        cancel.set()

                def run():
                    try:
                        self._request(protocol, call, adapter, f"T00:CASE:CANCEL:{protocol}", cancel_event=cancel, on_event=on_event)
                        results.append("completed")
                    except ProviderError as exc:
                        results.append(exc.code)

                worker = threading.Thread(target=run)
                worker.start()
                worker.join(timeout=4)
                self.assertFalse(worker.is_alive(), "cancelled stream did not finish promptly")
                self.assertEqual(results, ["request_cancelled"])
                self.assertTrue(self.upstream.state.cancel_observed.wait(timeout=2))
                adapter.close()
                self.assertTrue(adapter.client._client.is_closed)
                self.assertEqual(self._count(f"T00:CASE:CANCEL:{protocol}"), 1)

    def test_sdk_retry_policy_is_zero_and_event_projection_hides_raw_data(self):
        for protocol, adapter, _call in self.adapters():
            with self.subTest(protocol=protocol):
                self.assertEqual(adapter.client.max_retries, 0)
                adapter.close()
        event = ModelEvent("tool_delta", "openai_responses", _raw={"api_key": SYNTHETIC_A, "continuation": "private"})
        public = str(event.public_projection())
        self.assertNotIn(SYNTHETIC_A, public)
        self.assertNotIn("continuation", public)


if __name__ == "__main__":
    unittest.main(verbosity=2)
