"""Trusted T02 model identifiers and approved LiteLLM Proxy routes.

A user-supplied model ID is inert metadata unless it matches a server-owned
preset on the connection's trusted provider/endpoint. No dynamic alias creation.
"""
import re

from api.services.ai_gateway import ARTICLE_CHAT_SUPPORTED_ALIAS, PROVIDER_SPECS
from api.services.ai_registry import get_profile

CATALOG_VERSION = '2026-10-19.1'
_MODEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$')
# The provider's deployed wildcard is deepseek/*; the same alias must exist
# in the isolated synthetic Proxy before process-level T02 verification.
_PRESETS = {
    ('deepseek', 'deepseek-chat'): {
        'display_name': 'DeepSeek Chat',
        'proxy_alias': 'deepseek/deepseek-chat',
    },
    ('deepseek', 'deepseek-flash'): {
        'display_name': 'DeepSeek Flash',
        'proxy_alias': 'deepseek/deepseek-flash',
    },
}


def normalize_model_id(provider_id, raw):
    if not isinstance(raw, str) or raw != raw.strip() or not _MODEL_RE.fullmatch(raw):
        return None
    if '://' in raw or '..' in raw or '//' in raw or raw.lower().startswith(('sk-', 'ark-', 'aiza')):
        return None
    spec = PROVIDER_SPECS.get(provider_id)
    if spec is None:
        return None
    prefix = spec['route_prefix'] + '/'
    normalized = raw[len(prefix):] if raw.startswith(prefix) else raw
    return normalized if normalized and _MODEL_RE.fullmatch(normalized) else None


def get_trusted_preset(connection, model_id):
    """Versioned connection profile + exact model allowlist, not a user URL."""
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if profile is None or profile['version'] != connection.endpoint_profile_version:
        return None
    return _PRESETS.get((connection.provider_id, model_id))


def catalog_for(connection):
    return [{'model_id': model_id, 'display_name': preset['display_name'],
             'catalog_version': CATALOG_VERSION, 'context_window_tokens': None,
             'text': 'unknown', 'tools': 'unknown'}
            for (provider, model_id), preset in _PRESETS.items()
            if provider == connection.provider_id and get_trusted_preset(connection, model_id)]


def supports_article_chat(connection, model_id):
    """T04 is available only on a trusted route with verified stream terminal semantics."""
    preset = get_trusted_preset(connection, model_id)
    return bool(preset and preset.get('proxy_alias') == ARTICLE_CHAT_SUPPORTED_ALIAS)
