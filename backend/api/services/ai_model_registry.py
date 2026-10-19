"""Trusted T02 model identifiers and approved LiteLLM Proxy routes.

Presets are selection suggestions. Manual IDs may be explicitly probed only
through the connection's versioned server-owned provider/region route. Saving
an ID never proves a capability or authorizes business inference.
"""
import re

from api.services.ai_gateway import ARTICLE_CHAT_SUPPORTED_ALIAS, PROVIDER_SPECS
from api.services.ai_registry import profile_route_prefix

CATALOG_VERSION = '2026-10-20.2'
_MODEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$')
_BARE_MODEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,159}$')
# Exact approved aliases behind the existing Proxy. A catalog entry never
# proves a capability; owner/version-bound explicit probe receipts do that.
_PRESETS = {
    ('anthropic', 'claude-haiku-5-5'): {
        'display_name': 'Claude Haiku 5.5',
        'proxy_alias': 'anthropic/claude-haiku-5-5',
    },
    ('openai', 'gpt-5.4-mini'): {
        'display_name': 'GPT-5.4 mini',
        'proxy_alias': 'openai/gpt-5.4-mini',
    },
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
    prefix = profile_route_prefix(connection)
    if prefix is None:
        return None
    preset = _PRESETS.get((connection.provider_id, model_id))
    if preset is None:
        return None
    original_prefix = PROVIDER_SPECS[connection.provider_id]['route_prefix'] + '/'
    return {**preset, 'proxy_alias': prefix + '/' + preset['proxy_alias'].removeprefix(original_prefix)}


def get_trusted_route(connection, model_id):
    """A model name cannot select another provider, region, URL or parameter."""
    if type(model_id) is not str:
        return None
    preset = get_trusted_preset(connection, model_id)
    if preset is not None:
        return preset
    prefix = profile_route_prefix(connection)
    if prefix is None or normalize_model_id(connection.provider_id, model_id) != model_id:
        return None
    if (connection.provider_id in {'glm', 'qwen', 'kimi'}
            and connection.endpoint_profile == connection.provider_id + '_default'):
        # These old identities did not pin a region. Keep their saved Key
        # inert; users must explicitly create a fixed regional connection.
        return None
    # OpenRouter uses provider/model names inside its own fixed route. Other
    # trusted providers accept a bare ID, not nested router directives.
    if connection.provider_id != 'openrouter' and not _BARE_MODEL_RE.fullmatch(model_id):
        return None
    return {'display_name': model_id[:64], 'proxy_alias': prefix + '/' + model_id}


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
