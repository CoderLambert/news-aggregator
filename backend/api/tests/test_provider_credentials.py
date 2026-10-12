from unittest.mock import patch
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APIClient

from api.models import Category, News, Source, UserProviderCredential
from api.services.provider_credentials import (
    ProviderCredentialError,
    decrypt_api_key,
    encrypt_api_key,
    personal_clients_for_user,
)
from django.utils import timezone


SYNTHETIC_ARK_KEY = 'ark-test-only-not-a-real-credential'
SYNTHETIC_DASHSCOPE_KEY = 'sk-test-only-not-a-real-credential'


@pytest.fixture
def owner(db):
    return User.objects.create_user(username='credential-owner', password='unused')


@pytest.fixture
def article(db):
    return News.objects.create(
        title='BYOK article', content='Preview', full_content='Complete body',
        publish_time=timezone.now(), url='https://example.test/byok',
        source=Source.objects.create(name='BYOK source', url='https://example.test', language='en'),
        category=Category.objects.create(name='BYOK category', slug='byok'),
    )


def _store_credential(user, provider='volcengine', key=SYNTHETIC_ARK_KEY):
    return UserProviderCredential.objects.create(
        user=user,
        provider=provider,
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
    assert client.get(path).status_code == 403
    assert client.put(path, {'provider': 'volcengine', 'api_key': SYNTHETIC_ARK_KEY}, format='json').status_code == 403
    assert client.delete(path).status_code == 403


@pytest.mark.django_db
@override_settings(PROVIDER_CREDENTIAL_ENCRYPTION_KEY='stable-test-encryption-key')
def test_save_status_replace_and_delete_never_echo_plaintext(owner):
    client, csrf = _csrf_client(owner)
    path = '/api/provider-credential/'

    assert client.put(
        path,
        {'provider': 'volcengine', 'api_key': SYNTHETIC_ARK_KEY},
        format='json',
    ).status_code == 403

    saved = client.put(
        path,
        {'provider': 'volcengine', 'api_key': SYNTHETIC_ARK_KEY},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert saved.status_code == 200
    assert saved.json()['configured'] is True
    assert saved.json()['provider'] == 'volcengine'
    assert SYNTHETIC_ARK_KEY not in saved.content.decode()
    assert saved['Cache-Control'] == 'no-store'

    stored = UserProviderCredential.objects.get(user=owner)
    assert SYNTHETIC_ARK_KEY not in stored.encrypted_api_key
    assert decrypt_api_key(stored) == SYNTHETIC_ARK_KEY

    status_response = client.get(path)
    assert status_response.status_code == 200
    assert SYNTHETIC_ARK_KEY not in status_response.content.decode()

    replaced = client.put(
        path,
        {'provider': 'dashscope', 'api_key': SYNTHETIC_DASHSCOPE_KEY},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert replaced.status_code == 200
    stored.refresh_from_db()
    assert stored.provider == 'dashscope'
    assert decrypt_api_key(stored) == SYNTHETIC_DASHSCOPE_KEY

    assert client.delete(path).status_code == 403
    deleted = client.delete(path, HTTP_X_CSRFTOKEN=csrf)
    assert deleted.status_code == 200
    assert deleted.json() == {
        'configured': False,
        'provider': None,
        'provider_label': None,
        'updated_at': None,
    }
    assert not UserProviderCredential.objects.filter(user=owner).exists()


@pytest.mark.django_db
@override_settings(PROVIDER_CREDENTIAL_ENCRYPTION_KEY='stable-test-encryption-key')
def test_credentials_are_owner_isolated_and_bound_to_owner(owner):
    other = User.objects.create_user(username='other-credential-owner', password='unused')
    owner_client, owner_csrf = _csrf_client(owner)
    other_client, _ = _csrf_client(other)
    owner_client.put(
        '/api/provider-credential/',
        {'provider': 'volcengine', 'api_key': SYNTHETIC_ARK_KEY},
        format='json', HTTP_X_CSRFTOKEN=owner_csrf,
    )

    assert other_client.get('/api/provider-credential/').json()['configured'] is False
    credential = UserProviderCredential.objects.get(user=owner)
    credential.user = other
    with pytest.raises(ProviderCredentialError):
        decrypt_api_key(credential)


@pytest.mark.django_db
@override_settings(PROVIDER_CREDENTIAL_ENCRYPTION_KEY='stable-test-encryption-key')
def test_personal_client_uses_allowlisted_provider_configuration(owner):
    client, csrf = _csrf_client(owner)
    client.put(
        '/api/provider-credential/',
        {'provider': 'dashscope', 'api_key': SYNTHETIC_DASHSCOPE_KEY},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with patch('openai.OpenAI', FakeOpenAI):
        clients = personal_clients_for_user(owner)
    assert len(clients) == 1
    assert clients[0][1] == 'kimi-k2.5'
    assert captured == {
        'api_key': SYNTHETIC_DASHSCOPE_KEY,
        'base_url': 'https://coding.dashscope.aliyuncs.com/v1',
    }


@pytest.mark.django_db
@override_settings(PROVIDER_CREDENTIAL_ENCRYPTION_KEY='stable-test-encryption-key')
@pytest.mark.parametrize('provider,key', [
    ('custom', SYNTHETIC_ARK_KEY),
    ('volcengine', 'sk-wrong-provider'),
    ('dashscope', 'ark-wrong-provider'),
    ('dashscope', 'sk- bad whitespace'),
])
def test_invalid_provider_or_key_is_rejected_without_storage(owner, provider, key):
    client, csrf = _csrf_client(owner)
    response = client.put(
        '/api/provider-credential/',
        {'provider': provider, 'api_key': key},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 400
    assert response.json()['error_code'] == 'invalid_provider_credential'
    assert not UserProviderCredential.objects.filter(user=owner).exists()


@pytest.mark.django_db
@override_settings(
    PROVIDER_CREDENTIAL_ENCRYPTION_KEY='stable-test-encryption-key',
    PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True,
)
def test_chat_requires_a_provider_before_mutating_history(owner, article):
    client = APIClient()
    client.force_login(owner)
    response = client.post(
        f'/api/news/{article.pk}/chat/', {'question': 'Summarize'}, format='json',
    )
    assert response.status_code == 409
    assert response.json()['error_code'] == 'provider_credential_required'
    assert not owner.news_chat_sessions.exists()


@pytest.mark.django_db(transaction=True)
@override_settings(
    PROVIDER_CREDENTIAL_ENCRYPTION_KEY='stable-test-encryption-key',
    PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True,
)
def test_personal_key_is_used_for_chat_suggestions_and_translation(owner, article):
    _store_credential(owner)
    sentinel_client = object()
    captured_chat = {}

    def fake_openai(**_kwargs):
        return sentinel_client

    def fake_stream(_messages, **kwargs):
        captured_chat['clients'] = kwargs['clients']
        yield 'personal answer'

    client = APIClient()
    client.force_login(owner)
    with (
        patch('openai.OpenAI', side_effect=fake_openai),
        patch('api.views.stream_chat', side_effect=fake_stream),
        patch('api.services.chatgpt_subscription.active_connection_for_user', side_effect=AssertionError('subscription must not be used')),
    ):
        response = client.post(
            f'/api/news/{article.pk}/chat/', {'question': 'Summarize'}, format='json',
        )
        assert response.status_code == 200
        assert 'personal answer' in b''.join(response.streaming_content).decode()
    assert captured_chat['clients'] == [(sentinel_client, 'deepseek-v4-pro')]

    completion = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='["q1", "q2", "q3"]'),
    )])
    sentinel_client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **_kwargs: completion),
    ))
    with (
        patch('openai.OpenAI', return_value=sentinel_client),
        patch('api.services.chatgpt_subscription.active_connection_for_user', side_effect=AssertionError('subscription must not be used')),
    ):
        response = client.post(
            f'/api/news/{article.pk}/suggested-questions/?force=1', {}, format='json',
        )
    assert response.status_code == 200
    assert response.json()['questions'] == ['q1', 'q2', 'q3']

    sentinel_client = object()
    completed_job = SimpleNamespace(
        text='完整译文', done=True, error=None,
        wait_for_update=lambda *_args, **_kwargs: 4,
    )
    with (
        patch('openai.OpenAI', return_value=sentinel_client),
        patch('api.services.llm_translator.find_chinese_translation_link', return_value=None),
        patch('api.services.translation_jobs.start_or_get_job', return_value=completed_job) as start,
        patch('api.services.chatgpt_subscription.active_connection_for_user', side_effect=AssertionError('subscription must not be used')),
    ):
        response = client.post(
            f'/api/news/{article.pk}/translate/', {'force': True}, format='json',
        )
        assert response.status_code == 200
        assert '完整译文' in b''.join(response.streaming_content).decode()
    assert start.call_args.kwargs['clients'] == [(sentinel_client, 'deepseek-v4-pro')]
