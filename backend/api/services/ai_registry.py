"""Trusted connection identities derived from the existing LiteLLM route catalog.

Profiles bind a connection to a versioned, server-owned Proxy route. Endpoints
and protocol handling stay in LiteLLM; model capability receipts belong to T02.
"""
from api.services.ai_gateway import PROVIDER_SPECS
from django.conf import settings
from api.services.ai_endpoint_profiles import (
    EndpointManifestError, SERVICE_PRESETS, load_endpoint_profiles, profile_allows_user,
)

# New identities: never reinterpret an existing *_default connection or its
# encrypted AAD. A region change requires a new connection and explicit Key.
_REGIONAL_PROFILES = (
    ('glm', 'glm_cn', '智谱中国大陆通用 API', 'zai/cn'),
    ('glm', 'glm_zai', 'Z.AI 国际通用 API', 'zai/international'),
    ('qwen', 'qwen_beijing', '百炼北京通用 API', 'dashscope/beijing'),
    ('qwen', 'qwen_singapore', '百炼新加坡通用 API', 'dashscope/singapore'),
    ('kimi', 'kimi_international', 'Moonshot 国际通用 API', 'moonshot/international'),
)


def configured_profiles():
    try:
        profiles = load_endpoint_profiles(getattr(settings, 'AI_BYOK_ENDPOINT_MANIFEST', ''))
        reserved = {row[1] for row in _REGIONAL_PROFILES}
        return tuple(profile for profile in profiles if profile['profile_id'] not in reserved)
    except EndpointManifestError:
        # A broken optional manifest cannot change existing trusted cloud AAD.
        return ()


def provider_catalog(user_id=None):
    legacy = [
        {'provider_id': provider, 'provider_name': spec['label'],
         'profile_id': f'{provider}_default', 'version': 1,
         'region_name': '当前受信默认路由'}
        for provider, spec in PROVIDER_SPECS.items()
    ]
    regional = [
        {'provider_id': provider, 'provider_name': PROVIDER_SPECS[provider]['label'],
         'profile_id': profile_id, 'version': 1, 'region_name': region}
        for provider, profile_id, region, _prefix in _REGIONAL_PROFILES
    ]
    return legacy + regional + [
        {'provider_id': profile['provider_id'], 'provider_name': SERVICE_PRESETS[profile['provider_id']],
         'profile_id': profile['profile_id'], 'version': profile['version'],
         'region_name': profile['display_name'], 'auth_modes': list(profile['auth_modes']),
         'protocol_family': profile['protocol_family'],
         'data_destination_label': '管理员受信模型服务器；所选模型可能使用云服务'}
        for profile in configured_profiles() if profile_allows_user(profile, user_id)
    ]


def get_profile(provider_id, profile_id):
    for profile in configured_profiles():
        if (profile['provider_id'], profile['profile_id']) == (provider_id, profile_id):
            return {**profile, 'provider_name': SERVICE_PRESETS[provider_id],
                    'region_name': profile['display_name']}
    return next((profile for profile in provider_catalog()
                 if profile['provider_id'] == provider_id and profile['profile_id'] == profile_id), None)


def profile_route_prefix(connection):
    """Resolve only the stored provider/profile/version, never a caller URL."""
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if profile is None or profile['version'] != connection.endpoint_profile_version:
        return None
    if 'route_prefix' in profile:
        return profile['route_prefix'] if profile_allows_user(profile, getattr(connection, 'user_id', None)) else None
    for provider, profile_id, _region, prefix in _REGIONAL_PROFILES:
        if (provider, profile_id) == (connection.provider_id, connection.endpoint_profile):
            return prefix
    return PROVIDER_SPECS[connection.provider_id]['route_prefix']
