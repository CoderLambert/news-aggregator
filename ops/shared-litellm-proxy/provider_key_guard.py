"""Fail-closed request-scoped BYOK key guard and verified T04 stream boundary.

Only the exact pinned DeepSeek Chat route is stream-enabled. Its whole-iterator
hook checks the original LiteLLM 1.105.0 upstream wrapper terminal before
releasing the terminal chunk; every unknown route/wrapper/version fails closed.
"""
from __future__ import annotations

import importlib.metadata
import inspect
import os

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
        and not any(data.get(key) for key in ("tools", "tool_choice", "functions", "function_call"))
    )


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
            if (
                normalized_call_type in ALWAYS_DENIED_STREAMING_CALL_TYPES
                and not _terminal_stream_allowlisted(data, normalized_call_type)
            ):
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

        try:
            if importlib.metadata.version("litellm") != "1.105.0":
                raise RuntimeError("unsupported LiteLLM version")
            # LiteLLM 1.105.0 passes this exact boundary into the whole-stream
            # hook. Never trust duck-typed wrappers or a different provider.
            from litellm.proxy.utils import _UpstreamStreamBoundary
            from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper

            source = getattr(response, "_source", None)
            if (
                type(response) is not _UpstreamStreamBoundary
                or type(source) is not CustomStreamWrapper
                or source.custom_llm_provider != "deepseek"
            ):
                raise RuntimeError("unknown upstream stream")
        except Exception:
            try:
                await _aclose_stream(response)
            except Exception:
                pass
            raise HTTPException(status_code=502, detail=_TERMINAL_ERROR) from None

        tail = []
        saw_terminal = False
        usage_seen = False
        closed = False
        try:
            async for chunk in response:
                reason = _finish_reason(chunk)
                if reason is not None:
                    if (
                        reason != "stop"
                        or source.received_finish_reason != "stop"
                        or saw_terminal
                    ):
                        raise HTTPException(status_code=502, detail=_TERMINAL_ERROR)
                    saw_terminal = True
                    tail.append(chunk)
                    continue

                # Some provider parsers expose the raw reason only on the source
                # while omitting it from the normalized frame. Treat that exact
                # source transition as terminal and hold the frame until EOF.
                if source.received_finish_reason == "stop" and not saw_terminal:
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
                or source.received_finish_reason != "stop"
                or getattr(response, "failure", None) is not None
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


proxy_handler_instance = ProviderKeyGuard()
