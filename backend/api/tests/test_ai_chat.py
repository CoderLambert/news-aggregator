from __future__ import annotations

import base64
import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Category, ChatSession, News, Source, UserAITaskPreference
from api.services.ai_chat import ArticleChatError
from api.services.chat_history import ChatConflict


ENCRYPTION_KEY = base64.urlsafe_b64encode(b't04-synthetic-app-encryption-key').decode('ascii').rstrip('=')
SYNTHETIC_PROVIDER_KEY = 'sk-t04-synthetic-provider-key-never-real'


@pytest.fixture(autouse=True)
def enable_test_settings(settings):
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 't04-test-key-v1'
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:4000'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-' + ('t' * 32)
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    settings.SECURE_SSL_REDIRECT = False


def _authenticated_client(username='t04-owner'):
    user = User.objects.create_user(username=username, password='synthetic-password-123!')
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get(reverse('auth-csrf'))
    assert csrf.status_code == 200
    return client, user, csrf.json()['csrfToken']


def _create_model(client, csrf):
    connection = client.post(
        reverse('ai-connection-list'),
        {
            'provider_id': 'deepseek',
            'endpoint_profile': 'deepseek_default',
            'display_name': 'T04 synthetic connection',
            'api_key': SYNTHETIC_PROVIDER_KEY,
        },
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert connection.status_code == 201, connection.content
    model = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection.json()['id'], 'catalog_model_id': 'deepseek-flash'},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert model.status_code == 201, model.content
    return connection.json()['id'], model.json()


def _create_news():
    category = Category.objects.create(name='T04 Chat', slug='t04-chat')
    source = Source.objects.create(name='T04 source', url='https://t04.example.test')
    return News.objects.create(
        title='T04 article',
        content='Article summary.',
        full_content='Full article context.',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://t04.example.test/article',
    )


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_selected_model_stream_persists_one_owner_scoped_pair_and_source(monkeypatch):
    client, user, csrf = _authenticated_client()
    _connection_id, model = _create_model(client, csrf)
    news = _create_news()
    observed = {}

    def fake_stream(execution, messages, *, execution_guard):
        execution_guard()
        observed['execution'] = execution
        observed['messages'] = messages
        yield 'Answer '
        yield 'complete.'

    monkeypatch.setattr('api.services.ai_chat.stream_article_chat', fake_stream)
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: None)
    monkeypatch.setattr('api.views.stream_chat', lambda *_args, **_kwargs: pytest.fail('legacy provider fallback ran'))
    response = client.post(
        f'/api/news/{news.pk}/chat/',
        {'question': 'What is the key point?', 'model_config_id': model['id']},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    body = b''.join(response.streaming_content).decode('utf-8')

    session = ChatSession.objects.get(user=user, news=news)
    assert session.messages == [
        {'role': 'user', 'content': 'What is the key point?'},
        {
            'role': 'assistant',
            'content': 'Answer complete.',
            'model_source': {'provider': 'DeepSeek', 'model': 'DeepSeek V4.1 Flash'},
        },
    ]
    assert '__META__' in body and 'DeepSeek V4.1 Flash' in body
    assert 'Answer complete.' in body
    assert SYNTHETIC_PROVIDER_KEY not in body
    assert observed['execution'].model_alias == 'news.deepseek-flash'
    assert observed['execution'].provider_key == SYNTHETIC_PROVIDER_KEY
    assert observed['messages'][-1] == {'role': 'user', 'content': 'What is the key point?'}
    assert UserAITaskPreference.objects.filter(user=user).count() == 0


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_incomplete_stream_is_reported_and_never_saved_as_an_answer(monkeypatch):
    client, user, csrf = _authenticated_client('t04-incomplete')
    _connection_id, model = _create_model(client, csrf)
    news = _create_news()
    calls = []

    def incomplete_stream(*_args, **_kwargs):
        calls.append('called')
        yield 'partial output'
        raise ArticleChatError('incomplete_response')

    monkeypatch.setattr('api.services.ai_chat.stream_article_chat', incomplete_stream)
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: None)
    monkeypatch.setattr('api.views.stream_chat', lambda *_args, **_kwargs: pytest.fail('legacy provider fallback ran'))
    response = client.post(
        f'/api/news/{news.pk}/chat/',
        {'question': 'question', 'model_config_id': model['id']},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    body = b''.join(response.streaming_content).decode('utf-8')

    assert calls == ['called']
    assert 'partial output' in body
    assert '__ERROR__' in body
    assert '本次内容未保存' in body
    assert ChatSession.objects.get(user=user, news=news).messages == []


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_cross_owner_model_selection_fails_before_content_fetch_or_provider(monkeypatch):
    owner_client, _owner, owner_csrf = _authenticated_client('t04-model-owner')
    _connection_id, model = _create_model(owner_client, owner_csrf)
    other_client, other_user, other_csrf = _authenticated_client('t04-other')
    news = _create_news()
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: pytest.fail('invalid model fetched article'))
    monkeypatch.setattr('api.services.ai_chat.stream_article_chat', lambda *_args, **_kwargs: pytest.fail('provider ran'))

    response = other_client.post(
        f'/api/news/{news.pk}/chat/',
        {'question': 'question', 'model_config_id': model['id']},
        format='json',
        HTTP_X_CSRFTOKEN=other_csrf,
    )

    assert response.status_code == 404
    assert response.json()['error_code'] == 'model_not_found'
    assert ChatSession.objects.filter(user=other_user, news=news).exists() is False


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_late_result_after_clear_is_discarded(monkeypatch):
    client, user, csrf = _authenticated_client('t04-clear-race')
    _connection_id, model = _create_model(client, csrf)
    news = _create_news()

    def clear_during_stream(_execution, _messages, *, execution_guard):
        yield 'late answer'
        assert client.delete(f'/api/news/{news.pk}/chat/').status_code == 200
        with pytest.raises(ChatConflict):
            execution_guard()

    monkeypatch.setattr('api.services.ai_chat.stream_article_chat', clear_during_stream)
    monkeypatch.setattr('api.views.ensure_full_content', lambda _news: None)
    response = client.post(
        f'/api/news/{news.pk}/chat/',
        {'question': 'question', 'model_config_id': model['id']},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    body = b''.join(response.streaming_content).decode('utf-8')

    session = ChatSession.objects.get(user=user, news=news)
    assert session.messages == []
    assert 'late answer' in body
    assert '__ERROR__' in body
