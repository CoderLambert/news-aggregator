"""Synthetic contracts for ChatGPT Subscription deep-research execution."""
import json
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import (
    ChatGPTSubscriptionCapabilityReceipt,
    ChatGPTSubscriptionConnection,
    ResearchRun,
    ResearchSession,
)
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_llm as subscription_llm
from api.services.ai_task_preferences import (
    ModelSelectionError,
    read_preferences,
    save_preferences,
)
from api.services.research import agent_loop, job_manager, subscription_execution

User = get_user_model()


class FakeStreamResponse:
    def __init__(self, completed, streamed_items=()):
        self.status_code = 200
        self._completed = completed
        self._streamed_items = tuple(streamed_items)
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        for output_index, item in enumerate(self._streamed_items):
            yield 'event: response.output_item.done'
            yield 'data: ' + json.dumps({
                'type': 'response.output_item.done',
                'output_index': output_index,
                'item': item,
            })
        yield 'event: response.completed'
        yield 'data: ' + json.dumps({
            'type': 'response.completed', 'response': self._completed,
        })

    def close(self):
        self.closed = True


def make_connection(
    user, *, generation=3, model_slug='subscription-research-model',
    is_active=True,
):
    marker = uuid.uuid4().hex
    return ChatGPTSubscriptionConnection.objects.create(
        user=user,
        subject_hash=f'subject-{marker}',
        issuer='https://auth.example',
        issued_client_id=f'client-{marker}',
        registration_key_hash=f'registration-{marker}',
        encrypted_subject='synthetic-subject',
        granted_scopes=[subscription.REQUIRED_DIRECT_SCOPE],
        account_name='Synthetic subscription',
        account_email='synthetic@example.com',
        encrypted_access_token='synthetic-access',
        encrypted_refresh_token='synthetic-refresh',
        encrypted_id_token='synthetic-id',
        access_token_expires_at=timezone.now() + timedelta(hours=1),
        selected_model=model_slug,
        is_active=is_active,
        needs_reauth=False,
        generation=generation,
    )


def completed_tool_call(name, call_id, arguments):
    return {
        'status': 'completed',
        'error': None,
        'incomplete_details': None,
        'output': [{
            'type': 'function_call', 'status': 'completed',
            'call_id': call_id, 'name': name,
            'arguments': json.dumps(arguments),
        }],
    }


def completed_text(text):
    return {
        'status': 'completed',
        'error': None,
        'incomplete_details': None,
        'output': [{
            'type': 'message', 'status': 'completed', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': text}],
        }],
    }


@pytest.mark.django_db
def test_subscription_native_tool_transport_is_streamed_stateless_and_fenced(monkeypatch):
    user = User.objects.create_user(username='subscription-transport')
    connection = make_connection(user)
    snapshot = subscription_llm.snapshot_for_connection(connection)
    completed = completed_tool_call('search_news', 'call-1', {'query': 'chips'})
    response = FakeStreamResponse(completed)
    posted = {}

    monkeypatch.setattr(subscription, 'access_token_for', lambda *args, **kwargs: 'synthetic-token')

    def post(url, **kwargs):
        posted.update({'url': url, **kwargs})
        return response

    monkeypatch.setattr(subscription_llm.requests, 'post', post)
    result = subscription_llm.complete_response(
        snapshot,
        [{'role': 'developer', 'content': 'Use one local tool.'}],
        tools=[{
            'type': 'function', 'name': 'search_news', 'description': 'Search',
            'parameters': {'type': 'object'}, 'strict': False,
        }],
        tool_choice='auto',
    )

    assert result == completed
    assert response.closed is True
    assert posted['url'] == subscription.RESPONSES_URL
    assert posted['stream'] is True
    assert posted['json'] == {
        'model': connection.selected_model,
        'input': [{'role': 'developer', 'content': 'Use one local tool.'}],
        'store': False,
        'stream': True,
        'tools': [{
            'type': 'function', 'name': 'search_news', 'description': 'Search',
            'parameters': {'type': 'object'}, 'strict': False,
        }],
        'tool_choice': 'auto',
    }
    assert not ({'temperature', 'max_tokens', 'max_output_tokens', 'previous_response_id'} & posted['json'].keys())

@pytest.mark.django_db
def test_subscription_transport_reconstructs_output_from_completed_item_events(monkeypatch):
    user = User.objects.create_user(username='subscription-stream-items')
    connection = make_connection(user)
    snapshot = subscription_llm.snapshot_for_connection(connection)
    item = completed_tool_call(
        'search_news', 'call-1', {'query': 'chips'},
    )['output'][0]
    completed = {
        'status': 'completed', 'error': None,
        'incomplete_details': None, 'output': [],
    }
    response = FakeStreamResponse(completed, [item])
    monkeypatch.setattr(
        subscription, 'access_token_for',
        lambda *args, **kwargs: 'synthetic-token',
    )
    monkeypatch.setattr(
        subscription_llm.requests, 'post',
        lambda *args, **kwargs: response,
    )

    result = subscription_llm.complete_response(
        snapshot,
        [{'role': 'developer', 'content': 'Use one local tool.'}],
        tools=[{
            'type': 'function', 'name': 'search_news',
            'description': 'Search', 'parameters': {'type': 'object'},
            'strict': False,
        }],
        tool_choice={'type': 'function', 'name': 'search_news'},
    )

    assert result == {**completed, 'output': [item]}
    assert response.closed is True


@pytest.mark.django_db
def test_probe_receipt_makes_only_the_current_subscription_model_research_eligible(monkeypatch):
    user = User.objects.create_user(username='subscription-probe')
    connection = make_connection(user)
    seen = {}

    def complete(_snapshot, input_items, **kwargs):
        seen.update({'input': input_items, **kwargs})
        return completed_tool_call(
            subscription_execution.PROBE_TOOL_NAME,
            'probe-call',
            {'supported': True},
        )

    monkeypatch.setattr(subscription_execution, 'complete_response', complete)
    receipt = subscription_execution.probe_tools(connection, consent=True)

    assert receipt['status'] == 'supported'
    assert receipt['model_slug'] == connection.selected_model
    assert seen['tool_choice'] == {
        'type': 'function', 'name': subscription_execution.PROBE_TOOL_NAME,
    }
    stored = ChatGPTSubscriptionCapabilityReceipt.objects.get(pk=receipt['id'])
    assert stored.connection_generation == connection.generation
    assert read_preferences(user)['subscription']['research_eligible'] is True

    connection.selected_model = 'different-model'
    connection.save(update_fields=['selected_model', 'updated_at'])
    assert read_preferences(user)['subscription']['research_eligible'] is False

@pytest.mark.django_db
def test_probe_never_spends_on_a_new_active_connection_after_target_check(monkeypatch):
    user = User.objects.create_user(username='subscription-probe-switch')
    requested = make_connection(user)
    replacement = make_connection(
        user, model_slug='replacement-model', is_active=False,
    )
    active_connection = subscription.active_connection_for_user
    switched = False
    provider_calls = []

    def switch_after_lookup(owner):
        nonlocal switched
        selected = active_connection(owner)
        if not switched:
            ChatGPTSubscriptionConnection.objects.filter(pk=requested.pk).update(
                is_active=False,
            )
            ChatGPTSubscriptionConnection.objects.filter(pk=replacement.pk).update(
                is_active=True,
            )
            switched = True
        return selected

    monkeypatch.setattr(
        subscription, 'active_connection_for_user', switch_after_lookup,
    )
    monkeypatch.setattr(
        subscription, 'access_token_for',
        lambda *args, **kwargs: 'synthetic-token',
    )

    def post(*args, **kwargs):
        provider_calls.append((args, kwargs))
        return FakeStreamResponse(completed_tool_call(
            subscription_execution.PROBE_TOOL_NAME,
            'unexpected-probe-call',
            {'supported': True},
        ))

    monkeypatch.setattr(subscription_llm.requests, 'post', post)
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        reverse(
            'chatgpt-subscription-research-probe',
            kwargs={'connection_id': requested.pk},
        ),
        {'consent': True},
        format='json',
    )

    assert response.status_code == 400
    assert provider_calls == []
    assert ChatGPTSubscriptionCapabilityReceipt.objects.count() == 0


@pytest.mark.django_db
def test_unsupported_subscription_tool_probe_stays_fail_closed(monkeypatch):
    user = User.objects.create_user(username='subscription-unsupported')
    connection = make_connection(user)

    def unsupported(*args, **kwargs):
        raise subscription.SubscriptionError(
            'unsupported', 'subscription_sharing_unsupported_capability', 400,
        )

    monkeypatch.setattr(subscription_execution, 'complete_response', unsupported)
    receipt = subscription_execution.probe_tools(connection, consent=True)

    assert receipt['status'] == 'unsupported'
    assert ChatGPTSubscriptionCapabilityReceipt.objects.get(
        pk=receipt['id'],
    ).safe_error_code == 'subscription_sharing_unsupported_capability'
    assert subscription_execution.tools_supported(connection) is False
    assert read_preferences(user)['subscription']['research_eligible'] is False


@pytest.mark.django_db
def test_subscription_research_preference_requires_current_supported_receipt():
    user = User.objects.create_user(username='subscription-preference')
    connection = make_connection(user)
    entries = [
        {
            'task_kind': kind,
            'selection_source': (
                'unset' if kind == 'default'
                else 'chatgpt_subscription' if kind == 'deep_research'
                else 'inherit'
            ),
            'model_config_id': None,
        }
        for kind in (
            'default', 'article_qa', 'full_translation',
            'deep_research', 'question_suggestions',
        )
    ]

    with pytest.raises(ModelSelectionError) as rejected:
        save_preferences(user, 0, entries)
    assert rejected.value.code == 'model_not_verified'

    ChatGPTSubscriptionCapabilityReceipt.objects.create(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        credential_generation=connection.credential_generation,
        capability='tools',
        status='supported',
    )
    saved = save_preferences(user, 0, entries)
    research = next(
        row for row in saved['preferences'] if row['task_kind'] == 'deep_research'
    )
    assert research['selection_source'] == 'chatgpt_subscription'
    assert research['selection_state'] == 'available'


@pytest.mark.django_db(transaction=True)
def test_subscription_research_admission_is_explicit_and_never_falls_back_to_byok(monkeypatch):
    user = User.objects.create_user(username='subscription-admission')
    connection = make_connection(user)
    receipt = ChatGPTSubscriptionCapabilityReceipt.objects.create(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        credential_generation=connection.credential_generation,
        capability='tools',
        status='supported',
    )
    client = APIClient()
    client.force_authenticate(user)
    dispatched = []
    monkeypatch.setattr(
        'api.services.research.job_manager._dispatch',
        lambda run_id, query, local_only: dispatched.append((run_id, query, local_only)),
    )

    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False,
        AI_BYOK_ENABLED=False, DJANGO_ENV='development',
        CHATGPT_AUTH_MODE='local_oss', CHATGPT_PLAN_USAGE_ENABLED=True,
    ):
        from api.capabilities_views import _feature_snapshot
        assert _feature_snapshot()['research_byok_create']['enabled'] is True
        response = client.post('/api/research/', {
            'query': 'Research with my subscription',
            'execution_source': 'chatgpt_subscription',
            'consent': True,
        }, format='json', HTTP_IDEMPOTENCY_KEY='subscription-research-request')

    assert response.status_code == 200, response.data if hasattr(response, 'data') else response
    run = ResearchRun.objects.get()
    assert run.execution_snapshot == {
        'schema_version': 1,
        'source': 'chatgpt_subscription',
        'consent': True,
        'subscription': {
            'user_id': user.pk,
            'connection_id': str(connection.pk),
            'connection_generation': connection.generation,
            'model_slug': connection.selected_model,
            'receipt_id': str(receipt.pk),
        },
    }
    assert dispatched == [(run.pk, 'Research with my subscription', False)]


@pytest.mark.django_db
def test_subscription_queued_run_resume_uses_source_neutral_snapshot_verifier(monkeypatch):
    user = User.objects.create_user(username='subscription-queued-resume')
    connection = make_connection(user)
    receipt = ChatGPTSubscriptionCapabilityReceipt.objects.create(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        credential_generation=connection.credential_generation,
        capability='tools',
        status='supported',
    )
    snapshot = subscription_execution.capture_snapshot(user)
    session = ResearchSession.objects.create(user=user, title='', messages=[])
    run = ResearchRun.objects.create(
        user=user,
        session=session,
        idempotency_key='subscription-queued-resume',
        request_hash=job_manager.request_digest(
            'Resume subscription research', False, None,
            execution_source='chatgpt_subscription', consent=True,
        ),
        status='queued',
        queued_query='Resume subscription research',
        queued_local_only=False,
        execution_snapshot=snapshot,
    )
    dispatched = []
    monkeypatch.setattr(
        job_manager, '_dispatch',
        lambda run_id, query, local_only: dispatched.append((run_id, query, local_only)),
    )

    resumed = job_manager.resume_queued_run(user, session, str(run.pk))

    assert resumed.pk == run.pk
    assert dispatched == [(run.pk, 'Resume subscription research', False)]
    assert snapshot['subscription']['receipt_id'] == str(receipt.pk)


@pytest.mark.django_db
def test_subscription_queued_run_resume_rejects_a_changed_connection(monkeypatch):
    user = User.objects.create_user(username='subscription-queued-stale')
    connection = make_connection(user)
    ChatGPTSubscriptionCapabilityReceipt.objects.create(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        credential_generation=connection.credential_generation,
        capability='tools',
        status='supported',
    )
    snapshot = subscription_execution.capture_snapshot(user)
    session = ResearchSession.objects.create(user=user, title='', messages=[])
    run = ResearchRun.objects.create(
        user=user,
        session=session,
        idempotency_key='subscription-queued-stale',
        request_hash=job_manager.request_digest(
            'Reject stale subscription research', False, None,
            execution_source='chatgpt_subscription', consent=True,
        ),
        status='queued',
        queued_query='Reject stale subscription research',
        queued_local_only=False,
        execution_snapshot=snapshot,
    )
    ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(
        generation=connection.generation + 1,
    )
    dispatched = []
    monkeypatch.setattr(job_manager, '_dispatch', lambda *args: dispatched.append(args))

    with pytest.raises(job_manager.ResearchRunError) as rejected:
        job_manager.resume_queued_run(user, session, str(run.pk))

    assert rejected.value.error_code == 'research_authorization_changed'
    assert dispatched == []


@pytest.mark.django_db
def test_subscription_followup_admission_failure_certifies_that_no_run_was_created():
    user = User.objects.create_user(username='subscription-followup-stale')
    connection = make_connection(user)
    ChatGPTSubscriptionCapabilityReceipt.objects.create(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        credential_generation=connection.credential_generation,
        capability='tools',
        status='supported',
    )
    snapshot = subscription_execution.capture_snapshot(user)
    native_messages = [
        {'role': 'user', 'content': 'Original research'},
        {'role': 'assistant', 'content': 'Original result'},
    ]
    session = ResearchSession.objects.create(
        user=user,
        title='Original research',
        messages=native_messages,
        native_continuation=subscription_execution.continuation_payload(
            snapshot, native_messages,
        ),
    )
    ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(
        generation=connection.generation + 1,
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        f'/api/research/{session.pk}/chat/',
        {
            'query': 'Follow up after authorization changed',
            'execution_source': 'chatgpt_subscription',
            'consent': True,
        },
        format='json',
        HTTP_IDEMPOTENCY_KEY='subscription-followup-stale',
    )

    assert response.status_code == 409
    assert response.data['error_code'] == 'research_authorization_changed'
    assert response.data['request_state'] == 'rejected'
    assert ResearchRun.objects.filter(user=user, session=session).count() == 0


@pytest.mark.django_db
def test_subscription_agent_executes_local_tool_then_replays_native_items(monkeypatch):
    user = User.objects.create_user(username='subscription-agent')
    connection = make_connection(user)
    receipt = ChatGPTSubscriptionCapabilityReceipt.objects.create(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        credential_generation=connection.credential_generation,
        capability='tools',
        status='supported',
    )
    snapshot = subscription_execution.capture_snapshot(user)
    assert snapshot['subscription']['receipt_id'] == str(receipt.pk)
    session = ResearchSession.objects.create(user=user, title='', messages=[])
    responses = iter([
        completed_tool_call('search_news', 'call-1', {'query': 'chips'}),
        completed_text('Verified report'),
    ])
    requests = []

    def complete(_snapshot, input_items, **kwargs):
        requests.append(input_items)
        return next(responses)

    monkeypatch.setattr(subscription_execution, 'complete_response', complete)
    monkeypatch.setattr(
        agent_loop,
        'execute_tool',
        lambda name, args, **kwargs: {'articles': [], 'query': args['query']},
    )
    persisted = []
    events = []
    agent_loop.run_agent_loop(
        session,
        'Analyze chips',
        lambda kind, data: events.append((kind, data)),
        user=user,
        execution_snapshot=snapshot,
        execution_guard=lambda: None,
        persist_tool_result=lambda *args, **kwargs: None,
        persist_completion=lambda messages: persisted.append(messages),
    )

    assert [kind for kind, _ in events].count('tool_call') == 1
    assert events[-1][0] == 'complete'
    assert len(requests) == 2
    assert any(item.get('type') == 'function_call_output' for item in requests[1])
    assert persisted[0][-1]['content'] == 'Verified report'
    continuation = subscription_execution.continuation_payload(snapshot, persisted[0])
    session.native_continuation = continuation
    assert subscription_execution.native_messages(session, snapshot) == persisted[0]
