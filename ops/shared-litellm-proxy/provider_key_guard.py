"""Small pre-route guard for explicit per-request BYOK credentials.

The master key, project virtual keys, and provider keys have separate roles.
This callback rejects BYOK requests without a non-empty request-scoped provider
key before LiteLLM selects an upstream deployment. It also keeps the Chat
streaming route disabled while the v1.105.0 EOF compatibility risk remains:
LiteLLM (v1.104.2 and v1.105.0 images) synthesises ``finish_reason=stop`` +
``[DONE]`` when a Chat upstream closes without any terminal marker, so a
truncated stream is indistinguishable from a complete one. Chat streaming
is therefore fail-closed here -- always, not only when an operator happens
to set an environment variable correctly.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger


BYOK_CALL_TYPES = frozenset({"acompletion", "completion", "aresponses", "anthropic_messages"})

# Chat Completions streaming can never be re-enabled by configuration in
# this deployment: upstream EOF without a terminal would surface as a
# false success. BYOK_DENY_STREAMING_CALL_TYPES may only *add* denied
# call types (e.g. during a future Responses/Messages incident); an
# empty, missing, misscased, or Chat-omitting value must not reopen Chat.
ALWAYS_DENIED_STREAMING_CALL_TYPES = frozenset({"acompletion", "completion"})

_STREAM_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


def _stream_requested(value: object) -> bool:
    """Whether a raw pre-validation ``stream`` value asks for streaming.

    The hook runs on the request dict before LiteLLM's typed parsing
    coerces values, so a JSON ``"true"``/``1`` that the parser would
    turn into ``True`` must be treated as streaming here, not waved
    through because it is not the ``True`` singleton.
    """
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _STREAM_TRUE_STRINGS
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 1
    return False


def _denied_streaming_call_types() -> frozenset[str]:
    configured = os.environ.get("BYOK_DENY_STREAMING_CALL_TYPES", "")
    extra = {item.strip().lower() for item in configured.split(",") if item.strip()}
    return ALWAYS_DENIED_STREAMING_CALL_TYPES | extra


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
            raise HTTPException(
                status_code=400,
                detail={"code": "BYOK_PROVIDER_KEY_REQUIRED"},
            )

        if _stream_requested(data.get("stream")) and normalized_call_type in _denied_streaming_call_types():
            raise HTTPException(
                status_code=400,
                detail={"code": "T00_CHAT_STREAMING_DISABLED"},
            )

        return data


proxy_handler_instance = ProviderKeyGuard()
