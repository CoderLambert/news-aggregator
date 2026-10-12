"""Thin official-SDK adapters for OpenAI Chat, OpenAI Responses and Messages."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from collections.abc import Callable
from threading import Event
from typing import Any

import httpx2
from anthropic import Anthropic
from openai import OpenAI

from .contracts import ModelEvent, ModelTurn, ProviderError, ServerContinuation, ToolCall


DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TOOL_CALLS = 4
ALLOWED_TOOLS = frozenset({"lookup"})
TOOL_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "maxLength": 200}},
    "required": ["query"],
    "additionalProperties": False,
}


def _http_client(timeout: float) -> httpx2.Client:
    # Explicitly opt out of environment proxy variables and redirects.  Tests
    # therefore cannot inherit a user's network settings or credential path.
    return httpx2.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )


def _openai_client(api_key: str, base_url: str, timeout: float) -> OpenAI:
    if not api_key:
        raise ValueError("api_key is required explicitly")
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
        timeout=timeout,
        http_client=_http_client(timeout),
    )


def _anthropic_client(api_key: str, base_url: str, timeout: float) -> Anthropic:
    if not api_key:
        raise ValueError("api_key is required explicitly")
    return Anthropic(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
        timeout=timeout,
        http_client=_http_client(timeout),
    )


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _provider_error(protocol: str, exc: Exception) -> ProviderError:
    """Classify SDK failures without copying exception strings or bodies."""
    if isinstance(exc, ProviderError):
        return exc
    status = getattr(exc, "status_code", None)
    status_code = status if isinstance(status, int) else None
    name = type(exc).__name__.lower()
    if status_code is not None:
        code = "provider_http_error"
    elif "timeout" in name:
        code = "provider_timeout"
    elif "stream" in name or "connection" in name or "network" in name:
        code = "provider_stream_error"
    else:
        code = "provider_error"
    return ProviderError(code, protocol, http_status=status_code)


def _raise_safe(protocol: str, exc: Exception, cancel_event: Event | None = None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ProviderError("request_cancelled", protocol) from None
    safe = _provider_error(protocol, exc)
    if safe is exc:
        raise safe
    raise safe from None


def _emit(
    events: list[ModelEvent],
    event: ModelEvent,
    on_event: Callable[[ModelEvent], None] | None,
) -> None:
    events.append(event)
    if on_event is not None:
        on_event(event)


def _check_cancel(cancel_event: Event | None, protocol: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ProviderError("request_cancelled", protocol)


def _strict_json_object(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        value = dict(raw)
    elif isinstance(raw, str):
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            parsed: dict[str, Any] = {}
            for key, item in pairs:
                if key in parsed:
                    raise ValueError("duplicate key")
                parsed[key] = item
            return parsed

        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    else:
        raise ValueError("tool arguments must be an object")
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be an object")
    return value


def _validated_tool_call(
    protocol: str,
    *,
    call_id: str,
    name: str,
    raw_arguments: str | Mapping[str, Any],
    allowed_tools: frozenset[str],
) -> ToolCall:
    if name not in allowed_tools or name not in ALLOWED_TOOLS:
        raise ProviderError("tool_not_allowlisted", protocol)
    try:
        arguments = _strict_json_object(raw_arguments)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ProviderError("tool_arguments_invalid", protocol) from None
    if (
        set(arguments) != {"query"}
        or not isinstance(arguments.get("query"), str)
        or not arguments["query"].strip()
        or len(arguments["query"]) > 200
    ):
        raise ProviderError("tool_arguments_invalid", protocol)
    return ToolCall(call_id, name, arguments, raw_arguments if isinstance(raw_arguments, str) else dict(raw_arguments))


def _validated_tools(
    protocol: str,
    raw_calls: Iterable[tuple[str, str, str | Mapping[str, Any]]],
    allowed_tools: frozenset[str],
) -> tuple[ToolCall, ...]:
    rows = list(raw_calls)
    if len(rows) > MAX_TOOL_CALLS:
        raise ProviderError("tool_call_limit", protocol)
    return tuple(
        _validated_tool_call(
            protocol,
            call_id=call_id,
            name=name,
            raw_arguments=arguments,
            allowed_tools=allowed_tools,
        )
        for call_id, name, arguments in rows
    )


def _chat_tool_spec() -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a short synthetic fact.",
            "parameters": TOOL_SCHEMA,
        },
    }]


def _responses_tool_spec() -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "name": "lookup",
        "description": "Look up a short synthetic fact.",
        "parameters": TOOL_SCHEMA,
        "strict": True,
    }]


def _messages_tool_spec() -> list[dict[str, Any]]:
    return [{
        "name": "lookup",
        "description": "Look up a short synthetic fact.",
        "input_schema": TOOL_SCHEMA,
    }]


class _Adapter:
    protocol: str

    def __init__(self, client: Any) -> None:
        self.client = client

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class ChatCompletionsAdapter(_Adapter):
    protocol = "openai_chat_completions"

    def __init__(self, api_key: str, base_url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        super().__init__(_openai_client(api_key, base_url, timeout))

    def turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        allow_tools: bool = False,
        allowed_tools: frozenset[str] = ALLOWED_TOOLS,
        max_output_tokens: int = 64,
        on_event: Callable[[ModelEvent], None] | None = None,
        cancel_event: Event | None = None,
    ) -> ModelTurn:
        protocol = self.protocol
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_output_tokens,
        }
        if allow_tools:
            request["tools"] = _chat_tool_spec()

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_parts: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None
        events: list[ModelEvent] = []
        stream_started = False
        try:
            with self.client.chat.completions.create(**request) as stream:
                stream_started = True
                for chunk in stream:
                    _check_cancel(cancel_event, protocol)
                    if getattr(chunk, "usage", None) is not None:
                        usage = _dump(chunk.usage)
                    for choice in chunk.choices:
                        delta = choice.delta
                        text_delta = getattr(delta, "content", None)
                        if isinstance(text_delta, str) and text_delta:
                            text_parts.append(text_delta)
                            _emit(events, ModelEvent("text_delta", protocol, text=text_delta), on_event)
                        reasoning_delta = getattr(delta, "reasoning_content", None)
                        if isinstance(reasoning_delta, str) and reasoning_delta:
                            reasoning_parts.append(reasoning_delta)
                        for item in getattr(delta, "tool_calls", None) or []:
                            index = getattr(item, "index", 0) or 0
                            target = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if getattr(item, "id", None):
                                target["id"] = item.id
                            function = getattr(item, "function", None)
                            if function is not None:
                                if getattr(function, "name", None):
                                    target["name"] += function.name
                                if getattr(function, "arguments", None):
                                    target["arguments"] += function.arguments
                            _emit(events, ModelEvent("tool_delta", protocol, _raw=_dump(item)), on_event)
                        if choice.finish_reason is not None:
                            finish_reason = choice.finish_reason
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderError("request_cancelled", protocol) from None
            if stream_started and not isinstance(exc, ProviderError):
                raise ProviderError("provider_stream_error", protocol) from None
            _raise_safe(protocol, exc, cancel_event)

        if finish_reason is None:
            raise ProviderError("stream_eof_without_terminal", protocol, finish_reason="eof")
        if finish_reason not in {"stop", "tool_calls"}:
            raise ProviderError("incomplete_turn", protocol, finish_reason=finish_reason)
        raw_calls = [
            (row["id"], row["name"], row["arguments"])
            for _index, row in sorted(tool_parts.items())
        ]
        if raw_calls and finish_reason != "tool_calls":
            raise ProviderError("invalid_tool_terminal", protocol, finish_reason=finish_reason)
        tool_calls = _validated_tools(protocol, raw_calls, allowed_tools) if raw_calls else ()
        raw_message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
        if reasoning_parts:
            raw_message["reasoning_content"] = "".join(reasoning_parts)
        if raw_calls:
            raw_message["tool_calls"] = [{
                "id": row["id"],
                "type": "function",
                "function": {"name": row["name"], "arguments": row["arguments"]},
            } for _index, row in sorted(tool_parts.items())]
        _emit(events, ModelEvent("terminal", protocol, finish_reason=finish_reason), on_event)
        return ModelTurn(
            text=raw_message["content"],
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            usage=usage,
            continuation=ServerContinuation(protocol, {"assistant_message": raw_message}),
            events=tuple(events),
        )


class ResponsesAdapter(_Adapter):
    protocol = "openai_responses"

    def __init__(self, api_key: str, base_url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        super().__init__(_openai_client(api_key, base_url, timeout))

    def turn(
        self,
        *,
        model: str,
        input: str | list[dict[str, Any]],
        allow_tools: bool = False,
        allowed_tools: frozenset[str] = ALLOWED_TOOLS,
        max_output_tokens: int = 64,
        on_event: Callable[[ModelEvent], None] | None = None,
        cancel_event: Event | None = None,
    ) -> ModelTurn:
        protocol = self.protocol
        request: dict[str, Any] = {
            "model": model,
            "input": input,
            "stream": True,
            "max_output_tokens": max_output_tokens,
        }
        if allow_tools:
            request["tools"] = _responses_tool_spec()
        text_parts: list[str] = []
        events: list[ModelEvent] = []
        terminal_type: str | None = None
        response_obj: Any = None
        stream_started = False
        try:
            with self.client.responses.create(**request) as stream:
                stream_started = True
                for event in stream:
                    _check_cancel(cancel_event, protocol)
                    event_type = getattr(event, "type", "")
                    if event_type == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            text_parts.append(delta)
                            _emit(events, ModelEvent("text_delta", protocol, text=delta, _raw=_dump(event)), on_event)
                    elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
                        terminal_type = event_type
                        response_obj = getattr(event, "response", None)
                        _emit(events, ModelEvent("terminal", protocol, finish_reason=event_type, _raw=_dump(event)), on_event)
                    elif event_type == "error":
                        raise ProviderError("provider_stream_error", protocol)
                    else:
                        _emit(events, ModelEvent("tool_delta", protocol, _raw=_dump(event)), on_event)
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderError("request_cancelled", protocol) from None
            if stream_started and not isinstance(exc, ProviderError):
                raise ProviderError("provider_stream_error", protocol) from None
            _raise_safe(protocol, exc, cancel_event)

        if terminal_type is None:
            raise ProviderError("stream_eof_without_terminal", protocol, finish_reason="eof")
        if terminal_type == "response.failed":
            raise ProviderError("provider_stream_error", protocol, finish_reason=terminal_type)
        if terminal_type == "response.incomplete":
            response_dict = _dump(response_obj)
            details = response_dict.get("incomplete_details") or {}
            reason = details.get("reason") or "incomplete"
            raise ProviderError("incomplete_turn", protocol, finish_reason=str(reason))
        response_dict = _dump(response_obj)
        if response_dict.get("status") not in {None, "completed"}:
            raise ProviderError("incomplete_turn", protocol, finish_reason=str(response_dict.get("status")))
        output = response_dict.get("output") or []
        raw_calls = [
            (str(item.get("call_id", "")), str(item.get("name", "")), item.get("arguments", ""))
            for item in output
            if item.get("type") == "function_call"
        ]
        tool_calls = _validated_tools(protocol, raw_calls, allowed_tools) if raw_calls else ()
        final_text = "".join(
            str(content.get("text", ""))
            for item in output
            if item.get("type") == "message"
            for content in item.get("content", [])
            if content.get("type") == "output_text"
        )
        if not final_text:
            final_text = "".join(text_parts)
        usage = response_dict.get("usage") if isinstance(response_dict.get("usage"), dict) else None
        if terminal_type != "response.completed":
            _emit(events, ModelEvent("terminal", protocol, finish_reason="completed"), on_event)
        return ModelTurn(
            text=final_text,
            finish_reason="tool_calls" if raw_calls else "completed",
            tool_calls=tool_calls,
            usage=usage,
            continuation=ServerContinuation(protocol, {
                "response_id": response_dict.get("id"),
                "output_items": output,
            }),
            events=tuple(events),
        )


class MessagesAdapter(_Adapter):
    protocol = "anthropic_messages"

    def __init__(self, api_key: str, base_url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        super().__init__(_anthropic_client(api_key, base_url, timeout))

    def turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        allow_tools: bool = False,
        allowed_tools: frozenset[str] = ALLOWED_TOOLS,
        max_output_tokens: int = 64,
        on_event: Callable[[ModelEvent], None] | None = None,
        cancel_event: Event | None = None,
    ) -> ModelTurn:
        protocol = self.protocol
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": messages,
        }
        if allow_tools:
            request["tools"] = _messages_tool_spec()
        text_parts: list[str] = []
        partial_json: dict[int, str] = {}
        event_types: list[str] = []
        events: list[ModelEvent] = []
        stop_reason: str | None = None
        saw_message_stop = False
        stream: Any = None
        stream_started = False
        try:
            with self.client.messages.stream(**request) as stream:
                stream_started = True
                for event in stream:
                    _check_cancel(cancel_event, protocol)
                    event_type = getattr(event, "type", "")
                    event_types.append(event_type)
                    if event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        delta_type = getattr(delta, "type", "")
                        index = getattr(event, "index", 0)
                        if delta_type == "text_delta":
                            value = getattr(delta, "text", "")
                            if value:
                                text_parts.append(value)
                                _emit(events, ModelEvent("text_delta", protocol, text=value, _raw=_dump(event)), on_event)
                        elif delta_type == "input_json_delta":
                            partial_json[index] = partial_json.get(index, "") + str(getattr(delta, "partial_json", ""))
                            _emit(events, ModelEvent("tool_delta", protocol, _raw=_dump(event)), on_event)
                        else:
                            # Thinking and signature deltas remain in the final
                            # provider-native message kept only in continuation.
                            _emit(events, ModelEvent("tool_delta", protocol, _raw=_dump(event)), on_event)
                    elif event_type == "message_delta":
                        delta = getattr(event, "delta", None)
                        stop_reason = getattr(delta, "stop_reason", None)
                        _emit(events, ModelEvent("terminal", protocol, finish_reason=stop_reason, _raw=_dump(event)), on_event)
                    elif event_type == "message_stop":
                        saw_message_stop = True
                    elif event_type == "error":
                        raise ProviderError("provider_stream_error", protocol)
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise ProviderError("request_cancelled", protocol) from None
            if stream_started and not isinstance(exc, ProviderError):
                # Anthropic's SDK may represent an SSE `error` event as an
                # APIStatusError. Once the HTTP 200 stream has begun, that is
                # a provider stream failure rather than an HTTP response error.
                raise ProviderError("provider_stream_error", protocol) from None
            _raise_safe(protocol, exc)

        if not saw_message_stop:
            raise ProviderError("stream_eof_without_terminal", protocol, finish_reason="eof")
        if stop_reason not in {"end_turn", "tool_use"}:
            raise ProviderError("incomplete_turn", protocol, finish_reason=str(stop_reason or "missing"))
        for raw in partial_json.values():
            try:
                _strict_json_object(raw)
            except (ValueError, TypeError, json.JSONDecodeError):
                raise ProviderError("tool_arguments_invalid", protocol) from None
        try:
            final_message = stream.get_final_message()
        except Exception as exc:
            _raise_safe(protocol, exc, cancel_event)
        raw_message = _dump(final_message)
        blocks = raw_message.get("content") or []
        raw_calls = [
            (str(block.get("id", "")), str(block.get("name", "")), block.get("input", {}))
            for block in blocks
            if block.get("type") == "tool_use"
        ]
        if raw_calls and stop_reason != "tool_use":
            raise ProviderError("invalid_tool_terminal", protocol, finish_reason=str(stop_reason))
        tool_calls = _validated_tools(protocol, raw_calls, allowed_tools) if raw_calls else ()
        final_text = "".join(str(block.get("text", "")) for block in blocks if block.get("type") == "text")
        usage = raw_message.get("usage") if isinstance(raw_message.get("usage"), dict) else None
        if not events or events[-1].kind != "terminal":
            _emit(events, ModelEvent("terminal", protocol, finish_reason=stop_reason), on_event)
        return ModelTurn(
            text=final_text or "".join(text_parts),
            finish_reason=str(stop_reason),
            tool_calls=tool_calls,
            usage=usage,
            continuation=ServerContinuation(protocol, {"message": raw_message, "event_types": event_types}),
            events=tuple(events),
        )
