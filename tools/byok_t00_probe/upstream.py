"""Controlled synthetic HTTP upstream for the T00 LiteLLM probe.

Only synthetic marker IDs, tenant labels, booleans, event names, and counters are
retained. Credentials and request text are never written to records or stdout.
"""
import hashlib
import json
import re
import threading
import time
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

# Opaque fixture fields are synthetic continuity markers, not model reasoning.
CHAT_TOOL_MESSAGES = [
    {
        "role": "assistant",
        "reasoning_content": "opaque-chat-state-r1",
        "tool_calls": [{
            "id": "chat_call_r1",
            "type": "function",
            "function": {"name": "lookup_weather", "arguments": '{"city":"synthetic-city"}'},
        }],
    },
    {
        "role": "assistant",
        "reasoning_content": "opaque-chat-state-r2",
        "tool_calls": [{
            "id": "chat_call_r2",
            "type": "function",
            "function": {"name": "format_weather", "arguments": '{"summary":"synthetic-weather"}'},
        }],
    },
]
RESPONSES_TOOL_ITEMS = [
    [
        {
            "id": "resp_reasoning_r1",
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "opaque-responses-state-r1"}],
            "encrypted_content": "opaque-responses-continuation-r1",
        },
        {
            "id": "resp_item_call_r1",
            "type": "function_call",
            "call_id": "resp_call_r1",
            "name": "lookup_weather",
            "arguments": '{"city":"synthetic-city"}',
            "status": "completed",
        },
    ],
    [
        {
            "id": "resp_reasoning_r2",
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "opaque-responses-state-r2"}],
            "encrypted_content": "opaque-responses-continuation-r2",
        },
        {
            "id": "resp_item_call_r2",
            "type": "function_call",
            "call_id": "resp_call_r2",
            "name": "format_weather",
            "arguments": '{"summary":"synthetic-weather"}',
            "status": "completed",
        },
    ],
]
MESSAGES_TOOL_CONTENT = [
    [
        {"type": "thinking", "thinking": "opaque-messages-state-r1", "signature": "opaque-signature-r1"},
        {"type": "tool_use", "id": "msg_call_r1", "name": "lookup_weather", "input": {"city": "synthetic-city"}},
    ],
    [
        {"type": "thinking", "thinking": "opaque-messages-state-r2", "signature": "opaque-signature-r2"},
        {"type": "tool_use", "id": "msg_call_r2", "name": "format_weather", "input": {"summary": "synthetic-weather"}},
    ],
]


def history_facts(path, request):
    """Inspect only synthetic continuation markers; never retain input text."""
    facts = {}
    if path.endswith("/chat/completions"):
        messages = request.get("messages", [])
        assistants = [item for item in messages if item.get("role") == "assistant"]
        tools = [item for item in messages if item.get("role") == "tool"]
        for round_index, expected in enumerate(CHAT_TOOL_MESSAGES, start=1):
            assistant = next((item for item in assistants if item.get("reasoning_content") == expected["reasoning_content"]), None)
            facts[f"chat_r{round_index}_assistant_preserved"] = bool(
                assistant and assistant.get("tool_calls") == expected["tool_calls"]
            )
            call_id = expected["tool_calls"][0]["id"]
            expected_output = "synthetic-weather" if round_index == 1 else "synthetic-summary"
            facts[f"chat_r{round_index}_tool_result_id_preserved"] = any(
                item.get("tool_call_id") == call_id and item.get("content") == expected_output
                for item in tools
            )
        facts["chat_assistant_turn_count"] = len(assistants)
        facts["chat_tool_result_count"] = len(tools)
    elif path.endswith("/responses"):
        items = request.get("input", [])
        if isinstance(items, str):
            items = []
        for round_index, expected_items in enumerate(RESPONSES_TOOL_ITEMS, start=1):
            reasoning_expected, call_expected = expected_items
            function_calls = [
                item for item in items
                if isinstance(item, dict) and item.get("type") == "function_call"
            ]
            reasoning_actual = next((
                item for item in items
                if isinstance(item, dict) and item.get("type") == "reasoning"
                and item.get("id") == reasoning_expected["id"]
            ), {})
            call_actual = next((
                item for item in items
                if isinstance(item, dict) and item.get("type") == "function_call"
                and item.get("id") == call_expected["id"]
            ), function_calls[round_index - 1] if len(function_calls) >= round_index else {})
            reasoning_matches = all(reasoning_actual.get(key) == value for key, value in reasoning_expected.items())
            call_matches = all(call_actual.get(key) == value for key, value in call_expected.items())
            facts[f"responses_r{round_index}_output_items_preserved"] = (
                bool(reasoning_actual) and bool(call_actual)
                and reasoning_matches and call_matches
                and set(reasoning_actual) == set(reasoning_expected)
                and set(call_actual) == set(call_expected)
            )
            facts[f"responses_r{round_index}_reasoning_id_preserved"] = reasoning_actual.get("id") == reasoning_expected["id"]
            facts[f"responses_r{round_index}_reasoning_summary_preserved"] = reasoning_actual.get("summary") == reasoning_expected["summary"]
            facts[f"responses_r{round_index}_encrypted_continuation_preserved"] = reasoning_actual.get("encrypted_content") == reasoning_expected["encrypted_content"]
            facts[f"responses_r{round_index}_reasoning_keyset_preserved"] = set(reasoning_actual) == set(reasoning_expected)
            facts[f"responses_r{round_index}_function_call_type_preserved"] = call_actual.get("type") == call_expected["type"]
            facts[f"responses_r{round_index}_function_call_item_present"] = bool(call_actual)
            facts[f"responses_r{round_index}_function_call_id_preserved"] = call_actual.get("id") == call_expected["id"]
            facts[f"responses_r{round_index}_function_call_id_field_present"] = "id" in call_actual
            facts[f"responses_r{round_index}_function_call_call_id_preserved"] = call_actual.get("call_id") == call_expected["call_id"]
            facts[f"responses_r{round_index}_function_call_name_preserved"] = call_actual.get("name") == call_expected["name"]
            facts[f"responses_r{round_index}_function_call_arguments_preserved"] = call_actual.get("arguments") == call_expected["arguments"]
            facts[f"responses_r{round_index}_function_call_status_preserved"] = call_actual.get("status") == call_expected["status"]
            facts[f"responses_r{round_index}_function_call_fields_preserved"] = all(
                facts[f"responses_r{round_index}_function_call_{field}_preserved"]
                for field in ("type", "id", "call_id", "name", "arguments", "status")
            )
            facts[f"responses_r{round_index}_function_call_keyset_preserved"] = set(call_actual) == set(call_expected)
            facts[f"responses_r{round_index}_function_call_missing_expected_field_count"] = len(set(call_expected) - set(call_actual))
            facts[f"responses_r{round_index}_function_call_extra_field_count"] = len(set(call_actual) - set(call_expected))
            facts[f"responses_r{round_index}_output_item_count_matches"] = sum(
                isinstance(item, dict) and item.get("type") in {"reasoning", "function_call"}
                for item in items
            ) >= len(expected_items)
            call_id = "resp_call_r1" if round_index == 1 else "resp_call_r2"
            expected_output = "synthetic-weather" if round_index == 1 else "synthetic-summary"
            facts[f"responses_r{round_index}_tool_result_preserved"] = any(
                isinstance(item, dict)
                and item.get("type") == "function_call_output"
                and item.get("call_id") == call_id
                and item.get("output") == expected_output
                for item in items
            )
        facts["responses_input_item_count"] = len(items)
    elif path.endswith("/messages"):
        messages = request.get("messages", [])
        assistants = [item for item in messages if item.get("role") == "assistant"]
        users = [item for item in messages if item.get("role") == "user"]
        for round_index, expected_content in enumerate(MESSAGES_TOOL_CONTENT, start=1):
            assistant = next((item for item in assistants if any(
                isinstance(block, dict) and block.get("type") == "thinking"
                and block.get("thinking") == expected_content[0]["thinking"]
                for block in item.get("content", [])
            )), None)
            facts[f"messages_r{round_index}_thinking_signature_preserved"] = bool(
                assistant and expected_content[0] in assistant.get("content", [])
                and expected_content[1] in assistant.get("content", [])
            )
            call_id = expected_content[1]["id"]
            expected_output = "synthetic-weather" if round_index == 1 else "synthetic-summary"
            facts[f"messages_r{round_index}_tool_result_preserved"] = any(
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("tool_use_id") == call_id
                and block.get("content") == expected_output
                for message in users for block in message.get("content", [])
                if isinstance(message.get("content"), list)
            )
        facts["messages_assistant_turn_count"] = len(assistants)
    return facts


def project_key_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_marker(payload):
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    matches = list(TEST_ID_PATTERN.finditer(serialized))
    return matches[-1].group(0) if matches else "T00_UNKNOWN"


def expected_tenant(test_id):
    if test_id.endswith("_A"):
        return "tenant-a"
    if test_id.endswith("_B"):
        return "tenant-b"
    return None


def terminal_for(path, request, eof):
    if eof:
        return "normal_eof_without_protocol_terminal"
    if "_INCOMPLETE_" in extract_marker(request):
        return "response_incomplete" if path.endswith("/responses") else "message_stop_max_tokens" if path.endswith("/messages") else "finish_reason_length"
    if "_TOOL_R" in extract_marker(request):
        return "tool_call_turn"
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

    @staticmethod
    def _tool_case(test_id):
        round_number = 1 if "_TOOL_R1_" in test_id else 2 if "_TOOL_R2_" in test_id else 0
        if "_TOOL_MALFORMED_" in test_id:
            return 1, "lookup_weather", '{"city":'
        if "_TOOL_INVALID_" in test_id:
            return 1, "lookup_weather", "{not-json}"
        if "_TOOL_UNKNOWN_" in test_id:
            return 1, "delete_everything", '{"confirm":true}'
        expected = CHAT_TOOL_MESSAGES[round_number - 1] if round_number in (1, 2) else CHAT_TOOL_MESSAGES[0]
        call = expected["tool_calls"][0]
        return round_number or 1, call["function"]["name"], call["function"]["arguments"]

    def _chat_tool_response(self, model, test_id):
        round_number, tool_name, arguments = self._tool_case(test_id)
        reasoning = CHAT_TOOL_MESSAGES[round_number - 1]["reasoning_content"] if "_TOOL_R" in test_id else "opaque-chat-invalid-tool"
        call_id = CHAT_TOOL_MESSAGES[round_number - 1]["tool_calls"][0]["id"] if "_TOOL_R" in test_id else "chat_call_invalid"
        self._json(200, {
            "id": "chatcmpl_t00_tool_r" + str(round_number),
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": reasoning,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": arguments},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        })

    def _responses_tool_response(self, model, test_id):
        round_number, tool_name, arguments = self._tool_case(test_id)
        if "_TOOL_R" in test_id:
            output = RESPONSES_TOOL_ITEMS[round_number - 1]
        else:
            output = [
                {
                    "id": "resp_reasoning_invalid",
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "opaque-responses-invalid-tool"}],
                    "encrypted_content": "opaque-responses-invalid-continuation",
                },
                {
                    "id": "resp_item_call_invalid",
                    "type": "function_call",
                    "call_id": "resp_call_invalid",
                    "name": tool_name,
                    "arguments": arguments,
                    "status": "completed",
                },
            ]
        self._json(200, {
            "id": "resp_t00_tool_r" + str(round_number),
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": model,
            "output": output,
            "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
        })

    def _messages_tool_response(self, model, test_id):
        round_number, tool_name, arguments = self._tool_case(test_id)
        if "_TOOL_R" in test_id:
            content = MESSAGES_TOOL_CONTENT[round_number - 1]
        else:
            input_value = arguments if isinstance(arguments, dict) else {"invalid": arguments}
            if "_TOOL_MALFORMED_" in test_id or "_TOOL_INVALID_" in test_id:
                input_value = ["not", "an", "object"]
            content = [
                {"type": "thinking", "thinking": "opaque-messages-invalid-tool", "signature": "opaque-signature-invalid"},
                {"type": "tool_use", "id": "msg_call_invalid", "name": tool_name, "input": input_value},
            ]
        self._json(200, {
            "id": "msg_t00_tool_r" + str(round_number),
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 4, "output_tokens": 2},
        })

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
        scenario = (
            "eof-no-terminal" if "_EOF_" in test_id
            else "incomplete" if "_INCOMPLETE_" in test_id
            else "http-error" if "_HTTP_ERROR_" in test_id
            else "timeout" if "_TIMEOUT_" in test_id
            else "truncated-body" if "_TRUNCATED_" in test_id
            else "sse-error" if "_SSE_ERROR_" in test_id
            else "normal"
        )
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
            "continuation_facts": history_facts(self.path, request),
            "upstream_stream_events_written": 0,
            "upstream_stream_body_finished": False,
        }
        with LOCK:
            RECORDS.append(record)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True), flush=True)

        if not provider_credential or credential_label not in {"tenant-a", "tenant-b"}:
            self._json(401, {"error": {"type": "authentication_error"}})
            return

        model = request.get("model", "test-model")
        eof = scenario == "eof-no-terminal"
        if scenario == "http-error":
            self._json(503, {"error": {"type": "synthetic_upstream_error", "message": "synthetic-key-and-private-prompt-must-not-leak"}})
            return
        if scenario == "timeout":
            time.sleep(1.0)
        if scenario == "truncated-body":
            body = b'{"id":"t00-truncated","object":"chat.completion","choices":'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) + 128))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True
            return
        if self.path.endswith("/chat/completions"):
            if request.get("stream"):
                self._chat_stream(model, eof, scenario == "sse-error", "_INCOMPLETE_" in test_id, record, "_CANCEL_" in test_id)
            else:
                if "_TOOL_R1_" in test_id or "_TOOL_R2_" in test_id or "_TOOL_MALFORMED_" in test_id or "_TOOL_INVALID_" in test_id or "_TOOL_UNKNOWN_" in test_id:
                    self._chat_tool_response(model, test_id)
                    return
                if "_INCOMPLETE_" in test_id:
                    self._json(200, {
                        "id": "chatcmpl_t00_incomplete",
                        "object": "chat.completion",
                        "created": 1,
                        "model": model,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "synthetic partial"}, "finish_reason": "length"}],
                        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                    })
                    return
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
                self._responses_stream(model, eof, scenario == "sse-error", "_INCOMPLETE_" in test_id, record, "_CANCEL_" in test_id)
            else:
                if any(marker in test_id for marker in ("_TOOL_R1_", "_TOOL_R2_", "_TOOL_MALFORMED_", "_TOOL_INVALID_", "_TOOL_UNKNOWN_")):
                    self._responses_tool_response(model, test_id)
                    return
                if "_INCOMPLETE_" in test_id:
                    self._json(200, {
                        "id": "resp_t00_incomplete",
                        "object": "response",
                        "created_at": 1,
                        "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                        "model": model,
                        "output": [{"id": "msg_t00_incomplete", "type": "message", "role": "assistant", "status": "incomplete", "content": [{"type": "output_text", "text": "synthetic partial", "annotations": []}]}],
                        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                    })
                    return
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
                self._messages_stream(model, eof, scenario == "sse-error", "_INCOMPLETE_" in test_id, record, "_CANCEL_" in test_id)
            else:
                if any(marker in test_id for marker in ("_TOOL_R1_", "_TOOL_R2_", "_TOOL_MALFORMED_", "_TOOL_INVALID_", "_TOOL_UNKNOWN_")):
                    self._messages_tool_response(model, test_id)
                    return
                if "_INCOMPLETE_" in test_id:
                    self._json(200, {
                        "id": "msg_t00_incomplete",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [{"type": "text", "text": "synthetic partial"}],
                        "stop_reason": "max_tokens",
                        "stop_sequence": None,
                        "usage": {"input_tokens": 4, "output_tokens": 2},
                    })
                    return
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

    def _write_event(self, data, record=None):
        try:
            self.wfile.write(data)
            self.wfile.flush()
            if record is not None:
                record["upstream_stream_events_written"] = record.get("upstream_stream_events_written", 0) + 1
            return True
        except (BrokenPipeError, ConnectionResetError):
            if record is not None:
                record["client_disconnected"] = True
            self.close_connection = True
            return False

    def _send_sse(self, events, eof=False, record=None, cancel=False):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        cancel_event_index = next(
            (index for index, (event_name, _payload) in enumerate(events) if event_name == "content_block_delta"),
            1,
        )
        for index, (event_name, payload) in enumerate(events):
            if cancel and index == cancel_event_index:
                # Let the client close after the first event, then write enough
                # to make the upstream socket notice that the stream was closed.
                time.sleep(0.35)
                if event_name == "response.output_text.delta":
                    payload = {**payload, "delta": "x" * 1_048_576}
                elif event_name == "content_block_delta":
                    payload = {**payload, "delta": {"type": "text_delta", "text": "x" * 1_048_576}}
                elif event_name == "message":
                    payload = {**payload, "choices": [{"index": 0, "delta": {"content": "x" * 1_048_576}, "finish_reason": None}]}
            data = ("event: " + event_name + "\ndata: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode()
            if not self._write_event(data, record):
                return
        if not eof:
            if not self._write_event(b"data: [DONE]\n\n", record):
                return
        if record is not None and "client_disconnected" not in record:
            record["client_disconnected"] = False
        if record is not None:
            record["upstream_stream_body_finished"] = True
        self.close_connection = True

    def _chat_stream(self, model, eof=False, error=False, incomplete=False, record=None, cancel=False):
        def chunk(delta, finish=None):
            return {"id": "chatcmpl_t00_synthetic", "object": "chat.completion.chunk", "created": 1, "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        events = [("message", chunk({"role": "assistant"})), ("message", chunk({"content": "synthetic t00 stream"}))]
        if not eof and not error:
            events.append(("message", chunk({}, "length" if incomplete else "stop")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for index, (_name, payload) in enumerate(events):
            if cancel and index == 1:
                time.sleep(0.35)
                payload = chunk({"content": "x" * 1_048_576})
            data = ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode()
            if not self._write_event(data, record):
                return
        if error:
            error_payload = {"error": {"type": "server_error", "code": "synthetic_sse_error", "message": "synthetic-key-and-private-prompt-must-not-leak"}}
            if not self._write_event(("data: " + json.dumps(error_payload, separators=(",", ":")) + "\n\n").encode(), record):
                return
        if not eof and not error:
            if not self._write_event(b"data: [DONE]\n\n", record):
                return
        if record is not None and "client_disconnected" not in record:
            record["client_disconnected"] = False
        if record is not None:
            record["upstream_stream_body_finished"] = True
        self.close_connection = True

    def _responses_stream(self, model, eof=False, error=False, incomplete=False, record=None, cancel=False):
        created = {"id": "resp_t00_stream", "object": "response", "created_at": 1, "status": "in_progress", "model": model, "output": []}
        events = [("response.created", {"type": "response.created", "response": created}), ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "msg_t00", "output_index": 0, "content_index": 0, "delta": "synthetic t00 stream"})]
        if error:
            events.append(("error", {"type": "error", "error": {"type": "server_error", "code": "synthetic_sse_error", "message": "synthetic-key-and-private-prompt-must-not-leak"}}))
        elif incomplete:
            response = {"id": "resp_t00_stream", "object": "response", "created_at": 1, "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "model": model, "output": []}
            events.append(("response.incomplete", {"type": "response.incomplete", "response": response}))
        elif not eof:
            completed = {"id": "resp_t00_stream", "object": "response", "created_at": 1, "status": "completed", "model": model, "output": [{"id": "msg_t00", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "synthetic t00 stream", "annotations": []}]}]}
            events.append(("response.completed", {"type": "response.completed", "response": completed}))
        self._send_sse(events, eof=eof, record=record, cancel=cancel)

    def _messages_stream(self, model, eof=False, error=False, incomplete=False, record=None, cancel=False):
        start = {"type": "message_start", "message": {"id": "msg_t00", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 4, "output_tokens": 0}}}
        events = [("message_start", start), ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}), ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "synthetic t00 stream"}})]
        if error:
            events.append(("error", {"type": "error", "error": {"type": "api_error", "message": "synthetic-key-and-private-prompt-must-not-leak"}}))
        elif not eof:
            reason = "max_tokens" if incomplete else "end_turn"
            events.extend([("content_block_stop", {"type": "content_block_stop", "index": 0}), ("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None}, "usage": {"output_tokens": 5}}), ("message_stop", {"type": "message_stop"})])
        self._send_sse(events, eof=eof, record=record, cancel=cancel)


print("synthetic_upstream_ready", flush=True)
ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
