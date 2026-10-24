"""T02 synthetic loopback transport integration; zero paid upstream requests.

A disposable HTTPServer imitates only the LiteLLM Chat Completions envelope.
This is not a real LiteLLM process, provider, production or browser test.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from api.services.ai_model_probe import send_model_probe
from api.services.ai_gateway import build_gateway_client


PROJECT_KEY = 'sk-' + 'syntheticprojectkey1234567890ABCD'
PROVIDER_KEY = 'synthetic-provider-key-never-real'


class _ProxyStub(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        payload = json.loads(raw)
        self.server.seen.append((self.path, self.headers.get('Authorization'), payload))
        self.server.native_headers.append((self.headers.get('x-api-key'), self.headers.get('x-ambient-secret')))
        # Flash defaults to thinking: forced tool selection is rejected and a
        # tiny text budget can be spent on reasoning before any final answer.
        if (payload.get('model') == 'deepseek/deepseek-flash'
                and payload.get('thinking') != {'type': 'disabled'}):
            self.send_response(400)
            self.end_headers()
            return
        if self.server.status_code == 429:
            self.send_response(429)
            self.end_headers()
            return
        if self.server.status_code == 307:
            self.send_response(307)
            self.send_header('Location', 'https://example.invalid/collect')
            self.end_headers()
            return
        if self.path == '/v1/messages':
            blocks = ([{'type': 'tool_use', 'id': 'toolu_probe', 'name': 'byok_probe', 'input': {'ok': True}}]
                      if payload.get('tools') else [{'type': 'text', 'text': 'ok'}])
            reply = {'id': 'msg_synthetic', 'type': 'message', 'role': 'assistant',
                     'model': 'claude-haiku-5-5', 'content': blocks,
                     'stop_reason': ('max_tokens' if self.server.bad_terminal else
                                     'tool_use' if payload.get('tools') else 'end_turn'),
                     'usage': {'input_tokens': 9, 'output_tokens': 1}}
        elif self.path == '/v1/responses':
            item = ({'type': 'function_call', 'id': 'fc_probe', 'call_id': 'call_probe',
                     'name': 'byok_probe', 'arguments': '{"ok":true}', 'status': 'completed'}
                    if payload.get('tools') else
                    {'type': 'message', 'role': 'assistant', 'status': 'completed',
                     'content': [{'type': 'output_text', 'text': 'ok', 'annotations': []}]})
            reply = {'status': 'incomplete' if self.server.bad_terminal else 'completed',
                     'output': [item], 'usage': {'input_tokens': 9, 'output_tokens': 1}}
        elif self.server.bad_terminal:
            reply = {'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]}
        elif payload.get('tools'):
            reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {
                'content': None,
                'tool_calls': [{'type': 'function', 'id': 'call_synthetic_1',
                                'function': {'name': 'byok_probe','arguments': '{"ok":true}'}}]}}]}
        else:
            reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                     'usage': {'prompt_tokens': 9, 'completion_tokens': 1}}
        body = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('x-request-id', 'synthetic-request-1')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        # Never emit mock request bodies/headers to CI logs.
        return


class SyntheticGatewayTransportTests(TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _ProxyStub)
        self.server.seen = []
        self.server.native_headers = []
        self.server.status_code = 200
        self.server.bad_terminal = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def send(self, kind, model_alias='deepseek/deepseek-chat'):
        with override_settings(
                AI_BYOK_GATEWAY_URL=f'http://127.0.0.1:{self.server.server_port}',
                AI_BYOK_GATEWAY_PROJECT_KEY=PROJECT_KEY,
                AI_BYOK_GATEWAY_PROJECT_KEY_FILE=''):
            return send_model_probe(provider_key=PROVIDER_KEY, model_alias=model_alias, probe_kind=kind)

    def test_flash_short_probes_disable_default_thinking(self):
        for kind in ('text', 'tools'):
            result = self.send(kind, model_alias='deepseek/deepseek-flash')
            self.assertEqual(result.status, 'succeeded')
        self.assertEqual(len(self.server.seen), 2)
        text_payload, tools_payload = self.server.seen[0][2], self.server.seen[1][2]
        for payload in (text_payload, tools_payload):
            self.assertEqual(payload['thinking'], {'type': 'disabled'})
        self.assertLessEqual(text_payload['max_tokens'], 8)
        self.assertLessEqual(tools_payload['max_tokens'], 128)
        self.assertEqual(tools_payload['tool_choice'],
                         {'type': 'function', 'function': {'name': 'byok_probe'}})

    def test_openai_probes_use_stateless_native_responses(self):
        for kind in ('text', 'tools'):
            self.assertEqual(self.send(kind, 'openai/gpt-5.4-mini').status, 'succeeded')
        self.assertEqual(len(self.server.seen), 2)
        for path, bearer, payload in self.server.seen:
            self.assertEqual(path, '/v1/responses')
            self.assertEqual(bearer, f'Bearer {PROJECT_KEY}')
            self.assertEqual(payload['api_key'], PROVIDER_KEY)
            self.assertFalse(payload['store'])
            self.assertLessEqual(payload['max_output_tokens'], 128)
        self.assertEqual(self.server.seen[1][2]['tool_choice'], 'auto')
        self.server.bad_terminal = True
        self.assertEqual(self.send('text', 'openai/gpt-5.4-mini').status, 'unknown')
        self.assertEqual(len(self.server.seen), 3)

    def test_anthropic_probes_use_native_messages_and_fail_closed_on_truncation(self):
        for kind in ('text', 'tools'):
            self.assertEqual(self.send(kind, 'anthropic/claude-haiku-5-5').status, 'succeeded')
        self.assertEqual(len(self.server.seen), 2)
        for path, bearer, payload in self.server.seen:
            self.assertEqual(path, '/v1/messages')
            self.assertEqual(bearer, f'Bearer {PROJECT_KEY}')
            self.assertEqual(payload['api_key'], PROVIDER_KEY)
            self.assertEqual(payload['thinking'], {'type': 'disabled'})
            self.assertNotIn('temperature', payload)
            self.assertLessEqual(payload['max_tokens'], 128)
        self.assertEqual(self.server.seen[1][2]['tool_choice'], {'type': 'auto'})
        self.server.bad_terminal = True
        self.assertEqual(self.send('text', 'anthropic/claude-haiku-5-5').status, 'unknown')
        self.assertEqual(len(self.server.seen), 3)

    def test_official_messages_sdk_uses_project_auth_and_ignores_ambient_headers(self):
        with override_settings(
                AI_BYOK_GATEWAY_URL=f'http://127.0.0.1:{self.server.server_port}',
                AI_BYOK_GATEWAY_PROJECT_KEY=PROJECT_KEY, AI_BYOK_GATEWAY_PROJECT_KEY_FILE=''), patch.dict(
                    'os.environ', {'ANTHROPIC_CUSTOM_HEADERS': 'x-ambient-secret: synthetic-header-secret',
                                   'ANTHROPIC_API_KEY': 'synthetic-ambient-key',
                                   'ANTHROPIC_AUTH_TOKEN': 'synthetic-ambient-token'}):
            client = build_gateway_client(PROVIDER_KEY)
            try:
                result = client.chat.completions.create(model='anthropic/claude-haiku-5-5',
                    messages=[{'role': 'user', 'content': 'synthetic'}], max_tokens=64)
                self.assertEqual(result.choices[0].message.content, 'ok')
                self.assertEqual(result.usage.prompt_tokens, 9)
            finally:
                client.close()
        self.assertEqual(len(self.server.seen), 1)
        path, auth, payload = self.server.seen[0]
        self.assertEqual(path, '/v1/messages')
        self.assertIsNone(auth)
        self.assertEqual(self.server.native_headers, [(PROJECT_KEY, None)])
        self.assertEqual(payload['api_key'], PROVIDER_KEY)

    def test_text_and_tool_one_shots_have_bounded_fixed_request_shapes(self):
        for kind in ('text', 'tools'):
            result = self.send(kind)
            self.assertEqual(result.status, 'succeeded')
        self.assertEqual(len(self.server.seen), 2)
        for path, bearer, payload in self.server.seen:
            self.assertEqual(path, '/v1/chat/completions')
            self.assertEqual(bearer, f'Bearer {PROJECT_KEY}')
            self.assertEqual(payload['api_key'], PROVIDER_KEY)
            self.assertEqual(payload['model'], 'deepseek/deepseek-chat')
            self.assertIs(payload['stream'], False)
            self.assertLessEqual(payload['max_tokens'], 32)
            self.assertNotIn('thinking', payload)
        self.assertEqual(self.server.seen[1][2]['tool_choice'], 'auto')

    def test_rate_limit_redirect_and_incomplete_reply_never_verify(self):
        for status in (429, 307):
            self.server.status_code = status
            self.assertEqual(self.send('text').status, 'unknown')
        self.assertEqual(len(self.server.seen), 2)
        self.server.status_code = 200
        self.server.bad_terminal = True
        self.assertEqual(self.send('text').status, 'unknown')

    def test_loopback_requirement_rejects_nonlocal_gateway_before_send(self):
        with override_settings(AI_BYOK_GATEWAY_URL='https://example.invalid',
                AI_BYOK_GATEWAY_PROJECT_KEY=PROJECT_KEY, AI_BYOK_GATEWAY_PROJECT_KEY_FILE=''):
            result = send_model_probe(provider_key=PROVIDER_KEY,
                                      model_alias='deepseek/deepseek-chat', probe_kind='text')
        self.assertEqual(result.status, 'not_sent')
        self.assertEqual(len(self.server.seen), 0)
