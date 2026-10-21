"""Shared manifest resolution and static LiteLLM custom-provider routes."""
import copy
import os

from ai_endpoint_profiles import (
    EndpointManifestError, load_endpoint_profiles, profile_allows_user, valid_upstream_model_id,
)
from trusted_transport import EgressDenied

PROVIDER_ID = 'newshub_chat'


def resolve_route(alias, *, owner_id, auth_mode):
    if (type(alias) is not str or type(owner_id) is not int or owner_id < 1
            or type(auth_mode) is not str or auth_mode not in ('api_key', 'none')):
        raise EgressDenied()
    try:
        profiles = load_endpoint_profiles(os.environ.get('AI_BYOK_ENDPOINT_MANIFEST', ''))
    except EndpointManifestError:
        raise EgressDenied() from None
    for profile in profiles:
        prefix = profile['route_prefix'] + '/'
        if alias.startswith(prefix):
            model = alias[len(prefix):]
            if (not valid_upstream_model_id(model) or auth_mode not in profile['auth_modes']
                    or not profile_allows_user(profile, owner_id)):
                raise EgressDenied()
            return profile, model
    raise EgressDenied()


def build_proxy_config(base, profiles):
    """Generate fixed config; never store provider Keys or fake credentials."""
    result = copy.deepcopy(base)
    result['model_list'] = [row for row in result.get('model_list', [])
                            if not row.get('model_name', '').startswith('newshub/')]
    for profile in profiles:
        if not profile['enabled']:
            continue
        result['model_list'].append({
            'model_name': profile['route_prefix'] + '/*',
            'litellm_params': {'model': PROVIDER_ID + '/*', 'api_base': profile['api_base'],
                              'num_retries': 0, 'timeout': 180},
        })
    settings = result.setdefault('litellm_settings', {})
    mapping = [row for row in settings.get('custom_provider_map', []) if row.get('provider') != PROVIDER_ID]
    if any(profile['enabled'] for profile in profiles):
        mapping.append({'provider': PROVIDER_ID, 'custom_handler': 'trusted_chat.provider'})
    if mapping:
        settings['custom_provider_map'] = mapping
    else:
        settings.pop('custom_provider_map', None)
    result.setdefault('router_settings', {}).update(num_retries=0, fallbacks=[])
    settings['num_retries'] = 0
    return result
