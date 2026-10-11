"""Test-only wrapper that records provider-key match labels, never key values."""

from __future__ import annotations

import hashlib
import json
import os

from byok_gateway_policy import ProviderKeyGuard


class TestProviderKeyGuard(ProviderKeyGuard):
    async def async_pre_call_hook(
        self,
        user_api_key_dict,
        cache,
        data: dict,
        call_type: str,
        **kwargs,
    ):
        result = await super().async_pre_call_hook(
            user_api_key_dict=user_api_key_dict,
            cache=cache,
            data=data,
            call_type=call_type,
            **kwargs,
        )
        provider_key = data.get("api_key")
        expected_hashes = json.loads(os.environ.get("T00G_TEST_PROVIDER_KEY_HASHES", "{}"))
        matched_label = "unmatched"
        if isinstance(provider_key, str) and isinstance(expected_hashes, dict):
            provider_hash = hashlib.sha256(provider_key.encode("utf-8")).hexdigest()
            matched_label = next(
                (label for label, expected_hash in expected_hashes.items() if expected_hash == provider_hash),
                matched_label,
            )
        print(f"T00G_TEST_PROVIDER_KEY_MATCH label={matched_label}", flush=True)
        return result


proxy_handler_instance = TestProviderKeyGuard()
