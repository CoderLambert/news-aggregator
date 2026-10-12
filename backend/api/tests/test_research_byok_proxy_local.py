from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import (
    ResearchRun,
    ResearchRunEvent,
    ResearchSearchResult,
    UserAIConnection,
    UserAIModelConfig,
    UserAITaskPreference,
)
from api.services.ai_credentials import encrypt_credential
from api.services.ai_model_registry import get_model_preset
from api.services.research import job_manager


pytestmark = pytest.mark.skipif(
    os.environ.get('T09_PROXY_LOCAL') != '1',
    reason='requires the isolated T09 Proxy runner',
)

ENCRYPTION_KEY = base64.urlsafe_b64encode(b'0123456789abcdef0123456789abcdef').decode('ascii').rstrip('=')


@pytest.mark.django_db(transaction=True)
def test_first_research_run_uses_sdk_proxy_tool_and_durable_result(settings, monkeypatch):
    settings.DJANGO_ENV = 'development'
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = False
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 't09-proxy-local-v1'
    settings.AI_BYOK_GATEWAY_URL = os.environ['AI_BYOK_GATEWAY_URL']
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = os.environ['AI_BYOK_GATEWAY_PROJECT_KEY']
    provider_key = os.environ['T09_SYNTHETIC_PROVIDER_KEY']

    user = User.objects.create_user(username='t09-proxy-local-owner', password='synthetic-password')
    preset = get_model_preset('deepseek-flash', 'deepseek')
    connection = UserAIConnection.objects.create(
        user=user,
        provider_id='deepseek',
        endpoint_profile='deepseek_default',
        endpoint_profile_version=1,
        display_name='T09 isolated proxy connection',
    )
    connection.credential_ciphertext, connection.encryption_key_id = encrypt_credential(
        connection, provider_key,
    )
    connection.save(update_fields=['credential_ciphertext', 'encryption_key_id', 'updated_at'])
    model = UserAIModelConfig.objects.create(
        connection=connection,
        model_id=preset['model_id'],
        display_name=preset['display_name'],
        catalog_model_id=preset['catalog_model_id'],
        catalog_version=preset['catalog_version'],
        proxy_model_alias=preset['proxy_model_alias'],
        capability_snapshot={'text': 'supported', 'tools': 'supported'},
        verification_status='verified',
        verified_credential_epoch=connection.credential_epoch,
        verified_config_revision=1,
        verified_endpoint_profile_version=connection.endpoint_profile_version,
    )
    UserAITaskPreference.objects.create(
        user=user,
        task_kind='deep_research',
        model_config=model,
    )

    dispatched = []
    monkeypatch.setattr(
        'api.services.chatgpt_subscription_jobs.submit_background_task',
        lambda function, *args, **kwargs: dispatched.append((function, args, kwargs)),
    )
    monkeypatch.setattr(
        'api.services.research.tools._tool_search_news',
        lambda query, **_kwargs: {
            'query': query,
            'mode': 'keyword',
            'total': 1,
            'articles': [{
                'id': 91209,
                'title': 'Synthetic controlled article',
                'summary': 'A deterministic local fixture.',
            }],
        },
    )

    client = APIClient()
    client.force_login(user)
    prompt = 'T09_PROXY_LOCAL_PRIVATE_PROMPT_' + os.urandom(5).hex()
    response = client.post(
        reverse('research-create'),
        {'query': prompt, 'local_only': True},
        format='json',
        HTTP_IDEMPOTENCY_KEY='t09-proxy-local-run',
    )
    assert response.status_code == 200
    run_id = response['Run-ID']
    response.close()
    assert len(dispatched) == 1

    function, args, kwargs = dispatched[0]
    function(*args, **kwargs)

    run = ResearchRun.objects.get(pk=run_id)
    run.session.refresh_from_db()
    assert run.status == 'succeeded'
    assert run.session.messages[-1]['content'].startswith('## T09 controlled research report')
    assert ResearchSearchResult.objects.filter(
        session=run.session,
        tool_name='search_news',
        query='controlled news result',
    ).exists()
    assert [
        event.event_type for event in ResearchRunEvent.objects.filter(run=run).order_by('sequence')
    ] == ['thinking', 'tool_call', 'tool_result', 'thinking', 'text_delta', 'complete']
    assert provider_key not in str(run.execution_snapshot)
    assert provider_key not in str(run.session.messages)
