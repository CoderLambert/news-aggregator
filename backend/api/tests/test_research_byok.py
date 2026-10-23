"""T09 fake-only contracts for BYOK research admission and tool safety."""
import json
import uuid
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from api.models import ResearchRun, ResearchSession
from api.public_policy import PublicPolicyMiddleware
from api.services.research import job_manager
from api.services.research import agent_loop
from api.services.research.byok_execution import (
    ResearchBYOKError, decode_snapshot, validate_tool_batch,
)
from api.services.research.execution import ResearchExecutionError
from api.services.research.tools import TOOLS

User = get_user_model()


def _request_for_route(url_name, path='/api/research/'):
    request = RequestFactory().post(path, data='{"query":"private"}', content_type='application/json')
    request.resolver_match = SimpleNamespace(url_name=url_name)
    return request



def test_research_byok_create_capability_is_narrow_and_independent_of_public_ai():
    from api.capabilities_views import _feature_snapshot

    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=True,
        DJANGO_ENV='production',
    ):
        features = _feature_snapshot()
        assert features['research']['enabled'] is False
        assert features['research_byok_create']['enabled'] is True
        assert features['translation']['enabled'] is False

    with override_settings(
        PUBLIC_SITE_MODE='read_only', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=True,
        DJANGO_ENV='production',
    ):
        assert _feature_snapshot()['research_byok_create']['enabled'] is False

    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=False,
        CHATGPT_AUTH_MODE='disabled', DJANGO_ENV='development',
    ):
        assert _feature_snapshot()['research_byok_create']['enabled'] is False

def test_byok_public_policy_allows_only_explicit_research_write_routes():
    middleware = PublicPolicyMiddleware(lambda request: None)
    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=True,
        DJANGO_ENV='production',
    ):
        allowed = middleware.process_view(
            _request_for_route('research-create'), lambda: None, (), {},
        )
        assert allowed is None

        chat = middleware.process_view(
            _request_for_route('research-chat', '/api/research/00000000-0000-0000-0000-000000000001/chat/'),
            lambda: None, (), {},
        )
        assert chat is None  # T10 validates per-turn authorization in the view/service.

        other_ai = middleware.process_view(
            _request_for_route('news-chat', '/api/news/1/chat/'), lambda: None, (), {},
        )
        assert other_ai.status_code == 403
        assert json.loads(other_ai.content)['error_code'] == 'ai_disabled'

    with override_settings(
        PUBLIC_SITE_MODE='read_only', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=True,
        DJANGO_ENV='production',
    ):
        readonly = middleware.process_view(
            _request_for_route('research-create'), lambda: None, (), {},
        )
        assert readonly.status_code == 403
        assert json.loads(readonly.content)['error_code'] == 'public_read_only'

    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=False,
        DJANGO_ENV='production',
    ):
        disabled = middleware.process_view(
            _request_for_route('research-create'), lambda: None, (), {},
        )
        assert disabled.status_code == 403
        assert json.loads(disabled.content)['error_code'] == 'ai_disabled'


@pytest.mark.django_db(transaction=True)
def test_t09_production_requires_literal_consent_and_current_verified_model():
    owner = User.objects.create_user(username='t09-owner', password='not-used')
    client = APIClient()
    client.force_authenticate(owner)
    model_config_id = str(uuid.uuid4())

    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=True,
        DJANGO_ENV='production',
    ):
        missing_consent = client.post('/api/research/', {
            'query': 'test missing consent', 'execution_source': 'byok',
            'model_config_id': model_config_id,
        }, format='json')
        assert missing_consent.status_code == 400
        assert missing_consent.data['error_code'] == 'research_consent_required'
        assert not ResearchRun.objects.exists()
        assert not ResearchSession.objects.exists()

        missing_model = client.post('/api/research/', {
            'query': 'test no configured model', 'execution_source': 'byok',
            'model_config_id': model_config_id, 'consent': True,
        }, format='json')
        assert missing_model.status_code == 409
        assert missing_model.data['error_code'] == 'research_model_unavailable'
        assert not ResearchRun.objects.exists()
        assert not ResearchSession.objects.exists()

        shared_path = client.post('/api/research/', {
            'query': 'must not reach shared hosted execution',
        }, format='json')
        assert shared_path.status_code == 403
        assert shared_path.data['error_code'] == 'ai_disabled'
        assert not ResearchRun.objects.exists()
        assert not ResearchSession.objects.exists()

        with override_settings(PUBLIC_AI_ENABLED=True):
            shared_path = client.post('/api/research/', {
                'query': 'must not reach unapproved hosted execution',
            }, format='json')
        assert shared_path.status_code == 503
        assert shared_path.data['error_code'] == 'hosted_integration_unapproved'
        assert not ResearchSession.objects.exists()
        assert not ResearchRun.objects.exists()



@pytest.mark.django_db(transaction=True)
def test_t09_public_ai_disabled_without_byok_is_rejected_in_development():
    owner = User.objects.create_user(username='t09-disabled-owner', password='not-used')
    client = APIClient()
    client.force_authenticate(owner)
    with override_settings(
        PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=False, AI_BYOK_ENABLED=True,
        DJANGO_ENV='development',
    ):
        response = client.post('/api/research/', {
            'query': 'must not use shared research',
        }, format='json')
    assert response.status_code == 403
    assert response.data['error_code'] == 'ai_disabled'
    assert not ResearchRun.objects.exists()
    assert not ResearchSession.objects.exists()


@pytest.mark.django_db
def test_t09_idempotent_replay_keeps_saved_run_and_fences_stale_queued_snapshot(monkeypatch):
    owner = User.objects.create_user(username='t09-replay-owner', password='not-used')
    session = ResearchSession.objects.create(
        user=owner, title='Saved result', messages=[{'role': 'assistant', 'content': 'Saved report'}],
    )
    terminal = ResearchRun.objects.create(
        user=owner, session=session, idempotency_key='same-key', request_hash='same-request',
        status='succeeded', execution_snapshot={'schema_version': 1},
    )
    monkeypatch.setattr(
        'api.services.research.byok_execution.verify_snapshot',
        lambda *args, **kwargs: pytest.fail('terminal readback must not reauthorize or redispatch'),
    )
    attached_session, attached_run = job_manager._attach_existing(
        terminal, 'same-request', 'same query', False,
    )
    assert attached_session.pk == session.pk
    assert attached_run.pk == terminal.pk
    with pytest.raises(job_manager.ResearchRunError) as changed:
        job_manager._attach_existing(terminal, 'changed-model-or-consent', 'same query', False)
    assert changed.value.error_code == 'idempotency_key_reused'

    queued = ResearchRun.objects.create(
        user=owner, session=session, idempotency_key='queued-key', request_hash='queued-request',
        status='queued', queued_query='same query', execution_snapshot={'schema_version': 1},
    )
    def stale_snapshot(*args, **kwargs):
        raise ResearchBYOKError('authorization_changed')
    monkeypatch.setattr('api.services.research.byok_execution.verify_snapshot', stale_snapshot)
    monkeypatch.setattr(
        job_manager, '_dispatch',
        lambda *args, **kwargs: pytest.fail('stale stored authorization must never be redispatched'),
    )
    with pytest.raises(job_manager.ResearchRunError) as stale:
        job_manager._attach_existing(queued, 'queued-request', 'same query', False)
    assert stale.value.error_code == 'research_authorization_changed'


def _tool_call(name, raw_arguments, call_id='call-1'):
    return SimpleNamespace(
        id=call_id, type='function',
        function=SimpleNamespace(name=name, arguments=raw_arguments),
    )


@pytest.mark.parametrize('raw_arguments', [
    '{"query":"x","limit":"not-an-integer"}',
    '{"query":"x","query":"second"}',
    '{"query":"x","unexpected":true}',
    '{"query":NaN}',
])
def test_t09_tool_arguments_are_strict_json_and_schema_validated(raw_arguments):
    search_news = next(tool for tool in TOOLS if tool['function']['name'] == 'search_news')
    call = _tool_call('search_news', raw_arguments)
    with pytest.raises(ResearchBYOKError) as rejected:
        validate_tool_batch([call], [search_news])
    assert rejected.value.code == 'invalid_tool_call'


@pytest.mark.django_db
def test_t09_validates_entire_tool_batch_before_first_tool_side_effect(monkeypatch):
    owner = User.objects.create_user(username='t09-batch-owner', password='not-used')
    session = ResearchSession.objects.create(user=owner, messages=[])
    valid = _tool_call('search_news', '{"query":"safe query"}', 'call-valid')
    invalid = _tool_call('site_admin_secret', '{"query":"x"}', 'call-invalid')
    message = SimpleNamespace(content=None, tool_calls=[valid, invalid])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason='tool_calls')])
    monkeypatch.setattr(
        'api.services.research.byok_execution.call_model_once',
        lambda *args, **kwargs: response,
    )
    side_effects = []
    monkeypatch.setattr(
        agent_loop, 'execute_tool',
        lambda *args, **kwargs: side_effects.append(args) or {'total': 1},
    )
    events = []

    with pytest.raises(ResearchExecutionError) as rejected:
        agent_loop.run_agent_loop(
            session, 'query', lambda event, data: events.append((event, data)),
            local_only=True, execution_guard=lambda: None,
            persist_completion=lambda messages: side_effects.append('completed'),
            persist_tool_result=lambda *args: side_effects.append('persisted'),
            user=owner,
            execution_snapshot={'schema_version': 1, 'consent': True, 'model': {}},
        )

    assert rejected.value.code == 'invalid_tool_call'
    assert side_effects == []
    assert not any(event == 'tool_call' for event, _data in events)
    assert not any(event in {'tool_result', 'complete'} for event, _data in events)


@pytest.mark.django_db
def test_t09_failed_tool_write_cannot_emit_result_or_succeeded_completion(monkeypatch):
    owner = User.objects.create_user(username='t09-tool-error-owner', password='not-used')
    session = ResearchSession.objects.create(user=owner, messages=[])
    call = _tool_call('search_news', '{"query":"safe query"}')
    message = SimpleNamespace(content=None, tool_calls=[call])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason='tool_calls')])
    monkeypatch.setattr(
        'api.services.research.byok_execution.call_model_once',
        lambda *args, **kwargs: response,
    )
    from api.services.research import tools as research_tools
    monkeypatch.setattr(research_tools, '_tool_search_news', lambda **kwargs: {
        'total': 1, 'articles': [],
    })
    def failed_persistence(*args):
        raise RuntimeError('synthetic persistence failure')
    events = []

    with pytest.raises(ResearchExecutionError) as failed:
        agent_loop.run_agent_loop(
            session, 'query', lambda event, data: events.append((event, data)),
            local_only=True, execution_guard=lambda: None,
            persist_completion=lambda messages: pytest.fail('must not commit report'),
            persist_tool_result=failed_persistence,
            user=owner,
            execution_snapshot={'schema_version': 1, 'consent': True, 'model': {}},
        )

    assert failed.value.code == 'tool_failed'
    assert any(event == 'tool_call' for event, _data in events)
    assert not any(event in {'tool_result', 'complete'} for event, _data in events)


def test_t09_execution_snapshot_is_strict_and_secret_free():
    from api.services.ai_credentials import ConnectionSnapshot
    from api.services.ai_task_preferences import TaskModelSnapshot

    connection = ConnectionSnapshot(
        user_id=17, connection_id='b30d6041-8f49-4f44-8e89-36e6fef9deae',
        credential_epoch=3, credential_version=2, provider_id='deepseek',
        endpoint_profile='deepseek-global', endpoint_profile_version=1,
    )
    selection = TaskModelSnapshot(
        user_id=17, task_kind='deep_research', selected_by='explicit',
        preference_revision=4, model_config_id='dc8beed6-9efb-45ae-aacc-e8b8ce426b7f',
        model_revision=2, model_id='deepseek-chat', proxy_alias='deepseek/deepseek-chat',
        connection=connection, text_attempt_id='d51b6041-8f49-4f44-8e89-36e6fef9deae',
        tools_attempt_id='a55bd664-93a2-4ee7-a164-f17f6cf09aa0',
    )
    payload = {'schema_version': 1, 'consent': True, 'model': asdict(selection)}
    decoded = decode_snapshot(payload, owner_id=17)
    assert decoded == selection
    # auth_mode='api_key' is non-secret metadata, never an api_key field.
    assert 'api_key' not in payload and 'api_key' not in payload['model']
    assert 'api_key' not in payload['model']['connection']
    legacy = json.loads(json.dumps(payload))
    legacy['model']['connection'].pop('auth_mode')
    legacy['model']['connection'].pop('endpoint_policy_digest')
    assert decode_snapshot(legacy, owner_id=17) == selection

    extra = {**payload, 'api_key': 'must never persist'}
    with pytest.raises(ResearchBYOKError):
        decode_snapshot(extra, owner_id=17)
    with pytest.raises(ResearchBYOKError):
        decode_snapshot(payload, owner_id=18)
    without_consent = {**payload, 'consent': 1}
    with pytest.raises(ResearchBYOKError):
        decode_snapshot(without_consent, owner_id=17)


def test_t10_native_continuation_is_model_bound_and_not_visible():
    from api.services.research.byok_execution import (
        continuation_payload, native_messages, visible_messages,
    )
    snapshot = {'model': {'model_config_id': 'original'}}
    messages = [
        {'role': 'user', 'content': 'question'},
        {'role': 'assistant', 'content': '', 'reasoning_content': 'private reasoning',
         'tool_calls': [{'id': 'one', 'type': 'function', 'function': {'name': 'search_news', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'one', 'content': '{"articles": []}'},
        {'role': 'assistant', 'content': 'report', 'reasoning_content': 'native tail'},
    ]
    session = SimpleNamespace(native_continuation=continuation_payload(snapshot, messages))
    restored = native_messages(session, snapshot)
    assert restored == messages
    restored[0]['content'] = 'mutated'
    assert messages[0]['content'] == 'question'
    assert visible_messages(messages) == [
        {'role': 'user', 'content': 'question'}, {'role': 'assistant', 'content': 'report'},
    ]
    with pytest.raises(ResearchBYOKError):
        native_messages(session, {'model': {'model_config_id': 'different'}})
    session.native_continuation['protocol'] = 'other-provider'
    with pytest.raises(ResearchBYOKError):
        native_messages(session, snapshot)


def test_tool_reply_with_text_preface_is_not_a_final_or_visible_answer():
    from api.services.research.byok_execution import _validated_completion, visible_messages
    call = {'id': 'call-preface', 'type': 'function',
            'function': {'name': 'search_news', 'arguments': '{}'}}
    message = {'role': 'assistant', 'content': 'Checking the evidence.', 'tool_calls': [call]}
    response = {'choices': [{'finish_reason': 'tool_calls', 'message': message}]}
    assert _validated_completion(response) == (message, [call])
    assert visible_messages([{'role': 'user', 'content': 'Question'}, message]) == [
        {'role': 'user', 'content': 'Question'}]
    for content in ({'text': 'not a string'}, 2, []):
        with pytest.raises(ResearchBYOKError):
            _validated_completion({'choices': [{'finish_reason': 'tool_calls',
                'message': {**message, 'content': content}}]})


def test_t10_followup_rechecks_owner_and_locked_model(monkeypatch):
    from api.services.research.byok_execution import followup_snapshot, continuation_payload
    snapshot = {'model': {'model_config_id': 'original'}}
    session = SimpleNamespace(user_id=1, native_continuation=continuation_payload(snapshot, []))
    monkeypatch.setattr('api.services.research.byok_execution.verify_snapshot',
                        lambda *args, **kwargs: SimpleNamespace(model_config_id='original'))
    monkeypatch.setattr('api.services.research.access.require_session_evidence', lambda *args: None)
    assert followup_snapshot(session, SimpleNamespace(pk=1), 'original') == snapshot
    with pytest.raises(ResearchBYOKError):
        followup_snapshot(session, SimpleNamespace(pk=2), 'original')
    with pytest.raises(ResearchBYOKError):
        followup_snapshot(session, SimpleNamespace(pk=1), 'different')
