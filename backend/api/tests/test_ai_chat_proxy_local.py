from __future__ import annotations

import base64
import json
import os
import re
import uuid

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Category, ChatSession, News, Source


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(os.environ.get('T04_PROXY_LOCAL') != '1', reason='requires the isolated T04 Responses Proxy runner'),
]

ENCRYPTION_KEY = base64.urlsafe_b64encode(b'0123456789abcdef0123456789abcdef').decode('ascii').rstrip('=')


@override_settings(
    AI_BYOK_ENABLED=True,
    PUBLIC_SITE_MODE='full',
    PUBLIC_AI_ENABLED=True,
    AI_CONNECTION_ENCRYPTION_KEY=ENCRYPTION_KEY,
    AI_CONNECTION_ENCRYPTION_KEY_ID='t04-proxy-local-v1',
    SECURE_SSL_REDIRECT=False,
)
def test_article_chat_api_uses_real_openai_sdk_responses_stream_through_local_proxy(settings):
    settings.AI_BYOK_GATEWAY_URL = os.environ['AI_BYOK_GATEWAY_URL']
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = os.environ['AI_BYOK_GATEWAY_PROJECT_KEY']
    provider_key = os.environ['T04_SYNTHETIC_PROVIDER_KEY']

    user = User.objects.create_user(
        username=f't04-proxy-{uuid.uuid4().hex[:10]}',
        password='synthetic-password-123!',
    )
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get(reverse('auth-csrf'))
    assert csrf.status_code == 200
    csrf_token = csrf.json()['csrfToken']

    connection = client.post(
        reverse('ai-connection-list'),
        {
            'provider_id': 'deepseek',
            'endpoint_profile': 'deepseek_default',
            'display_name': 'T04 local controlled provider',
            'api_key': provider_key,
        },
        format='json',
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert connection.status_code == 201, connection.content
    model = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection.json()['id'], 'catalog_model_id': 'deepseek-flash'},
        format='json',
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert model.status_code == 201, model.content

    category = Category.objects.create(name='T04 Proxy Chat', slug='t04-proxy-chat')
    source = Source.objects.create(name='T04 Proxy source', url='https://t04-proxy.example.test')
    news = News.objects.create(
        title='Synthetic T04 article',
        content='Controlled article summary.',
        full_content='Controlled full article context.',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://t04-proxy.example.test/article',
    )

    response = client.post(
        f'/api/news/{news.pk}/chat/',
        {'question': 'T00_T04_PROXY_STREAM_A', 'model_config_id': model.json()['id']},
        format='json',
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert response.status_code == 200
    body = b''.join(response.streaming_content).decode('utf-8')

    assert '__ERROR__' not in body
    assert 'DeepSeek V4.1 Flash' in body
    assert 'synthetic t00 stream' in body
    assert provider_key not in body
    assert ChatSession.objects.get(user=user, news=news).messages == [
        {'role': 'user', 'content': 'T00_T04_PROXY_STREAM_A'},
        {
            'role': 'assistant',
            'content': 'synthetic t00 stream',
            'model_source': {'provider': 'DeepSeek', 'model': 'DeepSeek V4.1 Flash'},
        },
    ]

    incomplete_response = client.post(
        f'/api/news/{news.pk}/chat/',
        {'question': 'T00_T04_PROXY_INCOMPLETE_A', 'model_config_id': model.json()['id']},
        format='json',
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert incomplete_response.status_code == 200
    incomplete_body = b''.join(incomplete_response.streaming_content).decode('utf-8')
    error_frame = re.search(r'__ERROR__(\{.*?\})__ERROR__', incomplete_body)
    assert error_frame is not None
    assert json.loads(error_frame.group(1))['code'] == 'incomplete_response'
    assert 'synthetic t00 stream' in incomplete_body
    assert provider_key not in incomplete_body
    assert ChatSession.objects.get(user=user, news=news).messages == [
        {'role': 'user', 'content': 'T00_T04_PROXY_STREAM_A'},
        {
            'role': 'assistant',
            'content': 'synthetic t00 stream',
            'model_source': {'provider': 'DeepSeek', 'model': 'DeepSeek V4.1 Flash'},
        },
    ]
