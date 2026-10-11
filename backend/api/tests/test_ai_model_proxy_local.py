"""Real local LiteLLM Proxy + synthetic-upstream integration; run via scripts/byok/run_t02_proxy_local.py."""

from __future__ import annotations

import base64
import os
import uuid

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import AICallAttempt


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(os.environ.get('T02_PROXY_LOCAL') != '1', reason='requires the isolated T02 Proxy runner'),
]

ENCRYPTION_KEY = base64.urlsafe_b64encode(b'0123456789abcdef0123456789abcdef').decode('ascii').rstrip('=')


@override_settings(
    AI_BYOK_ENABLED=True,
    PUBLIC_SITE_MODE='full',
    AI_CONNECTION_ENCRYPTION_KEY=ENCRYPTION_KEY,
    AI_CONNECTION_ENCRYPTION_KEY_ID='t02-proxy-local-v1',
    SECURE_SSL_REDIRECT=False,
)
def test_model_test_api_reaches_only_the_local_proxy_and_fences_capability_results(settings):
    gateway_url = os.environ['AI_BYOK_GATEWAY_URL']
    project_key = os.environ['AI_BYOK_GATEWAY_PROJECT_KEY']
    provider_key = os.environ['T02_SYNTHETIC_PROVIDER_KEY']
    settings.AI_BYOK_GATEWAY_URL = gateway_url
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = project_key

    user = User.objects.create_user(username=f't02-proxy-{uuid.uuid4().hex[:10]}', password='synthetic-password-123!')
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
            'display_name': 'T02 synthetic proxy connection',
            'api_key': provider_key,
        },
        format='json',
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert connection.status_code == 201
    model = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection.json()['id'], 'catalog_model_id': 'deepseek-flash'},
        format='json',
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert model.status_code == 201

    model_test_url = reverse('ai-model-test', kwargs={'model_id': model.json()['id']})
    text_result = client.post(
        model_test_url, {'probe_kind': 'text'}, format='json', HTTP_X_CSRFTOKEN=csrf_token,
    )
    tools_result = client.post(
        model_test_url, {'probe_kind': 'tools'}, format='json', HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert text_result.status_code == 200
    assert text_result.json()['status'] == 'succeeded'
    assert text_result.json()['capability'] == 'supported'
    assert tools_result.status_code == 200
    assert tools_result.json()['status'] == 'failed'
    assert tools_result.json()['safe_error_code'] == 'probe_not_supported'
    assert tools_result.json()['capability'] == 'unknown'
    assert provider_key not in text_result.content.decode('utf-8')
    assert provider_key not in tools_result.content.decode('utf-8')

    attempts = list(AICallAttempt.objects.filter(user=user).order_by('probe_kind'))
    assert [(item.probe_kind, item.status) for item in attempts] == [
        ('text', 'succeeded'), ('tools', 'failed'),
    ]
    current = client.get(reverse('ai-model-list')).json()['models'][0]
    assert current['capabilities']['text'] == 'supported'
    assert current['capabilities']['tools'] == 'unknown'
