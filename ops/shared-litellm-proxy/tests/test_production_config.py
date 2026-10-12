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
