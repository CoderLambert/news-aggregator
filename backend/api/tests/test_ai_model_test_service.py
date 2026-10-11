from __future__ import annotations

import json
import urllib.request

from api.services import ai_model_test


class _Response:
    status = 200
    headers = {'x-request-id': 'proxy-request-123'}

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode('utf-8')

    def read(self, limit):
        assert limit == ai_model_test.MAX_RESPONSE_BYTES + 1
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_tools_probe_uses_only_the_fixed_gateway_and_scoped_headers(monkeypatch):
    captured = []
    provider_key = 'sk-t02-synthetic-provider-key-never-real'
    project_key = 'sk-' + ('a' * 32)

    class _Opener:
        def open(self, request, timeout):
            assert isinstance(request, urllib.request.Request)
            captured.append((request, timeout))
            return _Response({
                'choices': [{
                    'message': {
                        'content': None,
                        'tool_calls': [{
                            'function': {'name': 'byok_probe', 'arguments': '{"ok":true}'},
                        }],
                    },
                }],
                'usage': {'prompt_tokens': 9, 'completion_tokens': 3},
            })

    monkeypatch.setattr(ai_model_test, '_URL_OPENER', _Opener())
    result = ai_model_test.send_model_probe(
        gateway_url='http://127.0.0.1:44001',
        project_key=project_key,
        provider_key=provider_key,
        model_alias='news.deepseek-flash',
        probe_kind='tools',
    )

    assert result.status == 'succeeded'
    assert result.provider_request_id == 'proxy-request-123'
    assert result.input_tokens == 9
    assert result.output_tokens == 3
    assert len(captured) == 1
    request, timeout = captured[0]
    assert request.full_url == 'http://127.0.0.1:44001/v1/chat/completions'
    assert request.get_header('Authorization') == f'Bearer {project_key}'
    assert provider_key not in request.get_header('Authorization')
    assert timeout == ai_model_test.REQUEST_TIMEOUT_SECONDS
    payload = json.loads(request.data)
    assert payload['model'] == 'news.deepseek-flash'
    assert payload['api_key'] == provider_key
    assert payload['stream'] is False
    assert payload['max_tokens'] == 32
    assert payload['tool_choice']['function']['name'] == 'byok_probe'


def test_text_probe_is_bounded_and_unknown_gateway_urls_fail_before_network(monkeypatch):
    called = []

    class _Opener:
        def open(self, request, timeout):
            called.append(request)
            return _Response({'choices': [{'message': {'content': 'ready'}}]})

    monkeypatch.setattr(ai_model_test, '_URL_OPENER', _Opener())
    result = ai_model_test.send_model_probe(
        gateway_url='https://gateway.example',
        project_key='sk-' + ('b' * 32),
        provider_key='sk-t02-synthetic-provider-key-never-real',
        model_alias='news.deepseek-flash',
        probe_kind='text',
    )
    assert result.status == 'succeeded'
    payload = json.loads(called[0].data)
    assert payload['max_tokens'] == 8
    assert payload['stream'] is False
    assert payload['temperature'] == 0

    invalid = ai_model_test.send_model_probe(
        gateway_url='http://gateway.example/path?redirect=1',
        project_key='sk-' + ('b' * 32),
        provider_key='sk-t02-synthetic-provider-key-never-real',
        model_alias='news.deepseek-flash',
        probe_kind='text',
    )
    assert invalid.status == 'not_sent'
    assert invalid.safe_error_code == 'gateway_unavailable'
    assert len(called) == 1


def test_probe_never_follows_redirects():
    handler = ai_model_test._NoRedirectHandler()
    request = urllib.request.Request('http://127.0.0.1:44001/v1/chat/completions')
    assert handler.redirect_request(
        request, None, 307, 'Temporary Redirect', {}, 'http://attacker.example/collect',
    ) is None
