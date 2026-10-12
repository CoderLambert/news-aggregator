"""Versioned model presets; endpoint and proxy aliases stay server-owned."""

from __future__ import annotations

from copy import deepcopy


MODEL_CATALOG_VERSION = '2026-10-12.1'
MODEL_CATALOG_SOURCES = {
    'deepseek': 'https://api-docs.deepseek.com/api/list-models/',
}

# Only this preset has a route in the current NewsHub LiteLLM project allowlist.
# Provider-declared limits are metadata, not proof of runtime compatibility.
MODEL_PRESETS = (
    {
        'catalog_model_id': 'deepseek-flash',
        'provider_id': 'deepseek',
        'model_id': 'deepseek-flash',
        'display_name': 'DeepSeek V4.1 Flash',
        'context_window_tokens': 1_048_576,
        'max_output_tokens': 393_216,
        'proxy_model_alias': 'news.deepseek-flash',
        'catalog_version': MODEL_CATALOG_VERSION,
        'source_url': MODEL_CATALOG_SOURCES['deepseek'],
        'provider_claims': {
            'text': True,
            'tools': True,
            'structured_output': True,
            'thinking': True,
            'stream': True,
            'input_modalities': ['text', 'image'],
            'output_modalities': ['text'],
        },
    },
)

PRESETS_BY_ID = {item['catalog_model_id']: item for item in MODEL_PRESETS}


def get_model_preset(catalog_model_id: str, provider_id: str):
    preset = PRESETS_BY_ID.get(catalog_model_id)
    if preset is None or preset['provider_id'] != provider_id:
        return None
    return deepcopy(preset)


def find_model_preset(model_id: str, provider_id: str):
    preset = next(
        (
            item for item in MODEL_PRESETS
            if item['provider_id'] == provider_id and item['model_id'] == model_id
        ),
        None,
    )
    return deepcopy(preset) if preset is not None else None


def model_catalog(provider_id: str | None = None):
    return [
        {
            key: deepcopy(value)
            for key, value in preset.items()
            if key != 'proxy_model_alias'
        }
        for preset in MODEL_PRESETS
        if provider_id is None or preset['provider_id'] == provider_id
    ]
