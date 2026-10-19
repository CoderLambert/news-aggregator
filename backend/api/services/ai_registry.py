"""Trusted connection identities derived from the existing LiteLLM route catalog.

Profiles bind a connection to a versioned, server-owned Proxy route. Endpoints
and protocol handling stay in LiteLLM; model capability receipts belong to T02.
"""
from api.services.ai_gateway import PROVIDER_SPECS

# New identities: never reinterpret an existing *_default connection or its
# encrypted AAD. A region change requires a new connection and explicit Key.
_REGIONAL_PROFILES = (
    ('glm', 'glm_cn', '智谱中国大陆通用 API', 'zai/cn'),
    ('glm', 'glm_zai', 'Z.AI 国际通用 API', 'zai/international'),
    ('qwen', 'qwen_beijing', '百炼北京通用 API', 'dashscope/beijing'),
    ('qwen', 'qwen_singapore', '百炼新加坡通用 API', 'dashscope/singapore'),
    ('kimi', 'kimi_international', 'Moonshot 国际通用 API', 'moonshot/international'),
)


def provider_catalog():
    legacy = [
        {'provider_id': provider, 'provider_name': spec['label'],
         'profile_id': f'{provider}_default', 'version': 1,
         'region_name': '当前受信默认路由'}
        for provider, spec in PROVIDER_SPECS.items()
    ]
    return legacy + [
        {'provider_id': provider, 'provider_name': PROVIDER_SPECS[provider]['label'],
         'profile_id': profile_id, 'version': 1, 'region_name': region}
        for provider, profile_id, region, _prefix in _REGIONAL_PROFILES
    ]


def get_profile(provider_id, profile_id):
    return next((profile for profile in provider_catalog()
                 if profile['provider_id'] == provider_id and profile['profile_id'] == profile_id), None)


def profile_route_prefix(connection):
    """Resolve only the stored provider/profile/version, never a caller URL."""
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if profile is None or profile['version'] != connection.endpoint_profile_version:
        return None
    for provider, profile_id, _region, prefix in _REGIONAL_PROFILES:
        if (provider, profile_id) == (connection.provider_id, connection.endpoint_profile):
            return prefix
    return PROVIDER_SPECS[connection.provider_id]['route_prefix']
