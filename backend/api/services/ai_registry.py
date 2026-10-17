"""Trusted connection identities derived from the existing LiteLLM route catalog.

This is not a new provider adapter. Region-specific profiles remain a T01 follow-up; model capability
receipts belong to T02; a default route must not claim a verified region/model.
"""
from api.services.provider_credentials import PROVIDER_SPECS


def provider_catalog():
    return [
        {'provider_id': provider, 'provider_name': spec['label'],
         'profile_id': f'{provider}_default', 'version': 1,
         'region_name': '当前受信默认路由'}
        for provider, spec in PROVIDER_SPECS.items()
    ]


def get_profile(provider_id, profile_id):
    return next((profile for profile in provider_catalog()
                 if profile['provider_id'] == provider_id and profile['profile_id'] == profile_id), None)
