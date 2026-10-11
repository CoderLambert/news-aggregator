"""Controlled synthetic HTTP upstream for the T00 LiteLLM probe."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY_LABELS = {
    "sk-t00-provider-a-synthetic": "tenant-a",
    "sk-t00-provider-b-synthetic": "tenant-b",
}
RECORDS = []
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        # Request bodies and headers are deliberately never sent to stdout.
        return

    def _json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"ok": True})
            return
        if self.path == "/stats":
            with LOCK:
                records = list(RECORDS)
            self._json(200, {"records": records})
            return
        self._json(404, {"error": {"type": "not_found"}})

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size)
        try:
            request = json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": {"type": "invalid_request_error"}})
            return

        provider_key = self.headers.get("x-api-key")
        tenant = KEY_LABELS.get(provider_key)
        prompt_json = json.dumps(request, ensure_ascii=False)
        scenario = "eof-no-terminal" if "T00_EOF_NO_TERMINAL" in prompt_json else "normal"
        path = self.path.rsplit("/", 1)[-1]
        record = {
            "event": "upstream_request",
            "protocol": path,
            "scenario": scenario,
            "source": self.headers.get("x-probe-source", "unknown"),
            "model": request.get("model"),
            "tenant": tenant or "rejected",
            "provider_header_present": bool(provider_key),
            "authorization_present": bool(self.headers.get("authorization")),
            "upstream_terminal": (
                "normal_eof_without_protocol_terminal"
                if scenario == "eof-no-terminal"
                else "complete"
            ),
        }
        with LOCK:
            RECORDS.append(record)
        # This line contains only safe labels and booleans, never header values or prompt text.
        print(json.dumps(record, separators=(",", ":")), flush=True)

        if tenant is None:
            self._json(401, {"error": {"type": "authentication_error"}})
            return

        model = request.get("model", "test-model")
        if self.path.endswith("/chat/completions"):
            if request.get("stream"):
                self._chat_stream(model, scenario == "eof-no-terminal")
            else:
                self._json(200, {
                    "id": "chatcmpl_t00_synthetic",
                    "object": "chat.completion",
                    "created": 1,
                    "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "synthetic t00 chat pass"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
                })
            return
        if self.path.endswith("/responses"):
            if request.get("stream"):
                self._responses_stream(model, scenario == "eof-no-terminal")
            else:
                self._json(200, {
                    "id": "resp_t00_synthetic",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": model,
                    "output": [{"id": "msg_t00", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "synthetic t00 responses pass", "annotations": []}]}],
                    "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
                })
            return
        if self.path.endswith("/messages"):
            if request.get("stream"):
                self._messages_stream(model, scenario == "eof-no-terminal")
            else:
                self._json(200, {
                    "id": "msg_t00_synthetic",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": "synthetic t00 messages pass"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 4, "output_tokens": 5},
                })
            return
        self._json(404, {"error": {"type": "not_found"}})

    def _send_sse(self, events, eof=False):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event_name, payload in events:
            data = ("event: " + event_name + "\ndata: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode()
            self.wfile.write(data)
            self.wfile.flush()
        if not eof:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        self.close_connection = True

    def _chat_stream(self, model, eof=False):
        def chunk(delta, finish=None):
            return {"id": "chatcmpl_t00_synthetic", "object": "chat.completion.chunk", "created": 1, "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        events = [("message", chunk({"role": "assistant"})), ("message", chunk({"content": "synthetic t00 stream"}))]
        if not eof:
            events.append(("message", chunk({}, "stop")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for _name, payload in events:
            self.wfile.write(("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode())
            self.wfile.flush()
        if not eof:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        self.close_connection = True

    def _responses_stream(self, model, eof=False):
        created = {"id": "resp_t00_stream", "object": "response", "created_at": 1, "status": "in_progress", "model": model, "output": []}
        events = [("response.created", {"type": "response.created", "response": created}), ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "msg_t00", "output_index": 0, "content_index": 0, "delta": "synthetic t00 stream"})]
        if not eof:
            completed = {"id": "resp_t00_stream", "object": "response", "created_at": 1, "status": "completed", "model": model, "output": [{"id": "msg_t00", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "synthetic t00 stream", "annotations": []}]}]}
            events.append(("response.completed", {"type": "response.completed", "response": completed}))
        self._send_sse(events, eof=eof)

    def _messages_stream(self, model, eof=False):
        start = {"type": "message_start", "message": {"id": "msg_t00", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 4, "output_tokens": 0}}}
        events = [("message_start", start), ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}), ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "synthetic t00 stream"}})]
        if not eof:
            events.extend([("content_block_stop", {"type": "content_block_stop", "index": 0}), ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 5}}), ("message_stop", {"type": "message_stop"})])
        self._send_sse(events, eof=eof)


print("synthetic_upstream_ready", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
