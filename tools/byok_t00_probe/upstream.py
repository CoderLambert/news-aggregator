"""Controlled synthetic HTTP upstream for the T00 LiteLLM probe.

Only synthetic marker IDs, tenant labels, booleans, event names, and counters are
retained. Credentials and request text are never written to records or stdout.
"""
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY_LABELS = {
    "sk-t00-provider-a-synthetic": "tenant-a",
    "sk-t00-provider-b-synthetic": "tenant-b",
    "sk-t00-deployment-default-synthetic": "deployment-default",
    "sk-t00-master-synthetic": "master",
    "sk-t00-admin-synthetic": "admin",
}
PROJECT_KEY_HASHES = set()
RECORDS = []
LOCK = threading.Lock()
TEST_ID_PATTERN = re.compile(r"T00_[A-Z0-9_]{3,80}")


def project_key_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_marker(payload):
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    match = TEST_ID_PATTERN.search(serialized)
    return match.group(0) if match else "T00_UNKNOWN"


def expected_tenant(test_id):
    if test_id.endswith("_A"):
        return "tenant-a"
    if test_id.endswith("_B"):
        return "tenant-b"
    return None


def terminal_for(path, request, eof):
    if eof:
        return "normal_eof_without_protocol_terminal"
    if path.endswith("/chat/completions"):
        return "finish_reason_stop"
    if path.endswith("/responses"):
        return "response_completed"
    if path.endswith("/messages"):
        return "message_stop"
    return "not_applicable"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
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

        if self.path == "/test/expectations":
            hashes = request.get("project_key_sha256", [])
            if not isinstance(hashes, list) or any(
                not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
                for item in hashes
            ):
                self._json(400, {"error": {"type": "invalid_request_error"}})
                return
            with LOCK:
                PROJECT_KEY_HASHES.clear()
                PROJECT_KEY_HASHES.update(hashes)
            self._json(200, {"registered": len(hashes)})
            return

        route = self.path.rsplit("/", 1)[-1]
        is_messages = self.path.endswith("/messages")
        test_id = extract_marker(request)
        expected = expected_tenant(test_id)
        scenario = "eof-no-terminal" if "_EOF_" in test_id else "normal"
        authorization = self.headers.get("authorization", "")
        bearer = authorization[7:] if authorization.lower().startswith("bearer ") else None
        x_api_key = self.headers.get("x-api-key")
        provider_credential = x_api_key if is_messages else bearer
        candidates = [
            value
            for value in (
                provider_credential,
                bearer,
                x_api_key,
                request.get("api_key") if isinstance(request.get("api_key"), str) else None,
            )
            if value
        ]
        with LOCK:
            project_match = any(project_key_hash(value) in PROJECT_KEY_HASHES for value in candidates)
        credential_label = KEY_LABELS.get(provider_credential or "", "missing" if not provider_credential else "unknown")
        if project_match:
            credential_label = "project"
        upstream_terminal = terminal_for(self.path, request, scenario == "eof-no-terminal")
        record = {
            "event": "upstream_request",
            "test_id": test_id,
            "protocol": route,
            "scenario": scenario,
            "model": request.get("model"),
            "tenant": credential_label,
            "expected_tenant": expected or "none",
            "provider_key_match": credential_label == expected if expected else False,
            "provider_credential_present": bool(provider_credential),
            "provider_auth_scheme": (
                "x-api-key" if is_messages and x_api_key
                else "bearer" if not is_messages and bearer
                else "missing"
            ),
            "authorization_present": bool(authorization),
            "x_api_key_present": bool(x_api_key),
            "wrong_provider_header_present": bool(bearer) if is_messages else bool(x_api_key),
            "project_key_match": project_match,
            "master_key_match": any(value == "sk-t00-master-synthetic" for value in candidates),
            "admin_key_match": any(value == "sk-t00-admin-synthetic" for value in candidates),
            "deployment_default_match": any(
                value == "sk-t00-deployment-default-synthetic" for value in candidates
            ),
            "upstream_terminal": upstream_terminal,
        }
        with LOCK:
            RECORDS.append(record)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True), flush=True)

        if not provider_credential or credential_label not in {"tenant-a", "tenant-b"}:
            self._json(401, {"error": {"type": "authentication_error"}})
            return

        model = request.get("model", "test-model")
        eof = scenario == "eof-no-terminal"
        if self.path.endswith("/chat/completions"):
            if request.get("stream"):
                self._chat_stream(model, eof)
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
                self._responses_stream(model, eof)
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
                self._messages_stream(model, eof)
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
