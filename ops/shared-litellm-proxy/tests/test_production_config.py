"""Static policy assertions for the production LiteLLM configuration."""

from pathlib import Path

import yaml


EXPECTED_ROUTES = {
    'openai/*',
    'anthropic/*',
    'deepseek/*',
    'gemini/*',
    'dashscope/*',
    'zai/*',
    'moonshot/*',
    'mistral/*',
    'groq/*',
    'xai/*',
    'openrouter/*',
}


def test_production_routes_are_fixed_provider_wildcards_without_credentials_or_base_urls():
    config_path = Path(__file__).resolve().parents[1] / 'proxy.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    models = config['model_list']

    assert {item['model_name'] for item in models} == EXPECTED_ROUTES
    assert {item['litellm_params']['model'] for item in models} == EXPECTED_ROUTES
    for item in models:
        assert set(item['litellm_params']) == {'model'}

    general = config['general_settings']
    assert general['allow_client_side_credentials'] is True
    assert general['disable_master_key_return'] is True
    assert config['router_settings']['num_retries'] == 0
    assert config['router_settings']['fallbacks'] == []
    assert config['litellm_settings']['turn_off_message_logging'] is True


def test_chat_streaming_guard_is_wired_and_fail_closed_in_production_config():
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / 'proxy.yaml').read_text(encoding='utf-8'))
    assert config['litellm_settings']['callbacks'] == 'byok_gateway_policy.proxy_handler_instance'

    compose = yaml.safe_load((root / 'compose.yaml').read_text(encoding='utf-8'))
    proxy = compose['services']['proxy']
    assert proxy['image'] == 'ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2'
    mounts = {str(item) for item in proxy['volumes']}
    assert any(item.startswith('./provider_key_guard.py:/app/byok_gateway_policy.py') for item in mounts)
    # Defence in depth: the guard denies Chat streaming even without this
    # variable, but production must still declare the intent explicitly.
    assert proxy['environment']['BYOK_DENY_STREAMING_CALL_TYPES'] == 'acompletion'

    guard = (root / 'provider_key_guard.py').read_text(encoding='utf-8')
    assert 'ALWAYS_DENIED_STREAMING_CALL_TYPES' in guard
    assert 'T00_CHAT_STREAMING_DISABLED' in guard
