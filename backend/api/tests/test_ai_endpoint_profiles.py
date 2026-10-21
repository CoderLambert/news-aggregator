"""Trusted admin configuration is data; it cannot grant arbitrary routing."""
import copy
import json
from types import SimpleNamespace

import pytest

from api.services.ai_model_registry import get_trusted_route, normalize_model_id
from api.services.ai_registry import get_profile, profile_route_prefix, provider_catalog


def profile(**changes):
    return {
        'profile_id': 'office_ollama', 'version': 1, 'provider_id': 'ollama',
        'display_name': '办公室模型', 'protocol_family': 'chat_completions_v1',
        'api_base': 'http://127.0.0.1:11434/v1', 'network_zone': 'same_host',
        'allowed_ips': ['127.0.0.1'], 'auth_modes': ['none'],
        'allowed_user_ids': [7], 'enabled': True, **changes,
    }


def install_manifest(settings, tmp_path, entries):
    path = tmp_path / 'trusted-endpoints.json'
    path.write_text(json.dumps(entries))
    settings.AI_BYOK_ENDPOINT_MANIFEST = str(path)
    return path


def connection(**changes):
    return SimpleNamespace(**dict(provider_id='ollama', endpoint_profile='office_ollama',
                                  endpoint_profile_version=1, user_id=7) | changes)


def test_trusted_local_profile_routes_namespaced_and_tagged_models(settings, tmp_path):
    install_manifest(settings, tmp_path, [profile()])
    conn = connection()
    approved = get_profile('ollama', 'office_ollama')
    assert approved is not None
    for model in ('minimax-m3.1-flash:cloud', 'org/model:tag', 'model@revision', 'ollama/model'):
        assert normalize_model_id('ollama', model) == model
        route = get_trusted_route(conn, model)
        assert route['proxy_alias'].endswith('/' + model)
        assert route['protocol_family'] == 'chat_completions_v1'
    assert get_trusted_route(connection(user_id=8), 'org/model') is None


def test_catalog_filters_private_profiles_and_never_exposes_urls(settings, tmp_path):
    install_manifest(settings, tmp_path, [profile()])
    assert not any(p['profile_id'] == 'office_ollama' for p in provider_catalog())
    owner = provider_catalog(user_id=7)
    local = next(p for p in owner if p['profile_id'] == 'office_ollama')
    assert local['auth_modes'] == ['none']
    assert local['protocol_family'] == 'chat_completions_v1'
    assert 'api_base' not in local and 'allowed_ips' not in local
    assert '127.0.0.1' not in json.dumps(owner)


def test_same_version_policy_change_revokes_alias_but_label_change_does_not(settings, tmp_path):
    item = profile()
    path = install_manifest(settings, tmp_path, [item])
    first = profile_route_prefix(connection())
    item['display_name'] = '重命名'
    path.write_text(json.dumps([item]))
    assert profile_route_prefix(connection()) == first
    item['api_base'] = 'http://127.0.0.1:11435/v1'
    path.write_text(json.dumps([item]))
    assert profile_route_prefix(connection()) != first
    item['enabled'] = False
    path.write_text(json.dumps([item]))
    assert profile_route_prefix(connection()) is None


@pytest.mark.parametrize('changes', [
    {'api_base': 'http://169.254.169.254/v1', 'allowed_ips': ['169.254.169.254']},
    {'api_base': 'http://127.1/v1'},
    {'api_base': 'http://2130706433/v1'},
    {'api_base': 'http://user:pass@127.0.0.1/v1'},
    {'api_base': 'http://127.0.0.1/v1?target=cloud'},
    {'api_base': 'http://127.0.0.1/v1#fragment'},
    {'api_base': 'http://[::ffff:127.0.0.1]:11434/v1', 'allowed_ips': ['::ffff:127.0.0.1']},
    {'allowed_ips': ['0.0.0.0/0']}, {'allowed_ips': []},
    {'allowed_user_ids': []}, {'allowed_user_ids': [True]},
    {'auth_modes': ['inherit']}, {'auth_modes': []},
    {'protocol_family': 'guess'}, {'version': True},
    {'network_zone': 'public_https'}, {'unexpected': 'ignored'},
    {'api_base': 'http://127.0.0.1:11434/a/../v1'},
])
def test_unsafe_admin_manifests_are_rejected(changes):
    from api.services.ai_endpoint_profiles import EndpointManifestError, validate_endpoint_profiles
    with pytest.raises(EndpointManifestError):
        validate_endpoint_profiles([profile(**changes)])


def test_duplicate_profile_cannot_shadow_legacy_or_sibling(settings, tmp_path):
    from api.services.ai_endpoint_profiles import EndpointManifestError, validate_endpoint_profiles
    item = profile()
    with pytest.raises(EndpointManifestError):
        validate_endpoint_profiles([item, copy.deepcopy(item)])
    install_manifest(settings, tmp_path, [profile(profile_id='deepseek_default', provider_id='deepseek')])
    assert get_profile('deepseek', 'deepseek_default')['region_name'] == '当前受信默认路由'
    assert get_profile('ollama', 'office_ollama') is None


@pytest.mark.parametrize('model', [
    'https://example.com/model', 'model?api_base=evil', '../model', 'org//model',
    'org/%2e%2e/model', ' model', 'model\n', '/org/model', 'org/model#fragment',
])
def test_model_id_cannot_override_endpoint(settings, tmp_path, model):
    install_manifest(settings, tmp_path, [profile()])
    assert get_trusted_route(connection(), model) is None


def test_public_endpoint_requires_https_and_public_pinned_ip():
    from api.services.ai_endpoint_profiles import EndpointManifestError, validate_endpoint_profiles
    item = profile(api_base='https://inference.example.com/v1', network_zone='public_https',
                   auth_modes=['api_key'], allowed_user_ids=[], allowed_ips=['8.8.8.8'])
    assert len(validate_endpoint_profiles([item])) == 1
    item['allowed_ips'] = ['10.1.2.3']
    with pytest.raises(EndpointManifestError):
        validate_endpoint_profiles([item])


def test_invalid_manifest_is_fail_closed_without_disabling_existing_cloud(settings, tmp_path):
    path = install_manifest(settings, tmp_path, [])
    path.write_text('[{"profile_id":"duplicate","profile_id":"duplicate"}]')
    assert get_profile('ollama', 'office_ollama') is None
    assert get_profile('deepseek', 'deepseek_default') is not None
