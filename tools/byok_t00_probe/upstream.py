"""Loopback HTTP upstream used by the real-SDK T00 probe and tests."""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


SYNTHETIC_KEYS = {
    "synthetic-provider-key-a": "tenant-a",
    "synthetic-provider-key-b": "tenant-b",
}


def _all_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _all_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_strings(child)


def _tool_result_count(protocol: str, body: dict[str, Any]) -> int:
    if protocol == "chat":
        return sum(1 for row in body.get("messages", []) if row.get("role") == "tool")
    if protocol == "responses":
        return sum(1 for row in body.get("input", []) if isinstance(row, dict) and row.get("type") == "function_call_output")
    return sum(
        1
        for message in body.get("messages", [])
        if message.get("role") == "user"
        for block in (message.get("content") if isinstance(message.get("content"), list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    )


class ProbeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.records: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()
        self.cancel_observed = threading.Event()

    def add(self, protocol: str, path: str, headers: Any, body: dict[str, Any]) -> None:
        authorization = headers.get("Authorization", "")
        key = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else headers.get("x-api-key", "")
        key_label = SYNTHETIC_KEYS.get(key, "unknown")
        text = "\n".join(_all_strings(body))
        marker = next((part.strip() for part in text.splitlines() if part.strip().startswith("T00:")), "")
        record = {
            "protocol": protocol,
            "path": path,
            "credential_label": key_label,
            "model": str(body.get("model", "")),
            "marker": marker,
            "tool_result_count": _tool_result_count(protocol, body),
        }
        with self.lock:
            self.records.append(record)
            self.counts[marker or protocol] += 1

    def snapshot(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        with self.lock:
            return [dict(row) for row in self.records], dict(self.counts)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, state: ProbeState):
        self.probe_state = state
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "T00Loopback/1"
    sys_version = ""

    def log_message(self, *_args: Any) -> None:
        # The probe never logs request headers, bodies, or exception text.
        return

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body_bytes = self.rfile.read(length)
            body = json.loads(body_bytes or b"{}")
        except Exception:
            self._json(400, {"error": {"type": "invalid_request_error", "message": "synthetic invalid JSON"}})
            return

        if self.path.endswith("/chat/completions"):
            protocol = "chat"
        elif self.path.endswith("/responses"):
            protocol = "responses"
        elif self.path.endswith("/messages"):
            protocol = "messages"
        else:
            self._json(404, {"error": {"type": "not_found", "message": "synthetic route not found"}})
            return

        self.server.probe_state.add(protocol, self.path, self.headers, body)
        marker_text = "\n".join(_all_strings(body))
        if "T00:CASE:HTTP_ERROR" in marker_text:
            self._json(503, {
                "error": {
                    "type": "api_error",
                    "code": "synthetic_upstream_error",
                    "message": "synthetic provider body contains synthetic-provider-key-a; do not expose",
                },
            })
            return
        if "T00:CASE:STREAM_ERROR" in marker_text:
            if protocol == "chat":
                self._data_sse([{"error": {
                    "type": "api_error",
                    "code": "synthetic_stream_error",
                    "message": "synthetic-provider-key-a must not escape",
                }}])
            elif protocol == "responses":
                self._event_sse([("error", {"type": "error", "error": {
                    "type": "server_error",
                    "code": "synthetic_stream_error",
                    "message": "synthetic-provider-key-a must not escape",
                }})])
            else:
                self._event_sse([("error", {"type": "error", "error": {
                    "type": "api_error",
                    "message": "synthetic-provider-key-a must not escape",
                }})])
            return
        if "T00:CASE:EOF" in marker_text:
            self._eof(protocol, body)
            return
        if "T00:CASE:LENGTH" in marker_text:
            self._incomplete(protocol, body)
            return
        if "T00:CASE:CANCEL" in marker_text:
            self._cancel_stream(protocol)
            return
        if "T00:TOOL:INVALID" in marker_text:
            self._tool_response(protocol, "invalid")
            return
        if "T00:TOOL:NOT_ALLOWLISTED" in marker_text:
            self._tool_response(protocol, "not_allowlisted")
            return
        if "T00:TOOL:ROUNDTRIP" in marker_text:
            self._tool_response(protocol, "roundtrip", _tool_result_count(protocol, body))
            return
        self._complete(protocol, body)

    def _headers(self, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def _data_sse(self, values: list[dict[str, Any] | str]) -> None:
        self._headers("text/event-stream")
        try:
            for value in values:
                data = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.server.probe_state.cancel_observed.set()

    def _event_sse(self, values: list[tuple[str, dict[str, Any]]]) -> None:
        self._headers("text/event-stream")
        try:
            for event, value in values:
                data = json.dumps(value, separators=(",", ":"))
                self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.server.probe_state.cancel_observed.set()

    def _chat_chunk(self, *, delta: dict[str, Any] | None = None, finish: str | None = None, usage: dict[str, int] | None = None) -> dict[str, Any]:
        choices = [] if usage is not None else [{
            "index": 0,
            "delta": delta or {},
            "finish_reason": finish,
        }]
        return {
            "id": "chatcmpl_t00_synthetic",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "synthetic-model",
            "choices": choices,
            **({"usage": usage} if usage is not None else {}),
        }

    def _complete(self, protocol: str, body: dict[str, Any]) -> None:
        if protocol == "chat":
            self._data_sse([
                self._chat_chunk(delta={"role": "assistant", "content": "sdk-local-ok"}),
                self._chat_chunk(delta={}, finish="stop"),
                self._chat_chunk(usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}),
                "[DONE]",
            ])
            return
        if protocol == "responses":
            response = self._response(
                body,
                status="completed",
                output=[{
                    "id": "msg_t00_complete",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "sdk-local-ok", "annotations": []}],
                }],
                output_text="sdk-local-ok",
            )
            self._event_sse([
                ("response.created", {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}}),
                ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "sdk-local-ok", "output_index": 0, "content_index": 0, "item_id": "msg_t00_complete"}),
                ("response.completed", {"type": "response.completed", "response": response}),
            ])
            return
        self._messages_complete()

    def _eof(self, protocol: str, body: dict[str, Any]) -> None:
        if protocol == "chat":
            self._data_sse([self._chat_chunk(delta={"role": "assistant", "content": "partial"})])
        elif protocol == "responses":
            self._event_sse([("response.output_text.delta", {
                "type": "response.output_text.delta",
                "delta": "partial",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_t00_partial",
            })])
        else:
            self._messages_stream(stop_reason=None, text="partial", omit_stop=True)

    def _incomplete(self, protocol: str, body: dict[str, Any]) -> None:
        if protocol == "chat":
            self._data_sse([
                self._chat_chunk(delta={"role": "assistant", "content": "partial"}),
                self._chat_chunk(delta={}, finish="length"),
                self._chat_chunk(usage={"prompt_tokens": 3, "completion_tokens": 64, "total_tokens": 67}),
                "[DONE]",
            ])
        elif protocol == "responses":
            response = self._response(body, status="incomplete", output=[], output_text="", incomplete_reason="max_output_tokens")
            self._event_sse([("response.incomplete", {"type": "response.incomplete", "response": response})])
        else:
            self._messages_stream(stop_reason="max_tokens", text="partial")

    def _cancel_stream(self, protocol: str) -> None:
        if protocol == "chat":
            self._headers("text/event-stream")
            first = self._chat_chunk(delta={"role": "assistant", "content": "first"})
            repeat = self._chat_chunk(delta={"content": "more"})
            frame = lambda value: f"data: {json.dumps(value, separators=(',', ':'))}\n\n".encode()
        elif protocol == "responses":
            self._headers("text/event-stream")
            first = ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "first", "output_index": 0, "content_index": 0, "item_id": "msg_cancel"})
            repeat = first
            frame = lambda value: f"event: {value[0]}\ndata: {json.dumps(value[1], separators=(',', ':'))}\n\n".encode()
        else:
            self._headers("text/event-stream")
            first = [
                ("message_start", {"type": "message_start", "message": self._message_start()}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "first"}}),
            ]
            repeat = [("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "more"}})]
            frame = lambda value: f"event: {value[0]}\ndata: {json.dumps(value[1], separators=(',', ':'))}\n\n".encode()
        try:
            for value in first if isinstance(first, list) else [first]:
                self.wfile.write(frame(value))
                self.wfile.flush()
            for _ in range(80):
                time.sleep(0.025)
                for value in repeat if isinstance(repeat, list) else [repeat]:
                    self.wfile.write(frame(value))
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.server.probe_state.cancel_observed.set()

    def _tool_response(self, protocol: str, kind: str, round_number: int = 0) -> None:
        if kind == "not_allowlisted":
            name, arguments = "not_allowed", '{"query":"synthetic"}'
        elif kind == "invalid":
            name, arguments = "lookup", '{"query":'
        else:
            name = "lookup"
            arguments = json.dumps({"query": "synthetic-one" if round_number == 0 else "synthetic-two"}, separators=(",", ":"))
        if protocol == "chat":
            if kind == "roundtrip" and round_number >= 2:
                self._data_sse([
                    self._chat_chunk(delta={"role": "assistant", "content": "two-rounds-complete"}),
                    self._chat_chunk(delta={}, finish="stop"),
                    self._chat_chunk(usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}),
                    "[DONE]",
                ])
                return
            chunks = [
                self._chat_chunk(delta={"role": "assistant", "reasoning_content": "private reasoning"}),
                self._chat_chunk(delta={"tool_calls": [{"index": 0, "id": f"call_chat_{round_number + 1}", "type": "function", "function": {"name": name, "arguments": arguments[:10]}}]}),
                self._chat_chunk(delta={"tool_calls": [{"index": 0, "function": {"arguments": arguments[10:]}}]}),
                self._chat_chunk(delta={}, finish="tool_calls"),
                "[DONE]",
            ]
            self._data_sse(chunks)
            return
        if protocol == "responses":
            if kind == "roundtrip" and round_number >= 2:
                output = [
                    {"id": "rs_t00_final", "type": "reasoning", "summary": [{"type": "summary_text", "text": "private reasoning"}], "encrypted_content": "opaque-synthetic-continuation"},
                    {"id": "msg_t00_final", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "two-rounds-complete", "annotations": []}]},
                ]
                response = self._response(body={}, status="completed", output=output, output_text="two-rounds-complete")
                self._event_sse([("response.completed", {"type": "response.completed", "response": response})])
                return
            call_id = f"call_responses_{round_number + 1}"
            output = [
                {"id": f"rs_t00_{round_number + 1}", "type": "reasoning", "summary": [{"type": "summary_text", "text": "private reasoning"}], "encrypted_content": f"opaque-synthetic-{round_number + 1}"},
                {"id": f"fc_t00_{round_number + 1}", "type": "function_call", "call_id": call_id, "name": name, "arguments": arguments, "status": "completed"},
            ]
            response = self._response(body={}, status="completed", output=output, output_text="")
            self._event_sse([("response.completed", {"type": "response.completed", "response": response})])
            return
        if kind == "roundtrip" and round_number >= 2:
            self._messages_complete(text="two-rounds-complete", thinking=True)
            return
        input_value: dict[str, Any] = {}
        if kind == "roundtrip":
            tool_name = name
        else:
            tool_name = name
        events: list[tuple[str, dict[str, Any]]] = [
            ("message_start", {"type": "message_start", "message": self._message_start()}),
        ]
        index = 0
        if kind == "roundtrip":
            events.extend([
                ("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": "private reasoning"}}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": "synthetic-signature"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ])
            index += 1
        events.extend([
            ("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": f"tool_messages_{round_number + 1}", "name": tool_name, "input": input_value}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": arguments}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
            ("message_stop", {"type": "message_stop"}),
        ])
        self._event_sse(events)

    def _response(
        self,
        body: dict[str, Any],
        *,
        status: str,
        output: list[dict[str, Any]],
        output_text: str,
        incomplete_reason: str | None = None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "id": "resp_t00_synthetic",
            "object": "response",
            "created_at": 1,
            "status": status,
            "model": body.get("model") or "synthetic-model",
            "output": output,
            "output_text": output_text,
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
        }
        if incomplete_reason:
            response["incomplete_details"] = {"reason": incomplete_reason}
        return response

    def _message_start(self) -> dict[str, Any]:
        return {
            "id": "msg_t00_synthetic",
            "type": "message",
            "role": "assistant",
            "model": "synthetic-model",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 0},
        }

    def _messages_complete(self, text: str = "sdk-local-ok", thinking: bool = False) -> None:
        events: list[tuple[str, dict[str, Any]]] = [
            ("message_start", {"type": "message_start", "message": self._message_start()}),
        ]
        index = 0
        if thinking:
            events.extend([
                ("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": "private reasoning"}}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": "synthetic-signature"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ])
            index += 1
        events.extend([
            ("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
            ("message_stop", {"type": "message_stop"}),
        ])
        self._event_sse(events)

    def _messages_stream(self, *, stop_reason: str | None, text: str, omit_stop: bool = False) -> None:
        events: list[tuple[str, dict[str, Any]]] = [
            ("message_start", {"type": "message_start", "message": self._message_start()}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ]
        if not omit_stop:
            events.extend([
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"}),
            ])
        self._event_sse(events)


class LoopbackUpstream:
    """Context-managed local HTTP server; it never connects to provider hosts."""

    def __init__(self) -> None:
        self.state = ProbeState()
        self.server = _Server(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "LoopbackUpstream":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
