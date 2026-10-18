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
TERMINAL_STREAM_MODEL = "deepseek/deepseek-chat"
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


def _ensure_router_provenance_patch() -> bool:
    """Pin and patch only LiteLLM 1.105.0's router wrapper construction boundary."""
    global _ROUTER_PATCHED_CLASS, _ROUTER_PATCHED_METHOD
    try:
        if importlib.metadata.version("litellm") != "1.105.0":
            return False
        from litellm.router import FallbackAwareStreamWrapper, Router
        from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper

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
                wrapped = await original(
                    self, model_response, messages, initial_kwargs, deployment_slot,
                )
                if (
                    type(model_response) is CustomStreamWrapper
                    and getattr(model_response, "custom_llm_provider", None) == "deepseek"
                    and isinstance(initial_kwargs, dict)
                    and initial_kwargs.get("model") == TERMINAL_STREAM_MODEL
                    and initial_kwargs.get("stream") is True
                    and _request_has_no_retry_or_fallback_override(initial_kwargs)
                    and _is_pinned_router_fallback_wrapper(wrapped, FallbackAwareStreamWrapper)
                ):
                    try:
                        setattr(wrapped, _ROUTER_RAW_SOURCE_ATTR, model_response)
                        setattr(wrapped, _ROUTER_PROVENANCE_TOKEN_ATTR, _ROUTER_PROVENANCE_TOKEN)
                    except Exception:
                        # The streaming hook will fail closed if provenance is
                        # unavailable; never replace the Router's response.
                        pass
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

        boundary_type = fallback_base = custom_stream_type = None
        if reason is None:
            try:
                # LiteLLM 1.105.0's Proxy hook receives this boundary. Router
                # then wraps the provider stream in its local fallback wrapper.
                from litellm.proxy.utils import _UpstreamStreamBoundary
                from litellm.router import FallbackAwareStreamWrapper
                from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper

                boundary_type = _UpstreamStreamBoundary
                fallback_base = FallbackAwareStreamWrapper
                custom_stream_type = CustomStreamWrapper
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
                _clear_router_provenance(router_source)
            raise HTTPException(
                status_code=502,
                detail=_terminal_error_detail(reason, response, router_source, version),
            ) from None

        tail = []
        saw_terminal = False
        usage_seen = False
        closed = False
        try:
            async for chunk in response:
                if getattr(router_source, "fallback_headers_adopted", None) is not False:
                    raise HTTPException(
                        status_code=502,
                        detail=_terminal_error_detail(
                            "fallback_activated", response, router_source, version,
                        ),
                    )
                raw_reason = raw_source.received_finish_reason
                reason = _finish_reason(chunk)
                if reason is not None:
                    if reason != "stop" or raw_reason != "stop" or saw_terminal:
                        raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                    saw_terminal = True
                    tail.append(chunk)
                    continue

                # Some provider parsers expose the raw reason only on the source
                # while omitting it from the normalized frame. Cache that frame
                # as the terminal candidate and release it only after clean EOF.
                if raw_reason == "stop" and not saw_terminal:
                    saw_terminal = True
                    tail.append(chunk)
                    continue

                if _usage_only(chunk):
                    if usage_seen:
                        raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                    usage_seen = True
                    if saw_terminal:
                        tail.append(chunk)
                    else:
                        yield chunk
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
            # Drop the retained provider iterator once verification is over so
            # client disconnects and completed streams don't extend its lifetime.
            _clear_router_provenance(router_source)


proxy_handler_instance = ProviderKeyGuard()
