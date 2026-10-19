"""Fail-closed request-scoped BYOK key guard and verified T04 stream boundary.

Only the exact pinned DeepSeek Chat route is stream-enabled. A pinned Router
boundary retains the original 1.105.0 provider wrapper for the whole-iterator
hook's terminal check; unknown routes, wrappers, or versions fail closed.
"""
from __future__ import annotations

import functools
import importlib.metadata
import inspect
import os
import threading

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger


BYOK_CALL_TYPES = frozenset({"acompletion", "completion", "aresponses", "anthropic_messages"})
ALWAYS_DENIED_STREAMING_CALL_TYPES = frozenset({"acompletion", "completion"})
TERMINAL_STREAM_MODEL = "deepseek/deepseek-flash"
TERMINAL_STREAM_ENV = "BYOK_TERMINAL_STREAMING_MODELS"
DENY_STREAM_ENV = "BYOK_DENY_STREAMING_CALL_TYPES"
_STREAM_FALSE_STRINGS = frozenset({"0", "false", "f", "no", "n", "off"})
_URL_OVERRIDE_FIELDS = frozenset({"api_base", "base_url", "api_url", "url"})
_TERMINAL_ERROR = {"code": "T00_STREAM_TERMINAL_UNVERIFIED"}
_ROUTER_RAW_SOURCE_ATTR = "_byok_raw_terminal_source"
_ROUTER_PROVENANCE_TOKEN_ATTR = "_byok_terminal_provenance_token"
_ROUTER_PATCH_MARKER = "_byok_terminal_provenance_patch"
_ROUTER_PROVENANCE_TOKEN = object()
_ROUTER_PATCH_LOCK = threading.Lock()
_ROUTER_PATCHED_CLASS = None
_ROUTER_PATCHED_METHOD = None
_PARSER_PROVENANCE_TOKEN = object()
_PARSER_PROVENANCE_ATTR = "_byok_raw_terminal_parser_token"
_PARSER_STOP_ATTR = "_byok_raw_json_stop"
_PARSER_DONE_ATTR = "_byok_exact_sse_done"
_PARSER_INVALID_ATTR = "_byok_terminal_invalid"
_PARSER_USAGE_ATTR = "_byok_terminal_usage_seen"
_PARSER_ALLOW_USAGE_ATTR = "_byok_terminal_usage_allowed"
_PARSER_CLOSED_ATTR = "_byok_terminal_response_closed"
_PARSER_PATCH_MARKER = "_byok_deepseek_parser_patch"
_PARSER_PATCHED_CLASS = None
_PARSER_ORIGINAL_ANEXT = None
_PARSER_PATCHED_ANEXT = None
TERMINAL_DIAGNOSTICS_ENV = "BYOK_T00_SYNTHETIC_GUARD_DIAGNOSTICS"
_TERMINAL_DIAGNOSTIC_REASONS = frozenset({
    "version_unavailable",
    "version_mismatch",
    "router_provenance_patch_unavailable",
    "router_method_mismatch",
    "wrapper_types_unavailable",
    "boundary_type_mismatch",
    "router_wrapper_type_mismatch",
    "router_provenance_missing",
    "raw_source_type_mismatch",
    "source_provider_mismatch",
    "source_provider_unavailable",
    "fallback_activated",
    "parser_patch_unavailable",
    "parser_provenance_missing",
    "raw_json_terminal_missing",
    "raw_stream_invalid",
})


def _safe_label(value, limit: int = 192) -> str:
    if not isinstance(value, str):
        return "unavailable"
    safe = "".join(
        character if character.isalnum() or character in "._:<>" else "_"
        for character in value
    )
    return safe[:limit] or "unavailable"


def _type_label(value) -> str:
    value_type = type(value)
    module = getattr(value_type, "__module__", "unknown")
    name = getattr(value_type, "__qualname__", getattr(value_type, "__name__", "unknown"))
    return _safe_label(f"{module}.{name}")


def _source_provider_label(source) -> str:
    if source is None:
        return "missing"
    try:
        provider = getattr(source, "custom_llm_provider", None)
    except Exception:
        return "missing"
    if provider is None:
        return "missing"
    if not isinstance(provider, str):
        return "other"
    return provider if provider in {"deepseek", "openai"} else "other"


def _terminal_error_detail(
    reason: str,
    response,
    source=None,
    version: str = "unavailable",
) -> dict:
    detail = dict(_TERMINAL_ERROR)
    if os.environ.get(TERMINAL_DIAGNOSTICS_ENV) == "1":
        detail["diagnostic"] = {
            "reason": reason if reason in _TERMINAL_DIAGNOSTIC_REASONS else "internal_guard_failure",
            "litellm_version": _safe_label(version, 64),
            "response_type": _type_label(response),
            "source_type": _type_label(source) if source is not None else "missing",
            "source_provider": _source_provider_label(source),
        }
    return detail


def _stream_requested(value: object) -> bool:
    """Conservatively detect streaming before LiteLLM coerces raw JSON."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _STREAM_FALSE_STRINGS
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)) and value == 0:
        return False
    return True


def _configured_terminal_models() -> frozenset[str]:
    values = os.environ.get(TERMINAL_STREAM_ENV, "").split(",")
    return frozenset(item.strip() for item in values if item.strip() and item.strip() == TERMINAL_STREAM_MODEL)


def _extra_denied_streaming_call_types() -> frozenset[str]:
    values = os.environ.get(DENY_STREAM_ENV, "")
    return frozenset(item.strip().lower() for item in values.split(",") if item.strip())


def _terminal_stream_allowlisted(data: dict, call_type: str) -> bool:
    return (
        call_type == "acompletion"
        and data.get("stream") is True
        and isinstance(data.get("model"), str)
        and data["model"] in _configured_terminal_models()
        and isinstance(data.get("api_key"), str)
        and bool(data["api_key"].strip())
        and not (_URL_OVERRIDE_FIELDS & data.keys())
        and (data.get("n", 1) is None or (type(data.get("n", 1)) is int and data.get("n", 1) == 1))
        and not any(data.get(key) for key in (
            "tools", "tool_choice", "functions", "function_call", "silent_model",
        ))
        and _request_has_no_retry_or_fallback_override(data)
    )


def _request_has_no_retry_or_fallback_override(data: dict) -> bool:
    """Reject request-level attempts to override the proxy's zero retry/fallback policy."""
    if "num_retries" in data:
        retries = data["num_retries"]
        if retries is not None and (type(retries) is not int or retries != 0):
            return False
    for key in ("fallbacks", "context_window_fallbacks", "content_policy_fallbacks"):
        if key not in data:
            continue
        value = data[key]
        if value is not None and not (type(value) is list and not value):
            return False
    return True


def _is_pinned_router_fallback_wrapper(value, fallback_base) -> bool:
    value_type = type(value)
    return (
        isinstance(value, fallback_base)
        and value_type.__module__ == "litellm.router"
        and value_type.__qualname__
        == "Router._acompletion_streaming_iterator.<locals>.FallbackStreamWrapper"
        and value_type.__bases__ == (fallback_base,)
    )


def _router_method_has_pinned_shape(method) -> bool:
    if (
        not inspect.iscoroutinefunction(method)
        or getattr(method, "__wrapped__", None) is not None
        or getattr(method, "__module__", None) != "litellm.router"
        or getattr(method, "__qualname__", None) != "Router._acompletion_streaming_iterator"
    ):
        return False
    try:
        source_file = inspect.getsourcefile(method)
        normalized_source = source_file.replace("\\", "/") if isinstance(source_file, str) else ""
        if normalized_source.split("/")[-2:] != ["litellm", "router.py"]:
            return False
        parameters = list(inspect.signature(method).parameters.values())
    except (OSError, TypeError, ValueError):
        return False
    expected_names = ("self", "model_response", "messages", "initial_kwargs", "deployment_slot")
    if tuple(parameter.name for parameter in parameters) != expected_names:
        return False
    if any(parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD for parameter in parameters):
        return False
    return parameters[-1].default is None and all(
        parameter.default is inspect.Parameter.empty for parameter in parameters[:-1]
    )



def _parser_method_has_pinned_shape(method, module: str, qualname: str, source_tail, names, *, coroutine=None):
    if (
        getattr(method, "__module__", None) != module
        or getattr(method, "__qualname__", None) != qualname
        or getattr(method, "__wrapped__", None) is not None
        or (coroutine is not None and inspect.iscoroutinefunction(method) is not coroutine)
    ):
        return False
    try:
        source_file = inspect.getsourcefile(method)
        normalized_source = source_file.replace("\\", "/") if isinstance(source_file, str) else ""
        if normalized_source.split("/")[-len(source_tail):] != list(source_tail):
            return False
        parameters = list(inspect.signature(method).parameters.values())
    except (OSError, TypeError, ValueError):
        return False
    return (
        tuple(parameter.name for parameter in parameters) == tuple(names)
        and all(parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for parameter in parameters)
        and all(parameter.default is inspect.Parameter.empty for parameter in parameters)
    )


def _parser_invalid(parser) -> bool:
    return bool(getattr(parser, _PARSER_INVALID_ATTR, True))


def _raw_usage_only_event(chunk) -> bool:
    return (
        isinstance(chunk, dict)
        and not chunk.get("error")
        and isinstance(chunk.get("choices"), list)
        and not chunk["choices"]
        and isinstance(chunk.get("usage"), dict)
    )


def _record_raw_json_chunk(parser, chunk) -> None:
    if not isinstance(chunk, dict) or chunk.get("error"):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    raw_stop = bool(getattr(parser, _PARSER_STOP_ATTR, False))
    usage_seen = bool(getattr(parser, _PARSER_USAGE_ATTR, False))
    if not choices:
        usage = chunk.get("usage")
        if (
            not isinstance(usage, dict)
            or usage_seen
            or getattr(parser, _PARSER_ALLOW_USAGE_ATTR, False) is not True
        ):
            setattr(parser, _PARSER_INVALID_ATTR, True)
            return
        setattr(parser, _PARSER_USAGE_ATTR, True)
        return
    if len(choices) != 1 or not isinstance(choices[0], dict):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    choice = choices[0]
    if type(choice.get("index")) is not int or choice["index"] != 0:
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    if any(delta.get(name) for name in ("tool_calls", "function_call", "refusal")):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None:
        if (
            finish_reason != "stop"
            or raw_stop
            or any(delta.get(name) for name in ("content", "reasoning", "reasoning_content"))
        ):
            setattr(parser, _PARSER_INVALID_ATTR, True)
            return
        setattr(parser, _PARSER_STOP_ATTR, True)
        return
    if raw_stop:
        # Once the provider declared stop, only a single usage-only JSON event
        # or the exact SSE [DONE] record may follow.
        setattr(parser, _PARSER_INVALID_ATTR, True)


def _observe_sse_line(parser, line) -> None:
    if not isinstance(line, str):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return
    if not stripped.startswith("data:"):
        if (
            "[DONE]" in stripped
            or getattr(parser, _PARSER_STOP_ATTR, False)
        ):
            setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    payload = stripped[5:].strip()
    if payload == "[DONE]":
        setattr(parser, _PARSER_DONE_ATTR, True)
        if getattr(parser, _PARSER_STOP_ATTR, False) is not True:
            setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    if "[DONE]" in payload:
        # LiteLLM 1.105.0 searches for this substring, so reject ambiguous
        # content instead of letting a JSON string truncate the stream.
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    try:
        import json
        chunk = json.loads(payload)
    except Exception:
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    if not isinstance(chunk, dict):
        setattr(parser, _PARSER_INVALID_ATTR, True)
        return
    if getattr(parser, _PARSER_STOP_ATTR, False):
        if (
            not _raw_usage_only_event(chunk)
            or getattr(parser, _PARSER_ALLOW_USAGE_ATTR, False) is not True
        ):
            setattr(parser, _PARSER_INVALID_ATTR, True)


def _parser_is_guarded(parser) -> bool:
    return (
        _PARSER_PATCHED_CLASS is not None
        and type(parser) is _PARSER_PATCHED_CLASS
        and getattr(parser, _PARSER_PROVENANCE_ATTR, None) is _PARSER_PROVENANCE_TOKEN
        and _PARSER_PATCHED_CLASS.__dict__.get("__anext__") is _PARSER_PATCHED_ANEXT
    )


def _ensure_deepseek_parser_patch() -> bool:
    """Install a token-gated patch on the exact pinned native Chat parser only."""
    global _PARSER_PATCHED_CLASS, _PARSER_ORIGINAL_ANEXT, _PARSER_PATCHED_ANEXT
    try:
        if importlib.metadata.version("litellm") != "1.105.0":
            return False
        from litellm.llms.base_llm.base_model_iterator import BaseModelResponseIterator
        from litellm.llms.openai.chat.gpt_transformation import OpenAIChatCompletionStreamingHandler

        parser_class = OpenAIChatCompletionStreamingHandler
        if (
            parser_class.__module__ != "litellm.llms.openai.chat.gpt_transformation"
            or parser_class.__qualname__ != "OpenAIChatCompletionStreamingHandler"
            or parser_class.__bases__ != (BaseModelResponseIterator,)
        ):
            return False
        chunk_parser = parser_class.__dict__.get("chunk_parser")
        handle_line = BaseModelResponseIterator.__dict__.get("_handle_string_chunk")
        original_anext = BaseModelResponseIterator.__dict__.get("__anext__")
        if not (
            _parser_method_has_pinned_shape(
                chunk_parser,
                "litellm.llms.openai.chat.gpt_transformation",
                "OpenAIChatCompletionStreamingHandler.chunk_parser",
                ("litellm", "llms", "openai", "chat", "gpt_transformation.py"),
                ("self", "chunk"),
                coroutine=False,
            )
            and _parser_method_has_pinned_shape(
                handle_line,
                "litellm.llms.base_llm.base_model_iterator",
                "BaseModelResponseIterator._handle_string_chunk",
                ("litellm", "llms", "base_llm", "base_model_iterator.py"),
                ("self", "str_line"),
                coroutine=False,
            )
            and _parser_method_has_pinned_shape(
                original_anext,
                "litellm.llms.base_llm.base_model_iterator",
                "BaseModelResponseIterator.__anext__",
                ("litellm", "llms", "base_llm", "base_model_iterator.py"),
                ("self",),
                coroutine=True,
            )
        ):
            return False
        current = parser_class.__dict__.get("__anext__")
        if current is not None:
            marker = getattr(current, _PARSER_PATCH_MARKER, None)
            if marker is _PARSER_PROVENANCE_TOKEN:
                return (
                    _PARSER_PATCHED_CLASS is parser_class
                    and _PARSER_PATCHED_ANEXT is current
                    and _PARSER_ORIGINAL_ANEXT is original_anext
                )
            return False
        with _ROUTER_PATCH_LOCK:
            current = parser_class.__dict__.get("__anext__")
            if current is not None:
                return (
                    getattr(current, _PARSER_PATCH_MARKER, None) is _PARSER_PROVENANCE_TOKEN
                    and _PARSER_PATCHED_CLASS is parser_class
                    and _PARSER_PATCHED_ANEXT is current
                    and _PARSER_ORIGINAL_ANEXT is original_anext
                )

            @functools.wraps(original_anext)
            async def terminal_aware_anext(self):
                if _parser_is_guarded(self):
                    if _parser_invalid(self):
                        raise RuntimeError("T00_STREAM_TERMINAL_UNVERIFIED")
                    if getattr(self, _PARSER_DONE_ATTR, False):
                        if not getattr(self, _PARSER_CLOSED_ATTR, False):
                            await self.aclose()
                            setattr(self, _PARSER_CLOSED_ATTR, True)
                        raise StopAsyncIteration
                try:
                    return await original_anext(self)
                except StopAsyncIteration:
                    if _parser_is_guarded(self) and getattr(self, _PARSER_DONE_ATTR, False):
                        await self.aclose()
                    raise

            setattr(terminal_aware_anext, _PARSER_PATCH_MARKER, _PARSER_PROVENANCE_TOKEN)
            parser_class.__anext__ = terminal_aware_anext
            _PARSER_PATCHED_CLASS = parser_class
            _PARSER_ORIGINAL_ANEXT = original_anext
            _PARSER_PATCHED_ANEXT = terminal_aware_anext
        return True
    except Exception:
        return False


def _attach_parser_provenance(source, request_data) -> bool:
    if not _ensure_deepseek_parser_patch():
        return False
    parser = getattr(source, "completion_stream", None)
    if not _is_parser_exact_type(parser):
        return False
    namespace = getattr(parser, "__dict__", None)
    http_response = getattr(parser, "http_response", None)
    if (
        not isinstance(namespace, dict)
        or _PARSER_PROVENANCE_ATTR in namespace
        or http_response is None
        or not callable(getattr(http_response, "aclose", None))
    ):
        return False
    try:
        parser._byok_original_chunk_parser = parser.chunk_parser
        parser._byok_original_handle_line = parser._handle_string_chunk
        parser._byok_parser_state = True
        setattr(parser, _PARSER_PROVENANCE_ATTR, _PARSER_PROVENANCE_TOKEN)
        setattr(parser, _PARSER_STOP_ATTR, False)
        setattr(parser, _PARSER_DONE_ATTR, False)
        setattr(parser, _PARSER_INVALID_ATTR, False)
        setattr(parser, _PARSER_USAGE_ATTR, False)
        stream_options = request_data.get("stream_options") if isinstance(request_data, dict) else None
        allow_usage = isinstance(stream_options, dict) and stream_options.get("include_usage") is True
        setattr(parser, _PARSER_ALLOW_USAGE_ATTR, allow_usage)
        setattr(parser, _PARSER_CLOSED_ATTR, False)

        original_chunk_parser = parser._byok_original_chunk_parser
        original_handle_line = parser._byok_original_handle_line

        def guarded_chunk_parser(chunk):
            if _parser_is_guarded(parser):
                _record_raw_json_chunk(parser, chunk)
                if _parser_invalid(parser):
                    raise RuntimeError("T00_STREAM_TERMINAL_UNVERIFIED")
            return original_chunk_parser(chunk)

        def guarded_handle_line(str_line):
            if _parser_is_guarded(parser):
                _observe_sse_line(parser, str_line)
                if _parser_invalid(parser):
                    raise RuntimeError("T00_STREAM_TERMINAL_UNVERIFIED")
            return original_handle_line(str_line=str_line)

        parser.chunk_parser = guarded_chunk_parser
        parser._handle_string_chunk = guarded_handle_line
        return True
    except Exception:
        _clear_parser_provenance(parser)
        return False


def _is_parser_exact_type(parser) -> bool:
    return (
        _PARSER_PATCHED_CLASS is not None
        and type(parser) is _PARSER_PATCHED_CLASS
    )


def _clear_parser_provenance(source_or_parser) -> None:
    parser = source_or_parser
    if not _is_parser_exact_type(parser):
        parser = getattr(source_or_parser, "completion_stream", None)
    if not _is_parser_exact_type(parser):
        return
    namespace = getattr(parser, "__dict__", {})
    for name in (
        "chunk_parser", "_handle_string_chunk",
        "_byok_original_chunk_parser", "_byok_original_handle_line",
        "_byok_parser_state", _PARSER_PROVENANCE_ATTR, _PARSER_STOP_ATTR,
        _PARSER_DONE_ATTR, _PARSER_INVALID_ATTR, _PARSER_USAGE_ATTR,
        _PARSER_ALLOW_USAGE_ATTR, _PARSER_CLOSED_ATTR,
    ):
        namespace.pop(name, None)


def _ensure_router_provenance_patch() -> bool:
    """Pin and patch only LiteLLM 1.105.0's router wrapper construction boundary."""
    global _ROUTER_PATCHED_CLASS, _ROUTER_PATCHED_METHOD
    try:
        if importlib.metadata.version("litellm") != "1.105.0":
            return False
        from litellm.router import FallbackAwareStreamWrapper, Router
        from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper

        if not _ensure_deepseek_parser_patch():
            return False
        method = Router._acompletion_streaming_iterator
        marker = getattr(method, _ROUTER_PATCH_MARKER, None)
        if marker is _ROUTER_PROVENANCE_TOKEN:
            return _ROUTER_PATCHED_CLASS is Router and _ROUTER_PATCHED_METHOD is method
        if marker is not None:
            return False
        if not _router_method_has_pinned_shape(method):
            return False

        with _ROUTER_PATCH_LOCK:
            method = Router._acompletion_streaming_iterator
            marker = getattr(method, _ROUTER_PATCH_MARKER, None)
            if marker is _ROUTER_PROVENANCE_TOKEN:
                return _ROUTER_PATCHED_CLASS is Router and _ROUTER_PATCHED_METHOD is method
            if marker is not None or not _router_method_has_pinned_shape(method):
                return False
            original = method

            @functools.wraps(original)
            async def preserve_raw_source(
                self, model_response, messages, initial_kwargs, deployment_slot=None,
            ):
                exact_route = (
                    type(model_response) is CustomStreamWrapper
                    and getattr(model_response, "custom_llm_provider", None) == "deepseek"
                    and isinstance(initial_kwargs, dict)
                    and initial_kwargs.get("model") == TERMINAL_STREAM_MODEL
                    and initial_kwargs.get("stream") is True
                    and _request_has_no_retry_or_fallback_override(initial_kwargs)
                )
                parser_attached = _attach_parser_provenance(model_response, initial_kwargs) if exact_route else False
                try:
                    wrapped = await original(
                        self, model_response, messages, initial_kwargs, deployment_slot,
                    )
                except BaseException:
                    if parser_attached:
                        _clear_parser_provenance(model_response)
                    raise
                if (
                    exact_route
                    and parser_attached
                    and _is_pinned_router_fallback_wrapper(wrapped, FallbackAwareStreamWrapper)
                ):
                    try:
                        setattr(wrapped, _ROUTER_RAW_SOURCE_ATTR, model_response)
                        setattr(wrapped, _ROUTER_PROVENANCE_TOKEN_ATTR, _ROUTER_PROVENANCE_TOKEN)
                    except Exception:
                        # The streaming hook will fail closed if provenance is
                        # unavailable; never replace the Router's response.
                        _clear_parser_provenance(model_response)
                elif parser_attached:
                    _clear_parser_provenance(model_response)
                return wrapped

            setattr(preserve_raw_source, _ROUTER_PATCH_MARKER, _ROUTER_PROVENANCE_TOKEN)
            Router._acompletion_streaming_iterator = preserve_raw_source
            _ROUTER_PATCHED_CLASS = Router
            _ROUTER_PATCHED_METHOD = preserve_raw_source
        return True
    except Exception:
        return False


def _finish_reason(chunk):
    choices = getattr(chunk, "choices", None) or []
    if len(choices) > 1:
        return "__MULTIPLE_CHOICES__"
    return getattr(choices[0], "finish_reason", None) if choices else None


def _usage_only(chunk):
    choices = getattr(chunk, "choices", None) or []
    if getattr(chunk, "usage", None) is None:
        return False
    if not choices:
        return True
    if len(choices) != 1:
        return False
    delta = getattr(choices[0], "delta", None)
    return not any((
        getattr(delta, "content", None),
        getattr(delta, "tool_calls", None),
        getattr(delta, "refusal", None),
        getattr(delta, "function_call", None),
    ))


def _clear_router_provenance(value) -> None:
    if value is None:
        return
    for name in (_ROUTER_RAW_SOURCE_ATTR, _ROUTER_PROVENANCE_TOKEN_ATTR):
        try:
            delattr(value, name)
        except Exception:
            pass


async def _aclose_stream(value):
    for name in ("aclose", "close"):
        closer = getattr(value, name, None)
        if closer is None:
            continue
        result = closer()
        if inspect.isawaitable(result):
            await result
        return


class ProviderKeyGuard(CustomLogger):
    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type: str,
        **_kwargs,
    ):
        normalized_call_type = call_type.strip().lower() if isinstance(call_type, str) else call_type
        if normalized_call_type not in BYOK_CALL_TYPES:
            return data

        provider_key = data.get("api_key")
        if not isinstance(provider_key, str) or not provider_key.strip():
            raise HTTPException(status_code=400, detail={"code": "BYOK_PROVIDER_KEY_REQUIRED"})

        if _stream_requested(data.get("stream")):
            extra_denies = _extra_denied_streaming_call_types()
            if normalized_call_type in extra_denies:
                code = (
                    "T00_CHAT_STREAMING_DISABLED"
                    if normalized_call_type in ALWAYS_DENIED_STREAMING_CALL_TYPES
                    else "T00_STREAMING_DISABLED"
                )
                raise HTTPException(status_code=400, detail={"code": code})
            # Preserve the existing native Responses/Messages stream contracts.
            # Chat Completions remains denied unless this request uses the one
            # exact route whose raw upstream terminal is verified below.
            if normalized_call_type in ALWAYS_DENIED_STREAMING_CALL_TYPES:
                terminal_allowed = _terminal_stream_allowlisted(data, normalized_call_type)
                if not terminal_allowed or not _ensure_router_provenance_patch():
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "T00_CHAT_STREAMING_DISABLED"},
                    )
        return data

    async def async_post_call_streaming_iterator_hook(
        self, response, user_api_key_dict, request_data,
    ):
        model = request_data.get("model") if isinstance(request_data, dict) else None
        if model != TERMINAL_STREAM_MODEL or not _stream_requested(
            request_data.get("stream") if isinstance(request_data, dict) else None,
        ):
            async for chunk in response:
                yield chunk
            return

        router_source = getattr(response, "_source", None)
        raw_source = None
        version = "unavailable"
        reason = None
        try:
            version = importlib.metadata.version("litellm")
        except Exception:
            reason = "version_unavailable"
        if reason is None and version != "1.105.0":
            reason = "version_mismatch"

        boundary_type = fallback_base = custom_stream_type = parser_type = None
        if reason is None:
            try:
                # LiteLLM 1.105.0's Proxy hook receives this boundary. Router
                # then wraps the provider stream in its local fallback wrapper.
                from litellm.proxy.utils import _UpstreamStreamBoundary
                from litellm.router import FallbackAwareStreamWrapper
                from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
                from litellm.llms.openai.chat.gpt_transformation import OpenAIChatCompletionStreamingHandler

                boundary_type = _UpstreamStreamBoundary
                fallback_base = FallbackAwareStreamWrapper
                custom_stream_type = CustomStreamWrapper
                parser_type = OpenAIChatCompletionStreamingHandler
            except Exception:
                reason = "wrapper_types_unavailable"

        if reason is None and type(response) is not boundary_type:
            reason = "boundary_type_mismatch"
        elif reason is None and not _is_pinned_router_fallback_wrapper(router_source, fallback_base):
            reason = "router_wrapper_type_mismatch"
        elif reason is None:
            if (
                getattr(router_source, _ROUTER_PROVENANCE_TOKEN_ATTR, None)
                is not _ROUTER_PROVENANCE_TOKEN
                or not hasattr(router_source, _ROUTER_RAW_SOURCE_ATTR)
            ):
                reason = "router_provenance_missing"
            else:
                raw_source = getattr(router_source, _ROUTER_RAW_SOURCE_ATTR, None)
                if type(raw_source) is not custom_stream_type:
                    reason = "raw_source_type_mismatch"
                else:
                    parser = getattr(raw_source, "completion_stream", None)
                    if (
                        parser_type is None
                        or type(parser) is not parser_type
                        or not _parser_is_guarded(parser)
                        or _parser_invalid(parser)
                    ):
                        reason = "parser_provenance_missing"
                    try:
                        if (
                            raw_source.custom_llm_provider != "deepseek"
                            or router_source.custom_llm_provider != "deepseek"
                        ):
                            reason = "source_provider_mismatch"
                    except Exception:
                        reason = "source_provider_unavailable"
                    if reason is None and getattr(router_source, "fallback_headers_adopted", None) is not False:
                        reason = "fallback_activated"

        if reason is not None:
            try:
                await _aclose_stream(response)
            except Exception:
                pass
            finally:
                _clear_parser_provenance(raw_source)
            _clear_router_provenance(router_source)
            raise HTTPException(
                status_code=502,
                detail=_terminal_error_detail(reason, response, router_source, version),
            ) from None

        parser = raw_source.completion_stream
        tail = []
        saw_terminal = False
        usage_seen = False
        closed = False
        try:
            async for chunk in response:
                if _parser_invalid(parser):
                    raise HTTPException(
                        status_code=502,
                        detail=_terminal_error_detail("raw_stream_invalid", response, router_source, version),
                    )
                if getattr(router_source, "fallback_headers_adopted", None) is not False:
                    raise HTTPException(
                        status_code=502,
                        detail=_terminal_error_detail(
                            "fallback_activated", response, router_source, version,
                        ),
                    )
                raw_reason = raw_source.received_finish_reason
                verified_json_stop = getattr(parser, _PARSER_STOP_ATTR, False) is True
                reason = _finish_reason(chunk)
                if reason is not None:
                    if (
                        reason != "stop"
                        or raw_reason != "stop"
                        or not verified_json_stop
                        or saw_terminal
                    ):
                        raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                    saw_terminal = True
                    tail.append(chunk)
                    continue

                if _usage_only(chunk):
                    if usage_seen:
                        raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                    usage_seen = True
                    if saw_terminal or (raw_reason == "stop" and verified_json_stop):
                        tail.append(chunk)
                    else:
                        yield chunk
                    continue

                # Some provider parsers expose the raw reason only on the source
                # while omitting it from the normalized frame. Cache that frame
                # as the terminal candidate and release it only after clean EOF.
                if raw_reason == "stop" and verified_json_stop and not saw_terminal:
                    saw_terminal = True
                    tail.append(chunk)
                    continue

                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    if any(getattr(delta, name, None) for name in (
                        "tool_calls", "function_call", "refusal",
                    )):
                        raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                if saw_terminal:
                    raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                yield chunk

            if (
                not saw_terminal
                or raw_source.received_finish_reason != "stop"
                or getattr(parser, _PARSER_STOP_ATTR, False) is not True
                or _parser_invalid(parser)
                or getattr(router_source, "fallback_headers_adopted", None) is not False
                or getattr(response, "failure", None) is not None
                or getattr(raw_source, "failure", None) is not None
            ):
                raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
            # Close the upstream before releasing any cached terminal; a cleanup
            # error must never occur after the client observes completion.
            await _aclose_stream(response)
            closed = True
            for chunk in tail:
                yield chunk
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=502, detail=_TERMINAL_ERROR) from None
        finally:
            if not closed:
                try:
                    await _aclose_stream(response)
                except Exception:
                    pass
            # Drop the retained parser and provider iterator once verification is
            # over so client disconnects and completed streams don't extend lifetime.
            _clear_parser_provenance(raw_source)
            _clear_router_provenance(router_source)


proxy_handler_instance = ProviderKeyGuard()
