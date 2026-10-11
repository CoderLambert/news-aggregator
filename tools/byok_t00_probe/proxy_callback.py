"""Synthetic T00 admission guard loaded by the pinned LiteLLM Proxy fixture.

This callback is intentionally tiny: it reads only the request body's top-level
api_key and stream values, never logs credential data, and never calls a
provider. It is not a production integration.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger


BYOK_CALL_TYPES = frozenset({"acompletion", "aresponses", "anthropic_messages"})


class T00AdmissionGuard(CustomLogger):
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

        deny_streaming = {
            item.strip()
            for item in os.environ.get("T00_DENY_STREAMING_CALL_TYPES", "").split(",")
            if item.strip()
        }
        if data.get("stream") is True and call_type in deny_streaming:
            raise HTTPException(
                status_code=400,
                detail={"code": "T00_STREAMING_DISABLED"},
            )
        return data


proxy_handler_instance = T00AdmissionGuard()
