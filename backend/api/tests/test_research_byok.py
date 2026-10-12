from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import (
    ResearchRun,
    ResearchRunEvent,
    ResearchSearchResult,
    ResearchSession,
    UserAIConnection,
    UserAIModelConfig,
    UserAITaskPreference,
)
from api.services.ai_credentials import encrypt_credential
from api.services.ai_model_registry import get_model_preset
from api.services.research import job_manager


ENCRYPTION_KEY = base64.urlsafe_b64encode(b't09-synthetic-app-encryption-key').decode('ascii').rstrip('=')
PROVIDER_KEY = 'sk-t09-synthetic-provider-key-never-real'
PROJECT_KEY = 'sk-' + ('t' * 32)


@pytest.fixture(autouse=True)
def byok_research_settings(settings):
    settings.DJANGO_ENV = 'development'
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = False
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 't09-test-key-v1'
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:44009'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = PROJECT_KEY


@pytest.fixture(autouse=True)
def reset_research_process_state():
    with job_manager._capacity_lock:
        job_manager._admitted_runs.clear()
    with job_manager._dispatch_lock:
        job_manager._dispatching.clear()
    yield
    with job_manager._capacity_lock:
        job_manager._admitted_runs.clear()
    with job_manager._dispatch_lock:
        job_manager._dispatching.clear()


@pytest.fixture
def queued_executor(monkeypatch):
    submitted = []

    def capture(function, *args, **kwargs):
        submitted.append((function, args, kwargs))
        return SimpleNamespace(done=False)

    monkeypatch.setattr(
        'api.services.chatgpt_subscription_jobs.submit_background_task', capture,
    )
    return submitted


def _client(user):
    client = APIClient()
    client.force_login(user)
    return client


def _verified_research_model(user, *, tools='supported', display_name='T09 synthetic connection'):
    preset = get_model_preset('deepseek-flash', 'deepseek')
    connection = UserAIConnection.objects.create(
        user=user,
        provider_id='deepseek',
        endpoint_profile='deepseek_default',
        endpoint_profile_version=1,
        display_name=display_name,
    )
    connection.credential_ciphertext, connection.encryption_key_id = encrypt_credential(
        connection, PROVIDER_KEY,
    )
    connection.save(update_fields=['credential_ciphertext', 'encryption_key_id', 'updated_at'])
    model = UserAIModelConfig.objects.create(
        connection=connection,
        model_id=preset['model_id'],
        display_name=preset['display_name'],
        catalog_model_id=preset['catalog_model_id'],
        catalog_version=preset['catalog_version'],
        proxy_model_alias=preset['proxy_model_alias'],
        capability_snapshot={
            'text': 'supported',
            'tools': tools,
            'structured_output': 'unknown',
            'thinking': 'unknown',
            'stream': 'unknown',
        },
        verification_status='verified',
        verified_credential_epoch=connection.credential_epoch,
        verified_config_revision=1,
        verified_endpoint_profile_version=connection.endpoint_profile_version,
    )
    UserAITaskPreference.objects.update_or_create(
        user=user,
        task_kind='deep_research',
        defaults={'model_config': model},
    )
    return connection, model


def _submit(client, *, query='Research the synthetic test topic', key='t09-idempotency-key'):
    response = client.post(
        reverse('research-create'),
        {'query': query, 'local_only': True},
        format='json',
        HTTP_IDEMPOTENCY_KEY=key,
    )
    return response


def _tool_call(name='search_news', arguments='{"query":"synthetic topic","mode":"keyword"}'):
    return SimpleNamespace(
        id='tool-call-t09-1',
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _completion(*, text=None, tool_calls=None, finish_reason='stop'):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=text, tool_calls=tool_calls),
        )],
    )


def _run_submitted_worker(submitted):
    function, args, kwargs = submitted[0]
    function(*args, **kwargs)


@pytest.mark.django_db(transaction=True)
def test_research_requires_current_verified_tools_route_and_gateway_before_queue(queued_executor, settings):
    user = User.objects.create_user(username='t09-unconfigured', password='synthetic-password')
    client = _client(user)

    missing_model = _submit(client)
    assert missing_model.status_code == 409
    assert missing_model.json()['error_code'] == 'model_not_configured'
    assert ResearchRun.objects.count() == 0
    assert not queued_executor

    _verified_research_model(user, tools='unknown')
    unsupported = _submit(client, key='t09-unverified-tools')
    assert unsupported.status_code == 409
    assert unsupported.json()['error_code'] == 'research_tools_unverified'
    assert ResearchRun.objects.count() == 0
    assert not queued_executor

    model = UserAIModelConfig.objects.filter(connection__user=user).first()
    model.capability_snapshot['tools'] = 'supported'
    model.save(update_fields=['capability_snapshot'])
    settings.AI_BYOK_GATEWAY_URL = ''
    no_gateway = _submit(client, key='t09-no-gateway')
    assert no_gateway.status_code == 503
    assert no_gateway.json()['error_code'] == 'gateway_unavailable'
    assert ResearchRun.objects.count() == 0
    assert not queued_executor


@pytest.mark.django_db(transaction=True)
def test_worker_uses_frozen_byok_model_tool_persists_and_commits_full_report(
    queued_executor, monkeypatch,
):
    user = User.objects.create_user(username='t09-worker-success', password='synthetic-password')
    _verified_research_model(user)
    client = _client(user)
    response = _submit(client)
    assert response.status_code == 200
    run = ResearchRun.objects.get(pk=response['Run-ID'])
    response.close()

    stored_snapshot = json.dumps(run.execution_snapshot, sort_keys=True)
    assert PROVIDER_KEY not in stored_snapshot
    assert run.execution_snapshot['execution']['task_kind'] == 'deep_research'
    assert run.execution_snapshot['catalog_model_id'] == 'deepseek-flash'

    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return _completion(
                    tool_calls=[_tool_call()],
                    finish_reason='tool_calls',
                )
            return _completion(
                text='## 合成研究报告\n\n核心摘要：受控上游完整结束。',
                finish_reason='stop',
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )

    @contextmanager
    def open_fake_proxy():
        yield fake_client

    monkeypatch.setattr(
        'api.services.research.byok_execution.open_proxy_client', open_fake_proxy,
    )
    monkeypatch.setattr(
        'api.services.research.agent_loop.get_clients',
        lambda: pytest.fail('BYOK research must not use subscription/platform clients'),
    )
    monkeypatch.setattr(
        'api.services.research.tools._tool_search_news',
        lambda query, **_kwargs: {
            'query': query,
            'mode': 'keyword',
            'total': 1,
            'articles': [],
        },
    )

    _run_submitted_worker(queued_executor)

    run.refresh_from_db()
    run.session.refresh_from_db()
    assert run.status == 'succeeded'
    assert run.error_code == ''
    assert run.session.messages[-1]['content'].startswith('## 合成研究报告')
    assert len(calls) == 2
    assert all(call['model'] == 'news.deepseek-flash' for call in calls)
    assert all(call['extra_body'] == {'api_key': PROVIDER_KEY} for call in calls)
    assert all(call['tool_choice'] == 'auto' for call in calls)
    assert ResearchSearchResult.objects.filter(session=run.session, tool_name='search_news').count() == 1

    events = list(ResearchRunEvent.objects.filter(run=run).order_by('sequence'))
    assert [event.event_type for event in events] == [
        'thinking', 'tool_call', 'tool_result', 'thinking', 'text_delta', 'complete',
    ]
    event_data = json.dumps([event.data for event in events], ensure_ascii=False)
    assert PROVIDER_KEY not in event_data
    assert events[-1].sequence == run.last_event_sequence
    saved_report = client.get(reverse('research-session-detail', args=[run.session_id]))
    assert saved_report.status_code == 200
    assert saved_report['Cache-Control'] == 'no-store'
    assert saved_report.json()['messages'][-1]['content'].startswith('## 合成研究报告')
    assert PROVIDER_KEY not in json.dumps(saved_report.json(), ensure_ascii=False)


@pytest.mark.django_db(transaction=True)
def test_byok_idempotency_reuses_same_snapshot_and_conflicts_after_model_change(queued_executor):
    user = User.objects.create_user(username='t09-idempotency-owner', password='synthetic-password')
    first_connection, first_model = _verified_research_model(user)
    client = _client(user)

    first = _submit(client, query='idempotent research', key='t09-snapshot-idempotency')
    assert first.status_code == 200
    first_run_id = first['Run-ID']
    first.close()
    same_request = _submit(client, query='idempotent research', key='t09-snapshot-idempotency')
    assert same_request.status_code == 200
    assert same_request['Run-ID'] == first_run_id
    same_request.close()
    assert len(queued_executor) == 1

    second_connection, second_model = _verified_research_model(
        user,
        display_name='T09 alternate connection',
    )
    assert second_connection.pk != first_connection.pk
    assert second_model.pk != first_model.pk

    changed_snapshot = _submit(client, query='idempotent research', key='t09-snapshot-idempotency')
    assert changed_snapshot.status_code == 409
    assert changed_snapshot.json()['error_code'] == 'idempotency_key_reused'
    assert len(queued_executor) == 1
    assert ResearchRun.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_rotated_key_stops_queued_run_before_proxy_client_or_tool(monkeypatch, queued_executor):
    user = User.objects.create_user(username='t09-worker-stale', password='synthetic-password')
    connection, _model = _verified_research_model(user)
    response = _submit(_client(user), key='t09-stale-key')
    assert response.status_code == 200
    run = ResearchRun.objects.get(pk=response['Run-ID'])
    response.close()

    connection.credential_epoch += 1
    connection.save(update_fields=['credential_epoch', 'updated_at'])
    proxy_opened = []
    monkeypatch.setattr(
        'api.services.research.byok_execution.open_proxy_client',
        lambda: proxy_opened.append('opened'),
    )

    _run_submitted_worker(queued_executor)

    run.refresh_from_db()
    assert run.status == 'failed'
    assert run.error_code == 'execution_changed'
    assert proxy_opened == []
    assert run.session.messages == []
    assert not ResearchRunEvent.objects.filter(run=run, event_type='complete').exists()


@pytest.mark.django_db(transaction=True)
def test_tool_result_write_failure_cannot_commit_succeeded(queued_executor, monkeypatch):
    user = User.objects.create_user(username='t09-tool-write-failure', password='synthetic-password')
    _verified_research_model(user)
    response = _submit(_client(user), key='t09-tool-write-failure')
    assert response.status_code == 200
    run = ResearchRun.objects.get(pk=response['Run-ID'])
    response.close()

    class FakeCompletions:
        def create(self, **_kwargs):
            return _completion(tool_calls=[_tool_call()], finish_reason='tool_calls')

    @contextmanager
    def open_fake_proxy():
        yield SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    monkeypatch.setattr(
        'api.services.research.byok_execution.open_proxy_client', open_fake_proxy,
    )
    monkeypatch.setattr(
        'api.services.research.tools._tool_search_news',
        lambda query, **_kwargs: {'query': query, 'mode': 'keyword', 'total': 1, 'articles': []},
    )
    monkeypatch.setattr(
        job_manager,
        '_persist_tool_result',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('synthetic database write failure')),
    )

    _run_submitted_worker(queued_executor)

    run.refresh_from_db()
    assert run.status == 'failed'
    assert run.error_code == 'research_failed'
    assert run.session.messages == []
    assert not ResearchRunEvent.objects.filter(run=run, event_type='complete').exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ('tool_name', 'arguments'),
    [
        ('run_shell', '{"command":"do not execute"}'),
        ('search_news', '{"query":3,"mode":"keyword"}'),
        ('search_news', '{bad json'),
    ],
)
def test_untrusted_tool_name_and_arguments_are_rejected_before_execution(
    tool_name, arguments, queued_executor, monkeypatch,
):
    user = User.objects.create_user(username=f't09-invalid-{len(tool_name)}-{len(arguments)}', password='synthetic-password')
    _verified_research_model(user)
    response = _submit(_client(user), key=f't09-invalid-{len(tool_name)}-{len(arguments)}')
    assert response.status_code == 200
    run = ResearchRun.objects.get(pk=response['Run-ID'])
    response.close()

    class FakeCompletions:
        def create(self, **_kwargs):
            return _completion(
                tool_calls=[_tool_call(tool_name, arguments)],
                finish_reason='tool_calls',
            )

    @contextmanager
    def open_fake_proxy():
        yield SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    executed = []
    monkeypatch.setattr(
        'api.services.research.byok_execution.open_proxy_client', open_fake_proxy,
    )
    monkeypatch.setattr(
        'api.services.research.tools._tool_search_news',
        lambda *_args, **_kwargs: executed.append('search_news'),
    )

    _run_submitted_worker(queued_executor)

    run.refresh_from_db()
    assert run.status == 'failed'
    assert executed == []
    assert not ResearchRunEvent.objects.filter(run=run, event_type='tool_call').exists()
    assert not ResearchRunEvent.objects.filter(run=run, event_type='complete').exists()


@pytest.mark.django_db(transaction=True)
def test_production_research_allows_only_explicit_byok_model_path(queued_executor, settings):
    settings.DJANGO_ENV = 'production'
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    user = User.objects.create_user(username='t09-production-byok', password='synthetic-password')
    client = _client(user)

    settings.AI_BYOK_ENABLED = False
    blocked = _submit(client, key='t09-production-disabled')
    assert blocked.status_code == 503
    assert blocked.json()['error_code'] == 'hosted_integration_unapproved'
    assert ResearchRun.objects.count() == 0

    settings.AI_BYOK_ENABLED = True
    settings.PUBLIC_AI_ENABLED = False
    no_model = _submit(client, key='t09-production-no-model')
    assert no_model.status_code == 409
    assert no_model.json()['error_code'] == 'model_not_configured'
    assert ResearchRun.objects.count() == 0

    _verified_research_model(user)
    allowed = _submit(client, key='t09-production-valid-byok')
    assert allowed.status_code == 200
    queued = ResearchRun.objects.get(pk=allowed['Run-ID'])
    assert queued.execution_snapshot['execution']['user_id'] == user.pk
    assert queued.execution_snapshot['execution']['task_kind'] == 'deep_research'
    assert queued.status == 'queued'
    allowed.close()


@pytest.mark.django_db(transaction=True)
def test_byok_research_policy_bypass_still_requires_session_csrf(queued_executor):
    user = User.objects.create_user(username='t09-csrf-owner', password='synthetic-password')
    _verified_research_model(user)
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)

    missing_token = _submit(client, key='t09-csrf-missing')
    assert missing_token.status_code == 403
    assert ResearchRun.objects.count() == 0
    assert not queued_executor

    token_response = client.get(reverse('auth-csrf'))
    token = token_response.cookies['csrftoken'].value
    invalid_token = client.post(
        reverse('research-create'),
        {'query': 'CSRF must still be checked', 'local_only': True},
        format='json',
        HTTP_X_CSRFTOKEN='invalid-token',
        HTTP_IDEMPOTENCY_KEY='t09-csrf-invalid',
    )
    assert invalid_token.status_code == 403
    assert ResearchRun.objects.count() == 0

    accepted = client.post(
        reverse('research-create'),
        {'query': 'CSRF must still be checked', 'local_only': True},
        format='json',
        HTTP_X_CSRFTOKEN=token,
        HTTP_IDEMPOTENCY_KEY='t09-csrf-valid',
    )
    assert accepted.status_code == 200
    assert ResearchRun.objects.filter(user=user).count() == 1
    assert len(queued_executor) == 1
    accepted.close()
