import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from ai_endpoint_profiles import validate_endpoint_profiles


def raw_profile(**changes):
    return dict(profile_id='office_ollama', version=1, provider_id='ollama', display_name='Office model',
                protocol_family='chat_completions_v1', api_base='http://127.0.0.1:11434/v1',
                network_zone='same_host', allowed_ips=['127.0.0.1'], auth_modes=['none', 'api_key'],
                allowed_user_ids=[7], enabled=True) | changes


class TrustedRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'manifest.json'
        self.item = raw_profile()
        self.path.write_text(json.dumps([self.item]))
        self.profile = validate_endpoint_profiles([self.item])[0]
        self.alias = self.profile['route_prefix'] + '/org/model:cloud'

    def test_current_alias_auth_and_owner_are_all_required(self):
        from trusted_routes import resolve_route
        from trusted_transport import EgressDenied
        with patch.dict(os.environ, {'AI_BYOK_ENDPOINT_MANIFEST': str(self.path)}):
            profile, model = resolve_route(self.alias, owner_id=7, auth_mode='none')
            self.assertEqual(model, 'org/model:cloud')
            self.assertEqual(profile['api_base'], 'http://127.0.0.1:11434/v1')
            for owner, mode, alias in ((8, 'none', self.alias), (True, 'none', self.alias),
                                       (7, 'inherit', self.alias), (7, 'none', self.alias + '?api_base=evil')):
                with self.subTest(owner=owner, mode=mode), self.assertRaises(EgressDenied):
                    resolve_route(alias, owner_id=owner, auth_mode=mode)
            self.item['api_base'] = 'http://127.0.0.1:11435/v1'
            self.path.write_text(json.dumps([self.item]))
            with self.assertRaises(EgressDenied):
                resolve_route(self.alias, owner_id=7, auth_mode='none')

    def test_config_generation_is_fixed_and_idempotent_without_fake_keys(self):
        from trusted_routes import build_proxy_config
        base = {'model_list': [{'model_name': 'openai/*', 'litellm_params': {'model': 'openai/*'}}],
                'router_settings': {'num_retries': 0, 'fallbacks': []}, 'litellm_settings': {}}
        actual = build_proxy_config(base, [self.profile])
        self.assertEqual(base['model_list'][0]['model_name'], 'openai/*')
        configured = actual['model_list'][1]
        self.assertEqual(configured['model_name'], self.profile['route_prefix'] + '/*')
        self.assertEqual(configured['litellm_params']['api_base'], 'http://127.0.0.1:11434/v1')
        self.assertEqual(configured['litellm_params']['model'], 'newshub_chat/*')
        self.assertNotIn('api_key', configured['litellm_params'])
        self.assertEqual(build_proxy_config(actual, [self.profile]), actual)
        self.assertEqual(build_proxy_config(actual, [])['model_list'], base['model_list'])

    def test_cli_generates_private_config_and_refuses_to_overwrite_inputs(self):
        base = Path(self.directory.name) / 'base.json'
        output = Path(self.directory.name) / 'active.yaml'
        base.write_text(json.dumps({'model_list': [], 'litellm_settings': {}}))
        script = Path(__file__).resolve().parents[1] / 'configure_trusted_endpoints.py'
        arguments = [sys.executable, str(script), '--manifest', str(self.path),
                     '--base', str(base), '--output', str(output)]
        generated = subprocess.run(arguments, capture_output=True, text=True)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertIn(self.profile['route_prefix'], output.read_text())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        # Production mounts the script at /app, without checkout ancestors.
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', prefix='newshub-config-', dir='/tmp') as flat:
            flat.write(script.read_text())
            flat.flush()
            mounted = subprocess.run([arguments[0], flat.name, *arguments[2:]], capture_output=True, text=True)
            self.assertEqual(mounted.returncode, 0, mounted.stderr)
        original = base.read_text()
        rejected = subprocess.run(arguments[:-1] + [str(base)], capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(base.read_text(), original)
