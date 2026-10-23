"""Owner-selected compatible Key/None routes use the same business fences."""
import json
import io
import uuid
from types import SimpleNamespace as N
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.ai_model_models import AICallAttempt, UserAIModelConfig
from api.models import News, Source, Category, ChatSession, ChatGPTTranslationTask, ChatGPTArticleTranslation
from api.services.ai_credentials import snapshot_connection
from api.services.ai_gateway import AIGatewayError, _GatewayCompletions
from api.services.ai_model_capabilities import verified_for_task
from api.services.ai_model_probe import ProbeOutcome, parse_completion, send_model_probe
from api.services.ai_model_registry import get_trusted_route
from api.services.ai_task_preferences import ModelSelectionError, resolve_task_model
from api.tests.test_ai_endpoint_profiles import profile
from api.tests.rss.reader_fixtures import public_legacy_article
from api.tests.test_ai_article_chat_t04 import FakeGateway, gateway_frame

pytestmark = pytest.mark.django_db
BASE = '/api/me/ai/connections/'


@pytest.fixture
def unified(settings, tmp_path):
    settings.AI_BYOK_ENABLED = True
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = 'unified-consumer-synthetic-encryption-only'
    owner = get_user_model().objects.create_user('unified-consumer')
    api = APIClient()
    api.force_authenticate(owner)
    manifest = tmp_path / 'manifest.json'
    item = profile(allowed_user_ids=[owner.pk], auth_modes=['none', 'api_key'])
    manifest.write_text(json.dumps([item]))
    settings.AI_BYOK_ENDPOINT_MANIFEST = str(manifest)
    created = api.post(BASE, dict(provider_id='ollama', endpoint_profile='office_ollama',
        display_name='Synthetic server', auth_mode='none', request_id=str(uuid.uuid4())), format='json')
    assert created.status_code == 201, created.content
    connection = UserAIConnection.objects.get(pk=created.data['id'])
    models_url = BASE + str(connection.pk) + '/models/'
    created = api.post(models_url, {'model_id': 'org/model:cloud'}, format='json')
    assert created.status_code == 201, created.content
    model = UserAIModelConfig.objects.select_related('connection').get(pk=created.data['id'])
    return N(api=api, owner=owner, connection=connection, model=model, models_url=models_url,
             manifest=manifest, item=item)


def prove(context, kinds=('text',)):
    for kind in kinds:
        with patch('api.ai_model_views.send_model_probe', return_value=ProbeOutcome('succeeded')):
            result = context.api.post(context.models_url + str(context.model.pk) + '/probe/',
                {'probe_kind': kind, 'revision': 1, 'request_id': str(uuid.uuid4())}, format='json')
        assert result.status_code == 200, result.content
    context.model.refresh_from_db()


def test_none_probe_receives_authorized_snapshot_and_binds_adapter(unified):
    captured = []
    def send(**arguments):
        captured.append(arguments)
        return ProbeOutcome('succeeded')
    with patch('api.ai_model_views.send_model_probe', side_effect=send):
        result = unified.api.post(unified.models_url + str(unified.model.pk) + '/probe/',
            {'probe_kind': 'text', 'revision': 1, 'request_id': str(uuid.uuid4())}, format='json')
    assert result.status_code == 200
    assert captured[0]['provider_key'] is None
    assert captured[0]['connection_snapshot'] == snapshot_connection(unified.connection)
    unified.model.refresh_from_db()
    binding = unified.model.capability_results['text']['route_binding']
    assert binding['auth_mode'] == 'none' and binding['adapter_version'] == 'chat-terminal-egress-v1'
    assert binding['proxy_alias'] == get_trusted_route(unified.connection, unified.model.model_id)['proxy_alias']
    assert verified_for_task(unified.model, 'article_qa')


def test_verified_text_enables_chat_translation_but_not_research(unified):
    prove(unified)
    for kind in ('article_qa', 'full_translation'):
        selection = resolve_task_model(unified.owner, kind, explicit_model_id=str(unified.model.pk))
        assert selection.connection.auth_mode == 'none'
    with pytest.raises(ModelSelectionError):
        resolve_task_model(unified.owner, 'deep_research', explicit_model_id=str(unified.model.pk))
    prove(unified, ('tools',))
    resolve_task_model(unified.owner, 'deep_research', explicit_model_id=str(unified.model.pk))
    receipt = unified.model.capability_results['text']
    receipt['route_binding']['adapter_version'] = 'unknown-adapter'
    unified.model.capability_results['text'] = receipt
    unified.model.save(update_fields=['capability_results'])
    assert not verified_for_task(unified.model, 'article_qa')


def test_default_model_reports_research_eligibility_from_current_tools_receipt(unified):
    from api.services.ai_task_preferences import _selected_state
    preference = N(
        selection_source='byok',
        model_config_id=unified.model.pk,
        model_config=unified.model,
    )
    subscription = {'state': 'not_connected'}
    prove(unified)
    state, info, source = _selected_state(
        preference, 'default', unified.owner.pk, subscription,
    )
    assert state == 'available' and source == 'byok' and info['research_eligible'] is False
    prove(unified, ('tools',))
    state, info, source = _selected_state(
        preference, 'default', unified.owner.pk, subscription,
    )
    assert state == 'available' and source == 'byok' and info['research_eligible'] is True


def test_research_without_tools_is_rejected_before_any_run_or_dispatch(unified):
    from api.models import ResearchRun, ResearchSession
    prove(unified)
    with patch('api.services.research.job_manager._dispatch') as dispatch:
        response = unified.api.post('/api/research/', {'query': 'Synthetic local research',
            'model_config_id': str(unified.model.pk), 'consent': True}, format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
    assert response.status_code == 409
    assert response.data['error_code'] == 'research_model_not_verified'
    assert response.data['request_state'] == 'rejected'
    assert not ResearchRun.objects.exists() and not ResearchSession.objects.exists()
    dispatch.assert_not_called()


def test_generic_research_conflict_does_not_claim_request_was_never_created():
    from api.research_views import _run_error_response
    from api.services.research.job_manager import ResearchRunError
    result = _run_error_response(ResearchRunError('research_run_active', 'Active task'))
    assert 'request_state' not in result.data


def test_none_probe_without_snapshot_is_not_authorized(unified):
    route = get_trusted_route(unified.connection, unified.model.model_id)
    with patch('api.services.ai_model_probe._OPENER.open') as network:
        result = send_model_probe(provider_key=None, model_alias=route['proxy_alias'], probe_kind='text')
    assert result.status == 'not_sent'
    network.assert_not_called()


@pytest.mark.parametrize('kind', ['text', 'tools'])
def test_compatible_probe_has_bounded_room_for_a_complete_answer(unified, settings, kind):
    """Tiny legacy caps clipped real compatible text/tools before their terminal."""
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:19999'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-synthetic-project-key-123456789'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY_FILE = ''
    calls = []
    def respond(request, **kwargs):
        body = json.loads(request.data)
        calls.append(body)
        assert 0 < body['max_tokens'] <= 1024  # A bounded explicit probe, never an open generation.
        complete = body['max_tokens'] >= 128
        message = {'role': 'assistant', 'content': 'Confirmed' if complete else ''}
        reason = 'stop' if complete else 'length'
        if complete and kind == 'tools':
            message.update(content=None, tool_calls=[{'id': 'call-bounded', 'type': 'function',
                'function': {'name': 'byok_probe', 'arguments': '{"ok":true}'}}])
            reason = 'tool_calls'
        response = io.BytesIO(json.dumps({'choices': [{'index': 0, 'message': message,
            'finish_reason': reason}]}).encode())
        response.status, response.headers = 200, {}
        return response
    with patch('api.services.ai_model_probe._OPENER.open', side_effect=respond):
        outcome = send_model_probe(provider_key=None, model_alias=get_trusted_route(
            unified.connection, unified.model.model_id)['proxy_alias'], probe_kind=kind,
            connection_snapshot=snapshot_connection(unified.connection))
    assert outcome.status == 'succeeded'
    assert len(calls) == 1


def test_route_contract_exposes_transport_mode_and_not_endpoint(unified):
    route = get_trusted_route(unified.connection, unified.model.model_id)
    assert route['delivery_mode'] == 'streaming'
    assert route['stream_verified'] is True
    assert 'api_base' not in route
    public = unified.api.get(unified.models_url).data['models'][0]
    assert public['delivery_mode'] == 'streaming' and public['protocol_family'] == 'chat_completions_v1'


def test_selected_adapter_cannot_send_another_alias_or_override_metadata(unified):
    prove(unified)
    selection = resolve_task_model(unified.owner, 'article_qa', explicit_model_id=str(unified.model.pk))
    calls = []
    def send(**kwargs):
        calls.append(kwargs)
        return iter(())
    adapter = _GatewayCompletions(N(create=send), None, selection=selection)
    adapter.create(model=selection.proxy_alias, messages=[{'role': 'user', 'content': 'synthetic'}], stream=True)
    assert calls[0]['extra_body'] == {'api_key': None, 'metadata': {
        'newshub_owner_id': unified.owner.pk, 'newshub_auth_mode': 'none'}}
    for values in ({'model': selection.proxy_alias + '-other'},
                   {'model': selection.proxy_alias, 'metadata': {'newshub_owner_id': unified.owner.pk + 1}}):
        with pytest.raises(AIGatewayError):
            adapter.create(messages=[], stream=True, **values)
    assert len(calls) == 1


def test_cloud_native_response_is_explicitly_buffered_with_real_terminal(unified):
    response = unified.api.post(BASE, dict(provider_id='openai', endpoint_profile='openai_default',
        display_name='Synthetic cloud', api_key='synthetic-cloud-key', request_id=str(uuid.uuid4())), format='json')
    assert response.status_code == 201
    unified.models_url = BASE + response.data['id'] + '/models/'
    response = unified.api.post(unified.models_url, {'model_id': 'gpt-synthetic'}, format='json')
    assert response.status_code == 201
    unified.model = UserAIModelConfig.objects.select_related('connection').get(pk=response.data['id'])
    prove(unified)
    selection = resolve_task_model(unified.owner, 'article_qa', explicit_model_id=str(unified.model.pk))
    route = get_trusted_route(unified.model.connection, unified.model.model_id)
    assert route['delivery_mode'] == 'buffered' and route['stream_verified'] is False
    calls = []
    def respond(**kwargs):
        calls.append(kwargs)
        return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': 'synthetic answer', 'annotations': []}]}]}
    adapter = _GatewayCompletions(N(create=lambda **_kwargs: pytest.fail('wrong protocol')),
        'synthetic-cloud-key', responses=N(create=respond), selection=selection)
    frames = list(adapter.create(model=selection.proxy_alias, stream=True, max_tokens=64,
        messages=[{'role': 'user', 'content': 'synthetic'}], stream_options={'include_usage': True}))
    assert len(calls) == 1 and 'stream_options' not in calls[0]
    assert frames[0].choices[0].delta.content == 'synthetic answer'
    assert frames[-1].choices[0].finish_reason == 'stop'


def test_rejected_or_partial_buffered_completion_never_yields_text(unified):
    prove(unified)
    selection = resolve_task_model(unified.owner, 'article_qa', explicit_model_id=str(unified.model.pk))
    # Use a valid trusted model identity; only its transport mode changes here
    # to exercise the common buffered adapter, without any network.
    for reason, refusal in (('length', None), ('stop', 'denied')):
        completion = N(choices=[N(finish_reason=reason, message=N(content='private partial',
            tool_calls=None, function_call=None, refusal=refusal))])
        adapter = _GatewayCompletions(N(create=lambda **_kwargs: completion), None, selection=selection)
        adapter._route = {**adapter._route, 'delivery_mode': 'buffered'}
        with pytest.raises(AIGatewayError):
            list(adapter.create(model=selection.proxy_alias, stream=True, max_tokens=64,
                messages=[{'role': 'user', 'content': 'synthetic'}]))


@pytest.fixture
def story():
    source = Source.objects.create(name='unified synthetic publisher', url='https://publisher.example/')
    category = Category.objects.create(name='unified synthetic', slug='unified-synthetic')
    return public_legacy_article(News.objects.create(title='Synthetic unified article',
        url='https://publisher.example/unified', source=source, category=category, content='Synthetic content',
        publish_time=timezone.now(), full_content='# Heading\n\nAlpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph.',
        full_content_state='legacy'))


def test_compatible_article_chat_commits_selected_model_without_deepseek_options(unified, story):
    prove(unified)
    gateway = FakeGateway([gateway_frame('verified compatible answer')])
    with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway) as build:
        response = unified.api.post(f'/api/news/{story.pk}/chat/', {
            'model_config_id': str(unified.model.pk), 'billing_consent': True, 'turn_id': str(uuid.uuid4()),
            'question': 'What happened?'}, format='json')
        assert response.status_code == 200, response.content
        wire = b''.join(response.streaming_content)
    assert b'"type": "chat_turn", "status": "complete"' in wire
    assert gateway.closed and len(gateway.sent) == 1
    assert 'reasoning_effort' not in gateway.sent[0]
    assert build.call_args.kwargs['selection'].connection.auth_mode == 'none'
    assert 'verified compatible answer' in json.dumps(ChatSession.objects.get(user=unified.owner, news=story).messages)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('auth_mode', ['none', 'api_key'])
def test_compatible_segmented_translation_keeps_selected_identity(unified, story, auth_mode, monkeypatch):
    from api.services import ai_private_translation as service
    from api.tests.translation_transport_fake import channel_factory
    monkeypatch.setattr(service.transport, 'Channel', channel_factory(service.transport))
    monkeypatch.setattr(service.transport, 'available', lambda: None)
    if auth_mode == 'api_key':
        response = unified.api.post(BASE, dict(provider_id='ollama', endpoint_profile='office_ollama',
            display_name='Synthetic Key', auth_mode=auth_mode, api_key='synthetic-unified-key',
            request_id=str(uuid.uuid4())), format='json')
        assert response.status_code == 201
        unified.models_url = BASE + response.data['id'] + '/models/'
        response = unified.api.post(unified.models_url, {'model_id': 'org/model:cloud'}, format='json')
        assert response.status_code == 201
        unified.model = UserAIModelConfig.objects.select_related('connection').get(pk=response.data['id'])
    prove(unified)
    gateways = []
    def build(_key, *, selection):
        assert selection.connection.auth_mode == auth_mode
        class EchoGateway(FakeGateway):
            def __init__(self):
                super().__init__([])
                def send(**kwargs):
                    self.sent.append(kwargs)
                    return [gateway_frame(kwargs['messages'][-1]['content'])]
                self.chat.completions.create = send
        gateway = EchoGateway()
        gateways.append(gateway)
        return gateway
    with patch.object(service, 'MAX_INPUT_CHARS', 30), patch.object(service, 'T06_CHUNK_INPUT_CHARS', 30), \
            patch.object(service, '_dispatch'), patch.object(service, 'build_gateway_client', side_effect=build):
        response = unified.api.post(f'/api/news/{story.pk}/byok-translation/', {
            'model_config_id': str(unified.model.pk), 'billing_consent': True, 'target_language': 'zh'},
            format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        assert response.status_code == 202, response.content
        task = ChatGPTTranslationTask.objects.get(pk=response.data['task_id'])
        service.run_translation(task.pk, task.generation)
    task.refresh_from_db()
    assert task.status == 'succeeded', task.error_code
    assert len(gateways) >= 2 and all(gateway.closed for gateway in gateways)
    assert all('reasoning_effort' not in gateway.sent[0] for gateway in gateways)
    result = ChatGPTArticleTranslation.objects.get(user=unified.owner)
    assert result.content == story.full_content


def test_error_and_refusal_cannot_prove_text_or_tools():
    for kind in ('text', 'tools'):
        for changes in ({'error': {'message': 'synthetic error'}},
                        {'choices': [{'finish_reason': 'stop', 'message': {'content': 'partial', 'refusal': 'denied'}}]}):
            body = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'partial'}}]} | changes
            assert parse_completion(200, {}, json.dumps(body).encode(), kind).status == 'unknown'


def test_usage_receipt_keeps_safe_route_metadata_and_refusal_unknown(unified):
    from api.services.ai_usage import complete_with_usage
    from api.services.research.byok_execution import ResearchBYOKError, _validated_completion
    prove(unified, ('text', 'tools'))
    selection = resolve_task_model(unified.owner, 'deep_research', explicit_model_id=str(unified.model.pk))
    refused = N(choices=[N(finish_reason='stop', message=N(content='private partial', refusal='denied', tool_calls=None))])
    complete_with_usage(N(chat=N(completions=N(create=lambda **_kwargs: refused))), selection, 'deep_research')
    receipt = AICallAttempt.objects.get()
    assert receipt.status == 'unknown'
    assert receipt.route_metadata == {'protocol_family': 'chat_completions_v1', 'delivery_mode': 'streaming',
        'adapter_version': 'chat-terminal-egress-v1', 'auth_mode': 'none', 'terminal_verified': False}
    assert 'private partial' not in json.dumps(receipt.route_metadata)
    with pytest.raises(ResearchBYOKError):
        _validated_completion(refused)


def test_maximum_profile_and_model_id_preserve_probe_alias(unified):
    profile_id = 'a' * 48
    unified.item['profile_id'] = profile_id
    unified.item['version'] = 32767
    unified.manifest.write_text(json.dumps([unified.item]))
    response = unified.api.post(BASE, dict(provider_id='ollama', endpoint_profile=profile_id,
        display_name='Long identity', auth_mode='none', request_id=str(uuid.uuid4())), format='json')
    assert response.status_code == 201
    connection = UserAIConnection.objects.get(pk=response.data['id'])
    alias = get_trusted_route(connection, 'm' * 160)['proxy_alias']
    assert len(alias) == 245
    with patch('api.services.ai_model_probe._gateway_configuration', side_effect=AIGatewayError('synthetic absent gateway')):
        outcome = send_model_probe(provider_key=None, model_alias=alias, probe_kind='text',
                                   connection_snapshot=snapshot_connection(connection))
    assert outcome.safe_error_code == 'gateway_unavailable'


@pytest.mark.parametrize('mutation', ['epoch', 'manifest', 'content'])
def test_compatible_late_answer_cannot_commit_after_revocation(unified, story, mutation):
    from django.db.models import F
    prove(unified)
    def revoke():
        if mutation == 'epoch':
            UserAIConnection.objects.filter(pk=unified.connection.pk).update(credential_epoch=F('credential_epoch') + 1)
        elif mutation == 'manifest':
            unified.item['enabled'] = False
            unified.manifest.write_text(json.dumps([unified.item]))
        else:
            story.full_content += '\n\nSource changed.'
            story.save(update_fields=['full_content'])
    gateway = FakeGateway([gateway_frame('late private answer')], on_send=revoke)
    with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
        response = unified.api.post(f'/api/news/{story.pk}/chat/', {'question': 'What happened?',
            'model_config_id': str(unified.model.pk), 'billing_consent': True, 'turn_id': str(uuid.uuid4())}, format='json')
        assert response.status_code == 200
        wire = b''.join(response.streaming_content)
    assert b'"status": "complete"' not in wire
    assert len(gateway.sent) == 1 and gateway.closed
    history = ChatSession.objects.get(user=unified.owner, news=story)
    assert not any(row['role'] == 'assistant' for row in history.messages)
