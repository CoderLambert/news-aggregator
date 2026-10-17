"""Official SDK test calls adapted from PR #33 at 6867409.

These helpers exercise a configured loopback endpoint. They are not imported by
NewsHub and contain no provider HTTP/SSE adapter or fallback implementation.
"""
from __future__ import annotations

import json
import ipaddress
import time
import urllib.request
import urllib.parse
from urllib.error import HTTPError

import httpx2
from openai import OpenAI
from anthropic import Anthropic

SDK_MAX_RETRIES = 0
CANCEL_PROPAGATION_OBSERVATION_WINDOW_SECONDS = 2.0
URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CLIENTS_CREATED = []
TOOL_DISPATCH_COUNT = 0

def validate_loopback_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    try:
        local = ipaddress.ip_address(parts.hostname or "").is_loopback
    except ValueError:
        local = False
    if parts.scheme != "http" or not local or parts.username or parts.password:
        raise ValueError("T00_LOOPBACK_URL_REQUIRED")
    return url

class HttpStatusError(RuntimeError):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__("T00_HTTP_ERROR")

def request_json(
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict:
    validate_loopback_url(url)
    data = None if payload is None else json.dumps(payload).encode()
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with URL_OPENER.open(request, timeout=timeout) as response:
            decoded = json.load(response)
    except urllib.error.HTTPError as exc:
        raise HttpStatusError(exc.code) from None
    if not isinstance(decoded, dict):
        raise RuntimeError("unexpected JSON response")
    return decoded


def http_status_ok(url: str, timeout: float = 1.0) -> bool:
    """Return only whether a local health endpoint responds with HTTP 2xx."""
    validate_loopback_url(url)
    request = urllib.request.Request(url)
    try:
        with URL_OPENER.open(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def openai_client(api_key: str, base_url: str, *, timeout: float = 30.0) -> OpenAI:
    validate_loopback_url(base_url)
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=SDK_MAX_RETRIES,
        http_client=httpx2.Client(trust_env=False, timeout=timeout),
    )
    CLIENTS_CREATED.append(client)
    return client


def anthropic_client(api_key: str, base_url: str, *, auth_token: bool = False, timeout: float = 30.0) -> Anthropic:
    validate_loopback_url(base_url)
    kwargs = {
        "base_url": base_url,
        "max_retries": 0,
        "http_client": httpx2.Client(trust_env=False, timeout=timeout),
    }
    if auth_token:
        # Official Anthropic SDK's auth_token uses Authorization: Bearer for Proxy auth.
        kwargs["api_key"] = ""
        kwargs["auth_token"] = api_key
    else:
        # Official Anthropic SDK's api_key uses x-api-key for the provider credential.
        kwargs["api_key"] = api_key
    client = Anthropic(**kwargs)
    CLIENTS_CREATED.append(client)
    return client


def safe_exception(exc: Exception) -> dict:
    return {
        "success": False,
        "status_code": getattr(exc, "status_code", None),
        "error_type": type(exc).__name__,
    }


def run_incomplete_cases(base_url: str, protocol: str, *, project_key: str | None = None, provider_key: str | None = None) -> dict:
    """Check native length/incomplete endings without converting them to complete."""
    marker = f"T00_{'PROXY' if project_key else 'SDK'}_{protocol.upper()}_INCOMPLETE_A"
    sdk_key = project_key or provider_key or ""
    if protocol == "chat":
        client = openai_client(sdk_key, base_url)
        try:
            kwargs = {"model": "t00-chat" if project_key else "test-model", "messages": [{"role": "user", "content": marker}]}
            if project_key and provider_key:
                kwargs["extra_body"] = {"api_key": provider_key}
            response = client.chat.completions.create(**kwargs)
            return {"success": True, "terminal": response.choices[0].finish_reason}
        except Exception as exc:
            return safe_exception(exc)
        finally:
            client.close()
    if protocol == "responses":
        client = openai_client(sdk_key, base_url)
        try:
            kwargs = {"model": "t00-chat" if project_key else "test-model", "input": marker}
            if project_key and provider_key:
                kwargs["extra_body"] = {"api_key": provider_key}
            response = client.responses.create(**kwargs)
            return {"success": True, "terminal": response.status, "incomplete_reason": None if response.incomplete_details is None else response.incomplete_details.reason}
        except Exception as exc:
            return safe_exception(exc)
        finally:
            client.close()
    client = anthropic_client(sdk_key, base_url, auth_token=bool(project_key))
    try:
        kwargs = {"model": "t00-messages" if project_key else "test-model", "max_tokens": 40, "messages": [{"role": "user", "content": marker}]}
        if project_key and provider_key:
            kwargs["extra_body"] = {"api_key": provider_key}
        response = client.messages.create(**kwargs)
        return {"success": True, "terminal": response.stop_reason}
    except Exception as exc:
        return safe_exception(exc)
    finally:
        client.close()


def protocol_client(protocol: str, sdk_key: str, base_url: str, *, via_proxy: bool, timeout: float = 10.0):
    if protocol == "messages":
        return anthropic_client(sdk_key, base_url, auth_token=via_proxy, timeout=timeout)
    return openai_client(sdk_key, base_url, timeout=timeout)


def protocol_request(protocol: str, model: str, marker: str, *, provider_key: str | None, via_proxy: bool, stream: bool = False) -> dict:
    if protocol == "chat":
        kwargs = {"model": model, "messages": [{"role": "user", "content": marker}]}
    elif protocol == "responses":
        kwargs = {"model": model, "input": marker}
    else:
        kwargs = {"model": model, "max_tokens": 40, "messages": [{"role": "user", "content": marker}]}
    if stream:
        kwargs["stream"] = True
    if via_proxy and provider_key is not None:
        kwargs["extra_body"] = {"api_key": provider_key}
    return kwargs


def run_protocol_error_cases(
    base_url: str,
    protocol: str,
    test_prefix: str,
    sdk_key: str,
    *,
    provider_key: str | None = None,
    via_proxy: bool = False,
    cases: tuple[str, ...] = ("HTTP_ERROR", "TIMEOUT", "TRUNCATED", "SSE_ERROR"),
) -> dict:
    """Run one request per synthetic error class through one SDK/protocol path."""
    model = ("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model"
    results = {}
    for case in cases:
        marker = f"{test_prefix}_{case}_A"
        client = protocol_client(
            protocol, sdk_key, base_url, via_proxy=via_proxy,
            timeout=0.15 if case == "TIMEOUT" else 10.0,
        )
        try:
            kwargs = protocol_request(
                protocol, model, marker, provider_key=provider_key,
                via_proxy=via_proxy, stream=case == "SSE_ERROR",
            )
            if case == "SSE_ERROR":
                response = (
                    client.chat.completions.create(**kwargs)
                    if protocol == "chat" else
                    client.responses.create(**kwargs)
                    if protocol == "responses" else
                    client.messages.create(**kwargs)
                )
                with response:
                    for _event in response:
                        pass
                result = {"success": True, "error_type": None}
            elif protocol == "chat":
                response = client.chat.completions.create(**kwargs)
                result = {"success": True, "finish_reason": response.choices[0].finish_reason}
            elif protocol == "responses":
                response = client.responses.create(**kwargs)
                result = {"success": True, "terminal": response.status}
            else:
                response = client.messages.create(**kwargs)
                result = {"success": True, "terminal": response.stop_reason}
        except Exception as exc:
            result = safe_exception(exc)
        finally:
            client.close()
        results[case.lower()] = result
    return results


def _stream_event_facts(protocol: str, event: object) -> tuple[str | None, str | None]:
    event_type = getattr(event, "type", None)
    terminal = None
    stop_reason = None
    if protocol == "chat":
        event_type = "chat.chunk"
        for choice in getattr(event, "choices", []) or []:
            if choice.finish_reason is not None:
                terminal = choice.finish_reason
    elif protocol == "responses" and event_type in {"response.completed", "response.incomplete", "response.failed", "error"}:
        response = getattr(event, "response", None)
        terminal = getattr(response, "status", None) or event_type
    elif protocol == "messages" and event_type == "message_delta":
        delta = getattr(event, "delta", None)
        stop_reason = getattr(delta, "stop_reason", None)
        terminal = stop_reason
    elif protocol == "messages" and event_type in {"message_stop", "error"}:
        terminal = event_type
    return event_type, terminal if terminal is not None else stop_reason


def run_protocol_stream_case(
    base_url: str,
    protocol: str,
    case: str,
    sdk_key: str,
    *,
    provider_key: str | None = None,
    via_proxy: bool = False,
    upstream_url: str | None = None,
    proxy_health_url: str | None = None,
) -> dict:
    """Read a protocol stream with the official SDK and record only event names/terminals."""
    prefix = "PROXY" if via_proxy else "SDK"
    marker = f"T00_{prefix}_{protocol.upper()}_STREAM_{case}_A"
    model = ("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model"
    client = protocol_client(protocol, sdk_key, base_url, via_proxy=via_proxy)
    stream = None
    event_types: list[str] = []
    terminals: list[str] = []
    canceled_after_first = False
    downstream_close_monotonic_ns = None
    result: dict = {"success": False}
    try:
        kwargs = protocol_request(
            protocol, model, marker, provider_key=provider_key,
            via_proxy=via_proxy, stream=True,
        )
        if protocol == "chat":
            stream = client.chat.completions.create(**kwargs)
        elif protocol == "responses":
            stream = client.responses.create(**kwargs)
        else:
            stream = client.messages.create(**kwargs)
        with stream:
            if case == "CANCEL":
                event = next(iter(stream))
                event_type, terminal = _stream_event_facts(protocol, event)
                if event_type:
                    event_types.append(event_type)
                if terminal:
                    terminals.append(terminal)
                canceled_after_first = True
            else:
                for event in stream:
                    event_type, terminal = _stream_event_facts(protocol, event)
                    if event_type:
                        event_types.append(event_type)
                    if terminal:
                        terminals.append(terminal)
        result = {
            "success": True,
            "outcome": "cancelled" if case == "CANCEL" else "stream_consumed",
            "stream_consumed": case != "CANCEL",
        }
    except Exception as exc:
        result = safe_exception(exc)
    finally:
        try:
            # SIGTERM is translated to KeyboardInterrupt. It must propagate,
            # while resources close even if interruption precedes __enter__.
            if stream is not None:
                stream.close()
            response = getattr(stream, "response", None)
            if case == "CANCEL":
                downstream_close_monotonic_ns = time.monotonic_ns()
            result.update({
                "event_count": len(event_types),
                "event_types": event_types,
                "terminals": terminals,
                "canceled_after_first_event": canceled_after_first,
                "client_response_closed": bool(response is not None and response.is_closed),
                "downstream_close_monotonic_ns": downstream_close_monotonic_ns,
            })
        finally:
            client.close()
    if case == "CANCEL" and upstream_url and downstream_close_monotonic_ns is not None:
        deadline = time.monotonic() + CANCEL_PROPAGATION_OBSERVATION_WINDOW_SECONDS
        latest_stats: dict = {}
        observed_record: dict = {}
        while time.monotonic() <= deadline:
            try:
                latest_stats = request_json(upstream_url + "/stats", timeout=0.25)
                observed_record = next((
                    item for item in latest_stats.get("records", [])
                    if item.get("test_id") == marker
                ), {})
            except (OSError, RuntimeError, HttpStatusError):
                observed_record = {}
            if (
                observed_record.get("client_disconnected") is True
                and observed_record.get("upstream_stream_producer_exit_monotonic_ns") is not None
            ):
                break
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

        disconnect_ns = observed_record.get("upstream_disconnect_monotonic_ns")
        producer_exit_ns = observed_record.get("upstream_stream_producer_exit_monotonic_ns")
        disconnect_delay_ms = (
            None if disconnect_ns is None else round((disconnect_ns - downstream_close_monotonic_ns) / 1_000_000, 3)
        )
        producer_exit_delay_ms = (
            None if producer_exit_ns is None else round((producer_exit_ns - downstream_close_monotonic_ns) / 1_000_000, 3)
        )
        observation_window_ms = int(CANCEL_PROPAGATION_OBSERVATION_WINDOW_SECONDS * 1000)
        active_producers = latest_stats.get("active_stream_producers")
        proxy_liveness_ok = (
            None if proxy_health_url is None else http_status_ok(proxy_health_url, timeout=1.0)
        )
        write_times = observed_record.get("upstream_stream_write_monotonic_ns", [])
        result.update({
            "cancel_observation_window_ms": observation_window_ms,
            "upstream_disconnect_delay_ms": disconnect_delay_ms,
            "upstream_producer_exit_delay_ms": producer_exit_delay_ms,
            "upstream_disconnect_monotonic_ns": disconnect_ns,
            "upstream_producer_exit_monotonic_ns": producer_exit_ns,
            "upstream_disconnect_within_observation_window": (
                disconnect_delay_ms is not None and 0 <= disconnect_delay_ms <= observation_window_ms
            ),
            "upstream_producer_exited_within_observation_window": (
                producer_exit_delay_ms is not None and 0 <= producer_exit_delay_ms <= observation_window_ms
            ),
            "active_upstream_producers_at_observation_end": active_producers,
            "proxy_liveness_http_2xx_after_cancel": proxy_liveness_ok,
            "upstream_disconnect_observed": observed_record.get("client_disconnected") is True,
            "upstream_producer_exit_reason": observed_record.get("producer_exit_reason"),
            "upstream_stream_body_finished": observed_record.get("upstream_stream_body_finished") is True,
            "upstream_frames_written_at_disconnect": observed_record.get("upstream_stream_events_written"),
            "upstream_frames_written_after_downstream_close": (
                sum(1 for write_ns in write_times if write_ns > downstream_close_monotonic_ns)
                if isinstance(write_times, list) else None
            ),
            "upstream_cancel_fixture_frames_written": observed_record.get("cancel_fixture_frames_written", 0),
        })
    return result


OPENAI_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}


TOOL_SCHEMAS = {
    "lookup_weather": {"city"},
    "format_weather": {"summary"},
}


def dispatch_synthetic_tool(name: str, arguments: str | dict) -> tuple[str, str | None]:
    """Validate tool output before dispatching to pure, local fixture functions."""
    global TOOL_DISPATCH_COUNT
    if name not in TOOL_SCHEMAS:
        return "not_allowlisted", None
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            reason = "partial_json" if exc.pos >= len(arguments.rstrip()) else "invalid_json"
            return reason, None
    elif isinstance(arguments, dict):
        parsed = arguments
    else:
        return "invalid_argument_shape", None
    if not isinstance(parsed, dict) or set(parsed) != TOOL_SCHEMAS[name]:
        return "invalid_argument_shape", None
    value = parsed[next(iter(TOOL_SCHEMAS[name]))]
    if not isinstance(value, str):
        return "invalid_argument_shape", None
    if name == "lookup_weather" and value == "synthetic-city":
        TOOL_DISPATCH_COUNT += 1
        return "dispatched", "synthetic-weather"
    if name == "format_weather" and value == "synthetic-weather":
        TOOL_DISPATCH_COUNT += 1
        return "dispatched", "synthetic-summary"
    return "invalid_argument_value", None


def tool_definitions(protocol: str) -> list[dict]:
    if protocol == "messages":
        return [
            {"name": "lookup_weather", "description": "Synthetic local lookup", "input_schema": OPENAI_TOOL_SCHEMA},
            {"name": "format_weather", "description": "Synthetic local formatter", "input_schema": {
                "type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False,
            }},
        ]
    if protocol == "responses":
        return [
            {"type": "function", "name": "lookup_weather", "description": "Synthetic local lookup", "parameters": OPENAI_TOOL_SCHEMA},
            {"type": "function", "name": "format_weather", "description": "Synthetic local formatter", "parameters": {
                "type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False,
            }},
        ]
    return [
        {"type": "function", "function": {"name": "lookup_weather", "description": "Synthetic local lookup", "parameters": OPENAI_TOOL_SCHEMA}},
        {"type": "function", "function": {"name": "format_weather", "description": "Synthetic local formatter", "parameters": {
            "type": "object", "properties": {"summary": {"type": "string"}},
            "required": ["summary"], "additionalProperties": False,
        }}},
    ]


def _public_output(text: str | None, continuation: object, secrets: list[str]) -> tuple[dict, bool, bool]:
    public = {"text": text}
    serialized = json.dumps(public, ensure_ascii=True, sort_keys=True)
    continuation_serialized = json.dumps(continuation, ensure_ascii=True, default=str)
    leaked_continuation = any(
        value and value in serialized for value in (
            "opaque-chat-state-r1", "opaque-chat-state-r2",
            "opaque-responses-continuation-r1", "opaque-responses-continuation-r2",
            "opaque-messages-state-r1", "opaque-signature-r1", "opaque-signature-r2",
        )
    ) or continuation_serialized in serialized
    leaked_key = any(value and value in serialized for value in secrets)
    return public, leaked_continuation, leaked_key


def proxy_tool_roundtrip(
    protocol: str,
    proxy_url: str,
    project_key: str,
    provider_key: str,
    *,
    via_proxy: bool = True,
    foreign_responses_ids: bool = False,
) -> dict:
    """Two synthetic tool turns through the official SDK and optional Proxy."""
    public_text = None
    continuation_snapshots = []
    dispatch_outcomes = []
    source = "PROXY" if via_proxy else "SDK"
    model = ("t00-messages" if protocol == "messages" else "t00-chat") if via_proxy else "test-model"
    provider_body = {"extra_body": {"api_key": provider_key}} if via_proxy else {}
    client = (
        anthropic_client(project_key, proxy_url, auth_token=via_proxy)
        if protocol == "messages"
        else openai_client(project_key, proxy_url + "/v1")
    )
    try:
        if protocol == "chat":
            conversation = [{"role": "user", "content": f"T00_{source}_CHAT_TOOL_R1_A"}]
            for round_number in (1, 2):
                response = client.chat.completions.create(
                    model=model, messages=conversation, tools=tool_definitions("chat"),
                    **provider_body,
                )
                if len(response.choices) != 1 or response.choices[0].finish_reason != "tool_calls":
                    raise RuntimeError("T00_INCOMPLETE_TOOL_TURN")
                message = response.choices[0].message
                raw_message = message.model_dump(exclude_none=True)
                continuation_snapshots.append(raw_message)
                conversation.append(raw_message)
                for call in message.tool_calls or []:
                    outcome, result = dispatch_synthetic_tool(call.function.name, call.function.arguments)
                    dispatch_outcomes.append(outcome)
                    if outcome == "dispatched":
                        conversation.append({"role": "tool", "tool_call_id": call.id, "content": result})
                conversation.append({"role": "user", "content": f"T00_{source}_CHAT_TOOL_R{round_number + 1}_A" if round_number == 1 else f"T00_{source}_CHAT_TOOL_FINAL_A"})
            final = client.chat.completions.create(
                model=model, messages=conversation,
                **provider_body,
            )
            if len(final.choices) != 1 or final.choices[0].finish_reason != "stop":
                raise RuntimeError("T00_INCOMPLETE_FINAL_TURN")
            public_text = final.choices[0].message.content
        elif protocol == "responses":
            marker_prefix = f"T00_{source}_RESPONSES_" + ("FOREIGN_TOOL_" if foreign_responses_ids else "TOOL_")
            input_items = [{"role": "user", "content": marker_prefix + "R1_A"}]
            for round_number in (1, 2):
                response = client.responses.create(
                    model=model, input=input_items, tools=tool_definitions("responses"),
                    **provider_body,
                )
                if response.status != "completed":
                    raise RuntimeError("T00_INCOMPLETE_TOOL_TURN")
                raw_items = [item.model_dump(exclude_none=True) for item in response.output]
                continuation_snapshots.append(raw_items)
                input_items.extend(raw_items)
                for item in response.output:
                    if getattr(item, "type", None) != "function_call":
                        continue
                    outcome, result = dispatch_synthetic_tool(item.name, item.arguments)
                    dispatch_outcomes.append(outcome)
                    if outcome == "dispatched":
                        input_items.append({"type": "function_call_output", "call_id": item.call_id, "output": result})
                input_items.append({"role": "user", "content": marker_prefix + f"R{round_number + 1}_A" if round_number == 1 else marker_prefix + "FINAL_A"})
            final = client.responses.create(
                model=model, input=input_items,
                **provider_body,
            )
            if final.status != "completed":
                raise RuntimeError("T00_INCOMPLETE_FINAL_TURN")
            public_text = final.output_text
        else:
            messages = [{"role": "user", "content": f"T00_{source}_MESSAGES_TOOL_R1_A"}]
            for round_number in (1, 2):
                response = client.messages.create(
                    model=model, max_tokens=40, messages=messages,
                    tools=tool_definitions("messages"),
                    **provider_body,
                )
                if response.stop_reason != "tool_use":
                    raise RuntimeError("T00_INCOMPLETE_TOOL_TURN")
                raw_content = [block.model_dump(exclude_none=True) for block in response.content]
                continuation_snapshots.append(raw_content)
                messages.append({"role": "assistant", "content": raw_content})
                for block in response.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    outcome, result = dispatch_synthetic_tool(block.name, block.input)
                    dispatch_outcomes.append(outcome)
                    if outcome == "dispatched":
                        messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "content": result}]})
                messages.append({"role": "user", "content": f"T00_{source}_MESSAGES_TOOL_R{round_number + 1}_A" if round_number == 1 else f"T00_{source}_MESSAGES_TOOL_FINAL_A"})
            final = client.messages.create(
                model=model, max_tokens=40, messages=messages,
                **provider_body,
            )
            if final.stop_reason != "end_turn":
                raise RuntimeError("T00_INCOMPLETE_FINAL_TURN")
            public_text = "".join(block.text for block in final.content if getattr(block, "type", None) == "text")
        if not isinstance(public_text, str) or not public_text.strip():
            raise RuntimeError("T00_EMPTY_FINAL_TEXT")
        public, continuation_leak, key_leak = _public_output(public_text, continuation_snapshots, [provider_key, project_key])
        return {
            "success": True,
            "public_output": public,
            "tool_dispatch_outcomes": dispatch_outcomes,
            "continuation_in_public": continuation_leak,
            "key_in_public": key_leak,
        }
    except Exception as exc:
        return safe_exception(exc)
    finally:
        client.close()


def probe_invalid_tool(protocol: str, variant: str, proxy_url: str, project_key: str, provider_key: str) -> dict:
    before_dispatch = TOOL_DISPATCH_COUNT
    test_id = f"T00_PROXY_{protocol.upper()}_TOOL_{variant.upper()}_A"
    client = anthropic_client(project_key, proxy_url, auth_token=True) if protocol == "messages" else openai_client(project_key, proxy_url + "/v1")
    try:
        if protocol == "chat":
            response = client.chat.completions.create(
                model="t00-chat", messages=[{"role": "user", "content": test_id}],
                tools=tool_definitions("chat"), extra_body={"api_key": provider_key},
            )
            call = response.choices[0].message.tool_calls[0]
            outcome, _ = dispatch_synthetic_tool(call.function.name, call.function.arguments)
        elif protocol == "responses":
            response = client.responses.create(
                model="t00-chat", input=test_id, tools=tool_definitions("responses"),
                extra_body={"api_key": provider_key},
            )
            call = next(item for item in response.output if getattr(item, "type", None) == "function_call")
            outcome, _ = dispatch_synthetic_tool(call.name, call.arguments)
        else:
            response = client.messages.create(
                model="t00-messages", max_tokens=40, messages=[{"role": "user", "content": test_id}],
                tools=tool_definitions("messages"), extra_body={"api_key": provider_key},
            )
            call = next(item for item in response.content if getattr(item, "type", None) == "tool_use")
            outcome, _ = dispatch_synthetic_tool(call.name, call.input)
        return {"success": True, "test_id": test_id, "rejection": outcome, "dispatched": outcome == "dispatched", "tool_dispatch_count": TOOL_DISPATCH_COUNT - before_dispatch}
    except Exception as exc:
        return {"success": False, "test_id": test_id, "dispatched": TOOL_DISPATCH_COUNT > before_dispatch, "tool_dispatch_count": TOOL_DISPATCH_COUNT - before_dispatch, **safe_exception(exc)}
    finally:
        client.close()
