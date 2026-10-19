"""T02 manual names use trusted connection routes, never arbitrary endpoints."""
from types import SimpleNamespace as N
from unittest import TestCase

from api.services.ai_model_registry import get_trusted_preset, get_trusted_route


class ManualModelRouteTests(TestCase):
    def test_manual_ids_follow_the_versioned_connection_region(self):
        cases = (
            ('glm', 'glm_cn', 'zai/cn'), ('glm', 'glm_zai', 'zai/international'),
            ('qwen', 'qwen_beijing', 'dashscope/beijing'),
            ('qwen', 'qwen_singapore', 'dashscope/singapore'),
            ('kimi', 'kimi_international', 'moonshot/international'),
            ('openai', 'openai_default', 'openai'),
            ('anthropic', 'anthropic_default', 'anthropic'),
        )
        for provider, profile, prefix in cases:
            with self.subTest(profile=profile):
                connection = N(provider_id=provider, endpoint_profile=profile, endpoint_profile_version=1)
                self.assertIsNone(get_trusted_preset(connection, 'synthetic-future-model'))
                self.assertEqual(get_trusted_route(connection, 'synthetic-future-model')['proxy_alias'],
                                 prefix + '/synthetic-future-model')
                connection.endpoint_profile_version = 2
                self.assertIsNone(get_trusted_route(connection, 'synthetic-future-model'))
                connection.endpoint_profile_version = 1
                connection.provider_id = 'deepseek'
                self.assertIsNone(get_trusted_route(connection, 'synthetic-future-model'))

    def test_manual_ids_cannot_select_urls_nested_providers_or_router_parameters(self):
        connection = N(provider_id='deepseek', endpoint_profile='deepseek_default', endpoint_profile_version=1)
        for model_id in ('https://example.invalid', '../escape', 'openai/model', 'deepseek/model',
                         'model?api_base=x', 'model#fragment', 'foo@https', ' sk-secret ', 'sk-secret', None, {}):
            with self.subTest(model=model_id):
                self.assertIsNone(get_trusted_route(connection, model_id))

    def test_openrouter_nested_id_stays_inside_its_own_trusted_provider(self):
        connection = N(provider_id='openrouter', endpoint_profile='openrouter_default', endpoint_profile_version=1)
        self.assertEqual(get_trusted_route(connection, 'example/model')['proxy_alias'], 'openrouter/example/model')
        self.assertIsNone(get_trusted_route(connection, 'https://example.invalid'))

    def test_ambiguous_legacy_regions_do_not_silently_activate_saved_keys(self):
        for provider in ('glm', 'qwen', 'kimi'):
            connection = N(provider_id=provider, endpoint_profile=provider + '_default', endpoint_profile_version=1)
            self.assertIsNone(get_trusted_route(connection, 'synthetic-future-model'))
