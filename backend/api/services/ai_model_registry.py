"""Trusted T02 model identifiers and approved LiteLLM Proxy routes.

Presets are selection suggestions. Manual IDs may be explicitly probed only
through the connection's versioned server-owned provider/region route. Saving
an ID never proves a capability or authorizes business inference.
"""
import re

from api.services.ai_gateway import ARTICLE_CHAT_SUPPORTED_ALIAS, PROVIDER_SPECS
from api.services.ai_registry import profile_route_prefix
from api.services.ai_endpoint_profiles import ADAPTER_VERSION, SERVICE_PRESETS, valid_upstream_model_id
from api.services.ai_responses_protocol import uses_responses_protocol, RESPONSES_PROTOCOL
from api.services.ai_messages_protocol import uses_messages_protocol, MESSAGES_PROTOCOL

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


def normalize_model_id(provider_id, raw, *, connection=None):
    if not valid_upstream_model_id(raw):
        return None
    spec = PROVIDER_SPECS.get(provider_id)
    if spec is None and provider_id not in SERVICE_PRESETS:
        return None
    compatible = connection is not None and bool(getattr(connection, 'endpoint_policy_digest', ''))
    prefix = spec['route_prefix'] + '/' if spec and not compatible else None
    normalized = raw[len(prefix):] if prefix and raw.startswith(prefix) else raw
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


def _trusted_model_route(connection, model_id):
    """A model name cannot select another provider, region, URL or parameter."""
    if type(model_id) is not str:
        return None
    preset = get_trusted_preset(connection, model_id)
    if preset is not None:
        return preset
    prefix = profile_route_prefix(connection)
    if prefix is None or normalize_model_id(connection.provider_id, model_id, connection=connection) != model_id:
        return None
    if (connection.provider_id in {'glm', 'qwen', 'kimi'}
            and connection.endpoint_profile == connection.provider_id + '_default'):
        # These old identities did not pin a region. Keep their saved Key
        # inert; users must explicitly create a fixed regional connection.
        return None
    if prefix.startswith('newshub/'):
        return {'display_name': model_id[:64], 'proxy_alias': prefix + '/' + model_id,
                'protocol_family': 'chat_completions_v1'}
    # OpenRouter uses provider/model names inside its own fixed route. Other
    # trusted providers accept a bare ID, not nested router directives.
    if connection.provider_id != 'openrouter' and not _BARE_MODEL_RE.fullmatch(model_id):
        return None
    return {'display_name': model_id[:64], 'proxy_alias': prefix + '/' + model_id}


def get_trusted_route(connection, model_id):
    route = _trusted_model_route(connection, model_id)
    if route is None:
        return None
    alias = route['proxy_alias']
    manifest = alias.startswith('newshub/')
    protocol = (RESPONSES_PROTOCOL if uses_responses_protocol(alias) else
                MESSAGES_PROTOCOL if uses_messages_protocol(alias) else 'chat_completions_v1')
    streaming = manifest or alias == ARTICLE_CHAT_SUPPORTED_ALIAS
    return {**route, 'protocol_family': protocol,
            'adapter_version': ADAPTER_VERSION if manifest else protocol + '-legacy-terminal-v1',
            'delivery_mode': 'streaming' if streaming else 'buffered', 'stream_verified': streaming}


def catalog_for(connection):
    return [{'model_id': model_id, 'display_name': preset['display_name'],
             'catalog_version': CATALOG_VERSION, 'context_window_tokens': None,
             'text': 'unknown', 'tools': 'unknown'}
            for (provider, model_id), preset in _PRESETS.items()
            if provider == connection.provider_id and get_trusted_preset(connection, model_id)]


def supports_article_chat(connection, model_id):
    """A route may deliver verified streaming or an explicitly buffered completion."""
    route = get_trusted_route(connection, model_id)
    return bool(route and (route['stream_verified'] or route['protocol_family'] != 'chat_completions_v1'))


def supports_task_route(connection, model_id, task_kind):
    """Text proof cannot enable a consumer with a stricter transport contract."""
    return bool(get_trusted_route(connection, model_id) and (
        task_kind not in ('article_qa', 'full_translation') or supports_article_chat(connection, model_id)
    ))
