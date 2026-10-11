"""Small pre-route guard for explicit per-request BYOK credentials.

The master key, project virtual keys, and provider keys have separate roles.
This callback rejects BYOK requests without a non-empty request-scoped provider
key before LiteLLM selects an upstream deployment. It also keeps the Chat
streaming route disabled while the v1.105.0 EOF compatibility risk remains.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger


BYOK_CALL_TYPES = frozenset({"acompletion", "aresponses", "anthropic_messages"})


class ProviderKeyGuard(CustomLogger):
    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type: str,
        **_kwargs,
    ):
        if call_type not in BYOK_CALL_TYPES:
            return data

        provider_key = data.get("api_key")
        if not isinstance(provider_key, str) or not provider_key.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "BYOK_PROVIDER_KEY_REQUIRED"},
            )

        denied_streaming_calls = {
            item.strip()
            for item in os.environ.get("T00_DENY_STREAMING_CALL_TYPES", "acompletion").split(",")
            if item.strip()
        }
        if data.get("stream") is True and call_type in denied_streaming_calls:
            raise HTTPException(
                status_code=400,
                detail={"code": "T00_CHAT_STREAMING_DISABLED"},
            )

        return data


proxy_handler_instance = ProviderKeyGuard()
