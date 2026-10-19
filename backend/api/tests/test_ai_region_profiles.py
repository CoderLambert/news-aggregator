"""T01 regional identities and the trusted Proxy configuration, no network/DB."""
from pathlib import Path
from types import SimpleNamespace as N
from unittest import TestCase

import yaml

from api.services.ai_gateway import PROVIDER_SPECS
from api.services.ai_model_registry import get_trusted_preset
from api.services.ai_registry import get_profile, profile_route_prefix, provider_catalog


class TrustedRegionProfileTests(TestCase):
    def test_existing_default_identities_and_routes_remain_unchanged(self):
        for provider, spec in PROVIDER_SPECS.items():
            connection = N(provider_id=provider, endpoint_profile=f'{provider}_default', endpoint_profile_version=1)
            self.assertEqual(profile_route_prefix(connection), spec['route_prefix'])
            self.assertEqual(get_profile(provider, connection.endpoint_profile), {
                'provider_id': provider, 'provider_name': spec['label'],
                'profile_id': f'{provider}_default', 'version': 1, 'region_name': '当前受信默认路由'})

    def test_regions_are_distinct_versioned_identities_with_fixed_native_routes(self):
        root = Path(__file__).resolve().parents[3]
        config = yaml.safe_load((root / 'ops/shared-litellm-proxy/proxy.yaml').read_text())
        routes = {item['model_name']: item['litellm_params'] for item in config['model_list']}
        expected = (
            ('glm', 'glm_cn', 'zai/cn', 'https://open.bigmodel.cn/api/paas/v4'),
            ('glm', 'glm_zai', 'zai/international', 'https://api.z.ai/api/paas/v4'),
            ('qwen', 'qwen_beijing', 'dashscope/beijing', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
            ('qwen', 'qwen_singapore', 'dashscope/singapore', 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'),
            ('kimi', 'kimi_international', 'moonshot/international', 'https://api.moonshot.ai/v1'),
        )
        for provider, profile_id, prefix, endpoint in expected:
            with self.subTest(profile=profile_id):
                connection = N(provider_id=provider, endpoint_profile=profile_id, endpoint_profile_version=1)
                self.assertEqual(profile_route_prefix(connection), prefix)
                self.assertEqual(routes[prefix + '/*'], {
                    'model': PROVIDER_SPECS[provider]['route_prefix'] + '/*', 'api_base': endpoint})
                connection.endpoint_profile_version = 2
                self.assertIsNone(profile_route_prefix(connection))
                connection.endpoint_profile_version = 1
                connection.provider_id = 'deepseek'
                self.assertIsNone(profile_route_prefix(connection))

    def test_catalog_exposes_only_selection_metadata_and_does_not_open_models(self):
        catalog = provider_catalog()
        self.assertEqual(len({row['profile_id'] for row in catalog}), len(catalog))
        for row in catalog:
            self.assertEqual(set(row), {'provider_id', 'provider_name', 'profile_id', 'version', 'region_name'})
        regional = N(provider_id='glm', endpoint_profile='glm_cn', endpoint_profile_version=1)
        self.assertIsNone(get_trusted_preset(regional, 'unapproved-user-model'))
        self.assertIsNone(get_profile('glm', 'https://example.invalid'))
