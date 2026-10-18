"""T01 removal checks for the retired single-Key BYOK business API.

Connection CRUD, encryption, owner/CSRF, and epoch tests are retained in
test_ai_connections.py. No endpoint or worker here may initiate a paid call.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.services.ai_execution import (
    PersonalAIUnavailable, has_personal_connection, personal_clients_for_user,
)


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(
        username='retired-credential-owner', password='synthetic-only'
    )


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['get', 'put', 'post', 'delete'])
def test_legacy_credential_api_is_unrouted_and_never_writes(owner, method):
    client = APIClient()
    client.force_authenticate(user=owner)
    body = {'provider': 'deepseek', 'model_id': 'deepseek-chat',
            'api_key': 'synthetic-key-never-real'}
    response = getattr(client, method)('/api/provider-credential/', body, format='json') if (
        method in ('put', 'post')
    ) else getattr(client, method)('/api/provider-credential/')
    assert response.status_code == 404
    assert not UserAIConnection.objects.filter(user=owner).exists()


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full')
def test_new_connection_never_becomes_a_legacy_or_site_funded_default(owner):
    assert not has_personal_connection(owner)
    assert personal_clients_for_user(owner) == []
    UserAIConnection.objects.create(
        user=owner, provider_id='deepseek', endpoint_profile='deepseek_default',
        display_name='test-only-connection', request_hash='test-only',
        credential_ciphertext='synthetic-no-decrypt', is_enabled=False,
    )
    assert not has_personal_connection(owner)
    UserAIConnection.objects.filter(user=owner).update(is_enabled=True)
    assert has_personal_connection(owner)
    with (
        patch('openai.OpenAI', side_effect=AssertionError('model was called')) as upstream,
        pytest.raises(PersonalAIUnavailable, match='请等待模型与用途配置完成'),
    ):
        personal_clients_for_user(owner)
    upstream.assert_not_called()


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chat_with_unbound_personal_connection_fails_before_history_or_model(owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    UserAIConnection.objects.create(
        user=owner, provider_id='deepseek', endpoint_profile='deepseek_default',
        display_name='test-only-connection', request_hash='test-only',
        credential_ciphertext='synthetic-no-decrypt',
    )
    from api.models import Category, News, Source
    from django.utils import timezone
    from api.tests.rss.reader_fixtures import public_legacy_article

    article = public_legacy_article(News.objects.create(
        title='Test Article', content='Preview', full_content='Complete body',
        full_content_state='legacy',
        publish_time=timezone.now(), url='https://example.test/retired-byok',
        source=Source.objects.create(name='Test Source', url='https://example.test', language='en'),
        category=Category.objects.create(name='Test Category', slug='retired-byok'),
    ))
    with (
        patch('api.views.get_clients', side_effect=AssertionError('no site-key fallback')) as site,
        patch('openai.OpenAI', side_effect=AssertionError('no paid request')) as paid,
    ):
        response = client.post(f'/api/news/{article.pk}/chat/',
                               {'question': 'Summarize'}, format='json')
    assert response.status_code == 409
    assert response.data['error_code'] == 'provider_credential_unavailable'
    assert not owner.news_chat_sessions.exists()
    site.assert_not_called()
    paid.assert_not_called()

@pytest.mark.django_db
def test_disabled_byok_gate_never_shadows_independent_subscription(owner):
    UserAIConnection.objects.create(
        user=owner, provider_id='deepseek', endpoint_profile='deepseek_default',
        display_name='synthetic-only', request_hash='synthetic-only',
        credential_ciphertext='synthetic-not-a-key', is_enabled=True,
    )
    for enabled, mode in ((False, 'full'), (True, 'read_only')):
        with override_settings(AI_BYOK_ENABLED=enabled, PUBLIC_SITE_MODE=mode):
            assert has_personal_connection(owner) is False
            assert personal_clients_for_user(owner) == []
    with override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full'):
        assert has_personal_connection(owner) is True
        with pytest.raises(PersonalAIUnavailable):
            personal_clients_for_user(owner)

@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_chatgpt_subscription_works_even_with_enabled_unbound_byok_connection(owner):
    from api.models import Category, News, Source
    from api.tests.rss.reader_fixtures import public_legacy_article
    from django.utils import timezone
    from rest_framework.response import Response

    news = public_legacy_article(News.objects.create(
        title='Subscription Priority', content='summary', full_content='complete',
        full_content_state='legacy',
        publish_time=timezone.now(), url='https://example.test/byok-subscription',
        source=Source.objects.create(name='Subscription Source', url='https://example.test/sub'),
        category=Category.objects.create(name='Subscription Category', slug='byok-subscription'),
    ))
    UserAIConnection.objects.create(
        user=owner, provider_id='deepseek', endpoint_profile='deepseek_default',
        display_name='unbound Key', request_hash='synthetic-only',
        credential_ciphertext='synthetic-not-a-key', is_enabled=True,
    )
    client = APIClient()
    client.force_login(owner)
    selected = object()
    with (
        patch('api.services.chatgpt_subscription.active_connection_for_user', return_value=selected),
        patch('api.services.ai_execution.personal_clients_for_user',
              side_effect=AssertionError('unbound BYOK must not shadow subscription')) as byok,
        patch('api.services.chatgpt_subscription.stream_chat_response',
              return_value=iter(['subscription synthetic answer'])) as subscription,
        patch('api.views.get_clients',
              side_effect=AssertionError('no site-Key fallback')) as site,
    ):
        result = client.post(f'/api/news/{news.pk}/chat/',
                             {'question': 'Explain'}, format='json')
        assert result.status_code == 200
        assert 'subscription synthetic answer' in b''.join(result.streaming_content).decode()
    subscription.assert_called_once()
    byok.assert_not_called()
    site.assert_not_called()
