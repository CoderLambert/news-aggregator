from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Category, News, Source, UserProviderCredential
from api.services.provider_credentials import (
    ProviderCredentialError,
    decrypt_api_key,
    encrypt_api_key,
    personal_clients_for_user,
)


SYNTHETIC_PROVIDER_KEY = 'sk-test-only-not-a-real-credential'
SYNTHETIC_PROJECT_KEY = 'sk-' + ('p' * 32)
GATEWAY_SETTINGS = {
    'PROVIDER_CREDENTIAL_ENCRYPTION_KEY': 'stable-test-encryption-key',
    'AI_BYOK_GATEWAY_URL': 'http://127.0.0.1:44000',
    'AI_BYOK_GATEWAY_PROJECT_KEY': SYNTHETIC_PROJECT_KEY,
    'AI_BYOK_GATEWAY_PROJECT_KEY_FILE': '',
}


@pytest.fixture
def owner(db):
    return User.objects.create_user(username='credential-owner', password='unused')


@pytest.fixture
def article(db):
    return News.objects.create(
        title='BYOK article', content='Preview', full_content='Complete body',
        full_content_state='legacy',
        publish_time=timezone.now(), url='https://example.test/byok',
        source=Source.objects.create(name='BYOK source', url='https://example.test', language='en'),
        category=Category.objects.create(name='BYOK category', slug='byok'),
    )


def _store_credential(user, provider='deepseek', model_id='deepseek-chat', key=SYNTHETIC_PROVIDER_KEY):
    return UserProviderCredential.objects.create(
        user=user,
        provider=provider,
        model_id=model_id,
        encrypted_api_key=encrypt_api_key(key, user.pk, provider),
    )


def _csrf_client(user):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.get('/api/auth/csrf/')
    return client, response.cookies['csrftoken'].value


@pytest.mark.django_db
def test_credential_api_requires_authentication(owner):
    client = APIClient()
    path = '/api/provider-credential/'
    payload = {'provider': 'deepseek', 'model_id': 'deepseek-chat', 'api_key': SYNTHETIC_PROVIDER_KEY}
    assert client.get(path).status_code == 403
    assert client.put(path, payload, format='json').status_code == 403
    assert client.delete(path).status_code == 403


@pytest.mark.django_db
@override_settings(**GATEWAY_SETTINGS)
def test_save_status_replace_and_delete_never_echo_plaintext(owner):
    client, csrf = _csrf_client(owner)
    path = '/api/provider-credential/'
    first = {'provider': 'deepseek', 'model_id': 'deepseek-chat', 'api_key': SYNTHETIC_PROVIDER_KEY}

    assert client.put(path, first, format='json').status_code == 403
    saved = client.put(path, first, format='json', HTTP_X_CSRFTOKEN=csrf)
    assert saved.status_code == 200
    assert saved.json()['configured'] is True
    assert saved.json()['requires_replacement'] is False
    assert saved.json()['provider'] == 'deepseek'
    assert saved.json()['model_id'] == 'deepseek-chat'
    assert SYNTHETIC_PROVIDER_KEY not in saved.content.decode()
    assert saved['Cache-Control'] == 'no-store'

    stored = UserProviderCredential.objects.get(user=owner)
    assert SYNTHETIC_PROVIDER_KEY not in stored.encrypted_api_key
    assert decrypt_api_key(stored) == SYNTHETIC_PROVIDER_KEY

    replacement_key = 'anthropic-test-only-not-a-real-credential'
    replaced = client.put(
        path,
        {'provider': 'anthropic', 'model_id': 'claude-sonnet-4-6', 'api_key': replacement_key},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert replaced.status_code == 200
    stored.refresh_from_db()
    assert stored.provider == 'anthropic'
    assert stored.model_id == 'claude-sonnet-4-6'
    assert decrypt_api_key(stored) == replacement_key

    assert client.delete(path).status_code == 403
    deleted = client.delete(path, HTTP_X_CSRFTOKEN=csrf)
    assert deleted.status_code == 200
    assert deleted.json() == {
        'configured': False,
        'requires_replacement': False,
        'provider': None,
        'provider_label': None,
        'model_id': None,
        'updated_at': None,
    }
    assert not UserProviderCredential.objects.filter(user=owner).exists()


@pytest.mark.django_db
@override_settings(**GATEWAY_SETTINGS)
def test_removed_direct_provider_is_retained_but_never_treated_as_configured(owner):
    UserProviderCredential.objects.create(
        user=owner,
        provider='volcengine',
        model_id='',
        encrypted_api_key=encrypt_api_key('legacy-test-key', owner.pk, 'volcengine'),
    )
    client = APIClient()
    client.force_login(owner)
    payload = client.get('/api/provider-credential/').json()
    assert payload['configured'] is False
    assert payload['requires_replacement'] is True
    assert payload['provider'] is None
    with pytest.raises(ProviderCredentialError, match='旧模型提供方已移除'):
        personal_clients_for_user(owner)


@pytest.mark.django_db
@override_settings(**GATEWAY_SETTINGS)
def test_credentials_are_owner_isolated_and_bound_to_owner(owner):
    other = User.objects.create_user(username='other-credential-owner', password='unused')
    owner_client, owner_csrf = _csrf_client(owner)
    other_client, _ = _csrf_client(other)
    owner_client.put(
        '/api/provider-credential/',
        {'provider': 'deepseek', 'model_id': 'deepseek-chat', 'api_key': SYNTHETIC_PROVIDER_KEY},
        format='json', HTTP_X_CSRFTOKEN=owner_csrf,
    )

    assert other_client.get('/api/provider-credential/').json()['configured'] is False
    credential = UserProviderCredential.objects.get(user=owner)
    credential.user = other
    with pytest.raises(ProviderCredentialError):
        decrypt_api_key(credential)


@pytest.mark.django_db
@override_settings(**GATEWAY_SETTINGS)
@pytest.mark.parametrize(('provider', 'model_id', 'route'), [
    ('openai', 'gpt-5-mini', 'openai/gpt-5-mini'),
    ('anthropic', 'claude-sonnet-4-6', 'anthropic/claude-sonnet-4-6'),
    ('deepseek', 'deepseek-chat', 'deepseek/deepseek-chat'),
    ('gemini', 'gemini-2.5-flash', 'gemini/gemini-2.5-flash'),
    ('qwen', 'qwen-plus', 'dashscope/qwen-plus'),
    ('glm', 'glm-4.7', 'zai/glm-4.7'),
    ('kimi', 'kimi-k2.5', 'moonshot/kimi-k2.5'),
    ('mistral', 'mistral-small-latest', 'mistral/mistral-small-latest'),
    ('groq', 'llama-3.3-70b-versatile', 'groq/llama-3.3-70b-versatile'),
    ('xai', 'grok-4.3', 'xai/grok-4.3'),
    ('openrouter', 'openai/gpt-4o-mini', 'openrouter/openai/gpt-4o-mini'),
])
def test_personal_client_uses_fixed_litellm_route_and_request_scoped_key(owner, provider, model_id, route):
    _store_credential(owner, provider=provider, model_id=model_id)
    calls = []
    constructed = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='ok'), finish_reason='stop',
            )])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            constructed.update(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self):
            return None

    fake_http = SimpleNamespace(close=lambda: None)
    with patch('httpx.Client', return_value=fake_http), patch('openai.OpenAI', FakeOpenAI):
        clients = personal_clients_for_user(owner)

    gateway_client, selected_model = clients[0]
    assert selected_model == route
    assert constructed['api_key'] == SYNTHETIC_PROJECT_KEY
    assert constructed['base_url'] == 'http://127.0.0.1:44000/v1'
    assert constructed['max_retries'] == 0
    assert SYNTHETIC_PROVIDER_KEY not in repr(constructed)

    response = gateway_client.chat.completions.create(
        model=selected_model, messages=[{'role': 'user', 'content': 'synthetic'}],
    )
    assert response.choices[0].message.content == 'ok'
    assert calls == [{
        'model': route,
        'messages': [{'role': 'user', 'content': 'synthetic'}],
        'extra_body': {'api_key': SYNTHETIC_PROVIDER_KEY},
    }]


@pytest.mark.django_db
@override_settings(**GATEWAY_SETTINGS)
@pytest.mark.parametrize(('provider', 'model_id', 'key'), [
    ('custom', 'model', SYNTHETIC_PROVIDER_KEY),
    ('volcengine', 'model', SYNTHETIC_PROVIDER_KEY),
    ('dashscope', 'model', SYNTHETIC_PROVIDER_KEY),
    ('deepseek', '', SYNTHETIC_PROVIDER_KEY),
    ('deepseek', '../private-route', SYNTHETIC_PROVIDER_KEY),
    ('deepseek', 'deepseek-chat/../private-route', SYNTHETIC_PROVIDER_KEY),
    ('deepseek', 'deepseek chat', SYNTHETIC_PROVIDER_KEY),
    ('deepseek', 'a' * 129, SYNTHETIC_PROVIDER_KEY),
    ('deepseek', 'deepseek-chat', 'short'),
    ('deepseek', 'deepseek-chat', 'key with whitespace'),
])
def test_invalid_provider_model_or_key_is_rejected_without_storage(owner, provider, model_id, key):
    client, csrf = _csrf_client(owner)
    response = client.put(
        '/api/provider-credential/',
        {'provider': provider, 'model_id': model_id, 'api_key': key},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 400
    assert response.json()['error_code'] == 'invalid_provider_credential'
    assert not UserProviderCredential.objects.filter(user=owner).exists()


@pytest.mark.django_db
@override_settings(**GATEWAY_SETTINGS, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chat_requires_a_provider_before_mutating_history(owner, article):
    client = APIClient()
    client.force_login(owner)
    response = client.post(f'/api/news/{article.pk}/chat/', {'question': 'Summarize'}, format='json')
    assert response.status_code == 409
    assert response.json()['error_code'] == 'provider_credential_required'
    assert not owner.news_chat_sessions.exists()


@pytest.mark.django_db(transaction=True)
@override_settings(**GATEWAY_SETTINGS, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_personal_key_is_used_for_chat_suggestions_and_translation(owner, article):
    _store_credential(owner)
    captured_chat = {}
    completion = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='["q1", "q2", "q3"]'), finish_reason='stop',
    )])
    base_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: completion)),
        close=lambda: None,
    )
    fake_http = SimpleNamespace(close=lambda: None)

    def fake_stream(_messages, **kwargs):
        captured_chat['clients'] = kwargs['clients']
        yield 'personal answer'

    client = APIClient()
    client.force_login(owner)
    with (
        patch('httpx.Client', return_value=fake_http),
        patch('openai.OpenAI', return_value=base_client),
        patch('api.views.stream_chat', side_effect=fake_stream),
        patch('api.services.chatgpt_subscription.active_connection_for_user', side_effect=AssertionError('subscription must not be used')),
    ):
        response = client.post(f'/api/news/{article.pk}/chat/', {'question': 'Summarize'}, format='json')
        assert response.status_code == 200
        assert 'personal answer' in b''.join(response.streaming_content).decode()
    assert captured_chat['clients'][0][1] == 'deepseek/deepseek-chat'

    with (
        patch('httpx.Client', return_value=fake_http),
        patch('openai.OpenAI', return_value=base_client),
        patch('api.services.chatgpt_subscription.active_connection_for_user', side_effect=AssertionError('subscription must not be used')),
    ):
        response = client.post(f'/api/news/{article.pk}/suggested-questions/?force=1', {}, format='json')
    assert response.status_code == 200
    assert response.json()['questions'] == ['q1', 'q2', 'q3']

    completed_job = SimpleNamespace(
        text='完整译文', done=True, error=None,
        wait_for_update=lambda *_args, **_kwargs: 4,
    )
    with (
        patch('httpx.Client', return_value=fake_http),
        patch('openai.OpenAI', return_value=base_client),
        patch('api.services.llm_translator.find_chinese_translation_link', return_value=None),
        patch('api.services.translation_jobs.start_or_get_job', return_value=completed_job) as start,
        patch('api.services.chatgpt_subscription.active_connection_for_user', side_effect=AssertionError('subscription must not be used')),
    ):
        response = client.post(f'/api/news/{article.pk}/translate/', {'force': True}, format='json')
        assert response.status_code == 200
        assert '完整译文' in b''.join(response.streaming_content).decode()
    assert start.call_args.kwargs['clients'][0][1] == 'deepseek/deepseek-chat'
