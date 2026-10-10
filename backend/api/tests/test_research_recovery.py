"""Fake-only regression coverage for durable research recovery and resource fencing."""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.http import JsonResponse, StreamingHttpResponse
from django.test import RequestFactory
from django.utils import timezone

from api.models import ResearchRun, ResearchRunEvent, ResearchSession
from api.services import chatgpt_subscription_jobs
from api.services.research import job_manager
from api import sse_resources
from api.sse_resources import SSEResourceMiddleware

User = get_user_model()


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
def fake_executor(monkeypatch):
    submitted = []

    def capture(function, *args, **kwargs):
        submitted.append((function, args, kwargs))
        return SimpleNamespace(done=False)

    monkeypatch.setattr(chatgpt_subscription_jobs, 'submit_background_task', capture)
    return submitted


def make_user(name='research-reader'):
    return User.objects.create_user(username=name, password='not-used')


def start_run(user, *, session_id=None, query='offline query', key='research-key'):
    return job_manager.submit_research_run(
        user,
        session_id=session_id,
        query=query,
        local_only=True,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_idempotency_is_owner_private_and_digest_bound(fake_executor):
    owner = make_user()
    session, first = start_run(owner)

    same_session, same_run = start_run(owner, query='offline query', key='research-key')
    assert same_session.pk == session.pk
    assert same_run.pk == first.pk
    assert len(fake_executor) == 1

    with pytest.raises(job_manager.ResearchRunError) as mismatch:
        start_run(owner, query='different query', key='research-key')
    assert mismatch.value.error_code == 'idempotency_key_reused'

    with pytest.raises(job_manager.ResearchRunError) as active_conflict:
        start_run(owner, session_id=session.pk, query='second active request', key='another-key')
    assert active_conflict.value.error_code == 'research_run_active'

    other_owner = make_user('other-research-reader')
    other_session, other_run = start_run(other_owner, key='research-key')
    assert other_session.pk != session.pk
    assert other_run.pk != first.pk
    assert other_run.user_id == other_owner.pk
    assert len(fake_executor) == 2


@pytest.mark.django_db(transaction=True)
def test_fake_worker_commits_full_history_and_bounded_replay_events(fake_executor, monkeypatch):
    owner = make_user()
    session, run = start_run(owner)
    text = '研究摘要：' + ('🧪' * 1200)
    messages = [{'role': 'assistant', 'content': text}]

    def fake_loop(current_session, query, on_event, **options):
        assert query == 'offline query'
        options['execution_guard']()
        on_event('thinking', {'iteration': 0})
        on_event('text_delta', {'text': text})
        options['persist_completion'](messages)
        on_event('complete', {})

    monkeypatch.setattr('api.services.research.agent_loop.run_agent_loop', fake_loop)
    function, args, kwargs = fake_executor[0]
    function(*args, **kwargs)

    run.refresh_from_db()
    session.refresh_from_db()
    assert run.status == 'succeeded'
    assert run.run_token is None
    assert session.messages == messages
    events = list(ResearchRunEvent.objects.filter(run=run).order_by('sequence'))
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[0].event_type == 'thinking'
    text_events = [event for event in events if event.event_type == 'text_delta']
    assert ''.join(event.data['text'] for event in text_events) == text
    assert all(len(job_manager.serialize_event(event.event_type, event.data).encode('utf-8')) <= job_manager.MAX_EVENT_WIRE_BYTES for event in events)
    assert all(len(event.data['text'].encode('utf-8')) <= job_manager.MAX_TEXT_DELTA_BYTES for event in text_events)
    assert events[-1].event_type == 'complete'
    assert run.event_wire_bytes == sum(event.wire_bytes for event in events)


@pytest.mark.django_db(transaction=True)
def test_cancel_fences_the_next_worker_action_and_preserves_session_history(fake_executor, monkeypatch):
    owner = make_user()
    original_messages = [{'role': 'assistant', 'content': 'previous answer'}]
    session = ResearchSession.objects.create(user=owner, messages=original_messages)
    _, run = start_run(owner, session_id=session.pk, query='cancel me', key='cancel-key')
    reached_after_cancel = []

    def fake_loop(current_session, query, on_event, **options):
        on_event('thinking', {'iteration': 0})
        job_manager.cancel_research_run(owner, current_session, run.pk)
        with pytest.raises(job_manager.ResearchRunError):
            options['execution_guard']()
        reached_after_cancel.append('guarded')
        options['persist_completion']([{'role': 'assistant', 'content': 'must not save'}])

    monkeypatch.setattr('api.services.research.agent_loop.run_agent_loop', fake_loop)
    function, args, kwargs = fake_executor[0]
    function(*args, **kwargs)

    run.refresh_from_db()
    session.refresh_from_db()
    assert run.status == 'cancelled'
    assert reached_after_cancel == ['guarded']
    assert session.messages == original_messages


@pytest.mark.django_db(transaction=True)
def test_expired_running_run_becomes_interrupted_and_only_new_key_retries(fake_executor):
    owner = make_user()
    session = ResearchSession.objects.create(user=owner)
    token = uuid.uuid4()
    run = ResearchRun.objects.create(
        user=owner,
        session=session,
        idempotency_key='expired-key',
        request_hash=job_manager.request_digest('offline query', True, str(session.pk)),
        status='running',
        run_token=token,
        heartbeat_at=timezone.now() - timedelta(minutes=2),
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert job_manager._interrupt_expired(run.pk, token)
    run.refresh_from_db()
    assert run.status == 'interrupted'
    assert run.run_token is None
    assert not fake_executor

    _, retry = start_run(owner, session_id=session.pk, query='new explicit attempt', key='new-explicit-key')
    assert retry.pk != run.pk
    assert len(fake_executor) == 1


@pytest.mark.django_db(transaction=True)
def test_event_wire_and_cumulative_limits_fail_closed(fake_executor):
    owner = make_user()
    session = ResearchSession.objects.create(user=owner)
    now = timezone.now()
    token = uuid.uuid4()
    run = ResearchRun.objects.create(
        user=owner,
        session=session,
        idempotency_key='limit-key',
        request_hash=job_manager.request_digest('offline query', True, str(session.pk)),
        status='running',
        run_token=token,
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=60),
    )

    with pytest.raises(job_manager.ResearchRunError) as oversized:
        job_manager.append_event(run.pk, token, 'thinking', {'value': 'x' * job_manager.MAX_EVENT_WIRE_BYTES})
    assert oversized.value.error_code == 'research_event_too_large'

    ResearchRun.objects.filter(pk=run.pk).update(
        event_wire_bytes=job_manager.MAX_RUN_WIRE_BYTES - 1,
    )
    with pytest.raises(job_manager.ResearchRunError) as cumulative:
        job_manager.append_event(run.pk, token, 'thinking', {'value': 'x'})
    assert cumulative.value.error_code == 'research_event_limit_exceeded'
    assert not ResearchRunEvent.objects.filter(run=run).exists()


def _sse_request(factory, url_name='research-chat'):
    request = factory.post('/api/research/fake/')
    request.resolver_match = SimpleNamespace(url_name=url_name)
    return request


@pytest.mark.django_db
def test_sse_slots_saturate_before_dispatch_and_release_on_close_and_exception():
    factory = RequestFactory()
    middleware = SSEResourceMiddleware(lambda request: StreamingHttpResponse(iter(()), content_type='text/event-stream'))
    active = []
    for _ in range(2):
        request = _sse_request(factory)
        assert middleware.process_view(request, lambda: None, (), {}) is None
        active.append(request)

    saturated = _sse_request(factory)
    rejected = middleware.process_view(saturated, lambda: None, (), {})
    assert rejected.status_code == 503
    assert rejected['Retry-After'] == '1'
    assert json.loads(rejected.content)['error_code'] == 'sse_capacity_reached'

    active[0]._sse_resource_release()
    active[1]._sse_resource_release()

    never_iterated = _sse_request(factory)
    middleware.process_view(never_iterated, lambda: None, (), {})
    response = middleware(never_iterated)
    response.close()

    failing = _sse_request(factory)
    middleware.process_view(failing, lambda: None, (), {})
    failing_middleware = SSEResourceMiddleware(lambda request: (_ for _ in ()).throw(RuntimeError('fake view failure')))
    with pytest.raises(RuntimeError):
        failing_middleware(failing)

    non_stream = _sse_request(factory)
    non_stream_middleware = SSEResourceMiddleware(lambda request: JsonResponse({'error': 'fake non-stream'}))
    non_stream_middleware.process_view(non_stream, lambda: None, (), {})
    non_stream_middleware(non_stream)

    with sse_resources._sse_lock:
        assert sse_resources._active_sse_requests == 0


@pytest.mark.django_db
def test_sse_resource_release_on_stream_iteration_exception_and_non_sse_isolation():
    factory = RequestFactory()
    def response_with_failure(_request):
        def source():
            yield 'data: {"type":"thinking"}\n\n'
            raise RuntimeError('connection reset during streaming')
        return StreamingHttpResponse(source(), content_type='text/event-stream')

    middleware = SSEResourceMiddleware(response_with_failure)
    request = _sse_request(factory, 'research-stream')
    request.method = 'GET'
    assert middleware.process_view(request, lambda: None, (), {}) is None
    response = middleware(request)
    events = iter(response.streaming_content)
    assert next(events).startswith(b'data: ')
    with pytest.raises(RuntimeError, match='connection reset'):
        next(events)
    response.close()
    request._sse_resource_release()

    blocked_slots = []
    for _ in range(2):
        current = _sse_request(factory)
        assert middleware.process_view(current, lambda: None, (), {}) is None
        blocked_slots.append(current)
    try:
        unrelated = factory.get('/api/news/')
        unrelated.resolver_match = SimpleNamespace(url_name='news-list')
        assert middleware.process_view(unrelated, lambda: None, (), {}) is None
        assert middleware.process_view(_sse_request(factory), lambda: None, (), {}).status_code == 503
    finally:
        for current in blocked_slots:
            current._sse_resource_release()
    with sse_resources._sse_lock:
        assert sse_resources._active_sse_requests == 0



@pytest.mark.django_db(transaction=True)
def test_queued_recovery_after_process_restart_dispatches_existing_idempotent_run_once(fake_executor, monkeypatch):
    owner = make_user()
    session, run = start_run(owner, query='unstarted research', key='safe-recover-1')
    assert run.queued_query == 'unstarted research'
    assert run.queued_local_only is True
    assert len(fake_executor) == 1

    # Simulate the queue process exiting before it ever claims the row.
    with job_manager._dispatch_lock:
        job_manager._dispatching.clear()
    with job_manager._capacity_lock:
        job_manager._admitted_runs.clear()

    recovered = job_manager.resume_queued_run(owner, session, str(run.pk))
    assert recovered.pk == run.pk
    assert len(fake_executor) == 2
    calls = []
    def guarded_agent(session, query, on_event, **kwargs):
        calls.append((session.pk, query, kwargs['local_only']))
        kwargs['execution_guard']()
        kwargs['persist_completion']([{'role': 'assistant', 'content': 'completed'}])
        on_event('complete', {})

    monkeypatch.setattr('api.services.research.agent_loop.run_agent_loop', guarded_agent)
    # Both submitted work items can race; only one can claim from queued.
    for fn, args, kw in reversed(fake_executor):
        fn(*args, **kw)

    run.refresh_from_db()
    session.refresh_from_db()
    assert calls == [(session.pk, 'unstarted research', True)]
    assert run.status == 'succeeded'
    assert run.queued_query == ''
    assert session.messages == [{'role': 'assistant', 'content': 'completed'}]
    assert ResearchRun.objects.filter(user=owner, session=session).count() == 1


@pytest.mark.django_db(transaction=True)
def test_started_run_and_terminal_run_cannot_reenter_provider_on_queued_resume(fake_executor):
    owner = make_user()
    session, run = start_run(owner, query='one provider attempt', key='no-double-run')
    token = job_manager._claim(run.pk)
    assert token is not None

    already_running = job_manager.resume_queued_run(owner, session, str(run.pk))
    assert already_running.pk == run.pk and already_running.status == 'running'
    assert len(fake_executor) == 1
    job_manager.cancel_research_run(owner, session, run.pk)
    with pytest.raises(job_manager.ResearchRunError) as terminated:
        job_manager.resume_queued_run(owner, session, str(run.pk))
    assert terminated.value.error_code == 'research_run_changed'
    assert len(fake_executor) == 1


@pytest.mark.django_db(transaction=True)
def test_legacy_queued_without_recoverable_input_fails_closed_and_owner_isolated(fake_executor):
    owner = make_user()
    stranger = make_user('stranger-queued')
    session = ResearchSession.objects.create(user=owner)
    run = ResearchRun.objects.create(
        user=owner, session=session, idempotency_key='old-queued',
        request_hash=job_manager.request_digest('undisclosed query', True, None),
        status='queued',
    )
    with pytest.raises(job_manager.ResearchRunError) as missing:
        job_manager.resume_queued_run(owner, session, str(run.pk))
    assert missing.value.error_code == 'research_queued_input_missing'
    assert missing.value.status_code == 409

    with pytest.raises(job_manager.ResearchRunError) as hidden:
        job_manager.resume_queued_run(stranger, session, str(run.pk))
    assert hidden.value.status_code == 404
    assert len(fake_executor) == 0


@pytest.mark.django_db(transaction=True)
def test_queued_resume_endpoint_rejects_other_users_and_preserves_csrf(fake_executor):
    from rest_framework.test import APIClient

    owner = make_user()
    stranger = make_user('stranger-endpoint')
    session, run = start_run(owner, query='offline', key='http-safe')
    route = f'/api/research/{session.pk}/resume-queued/'
    other = APIClient()
    other.force_authenticate(stranger)
    assert other.post(route, {'run_id': str(run.pk)}, format='json').status_code == 404

    csrf = APIClient(enforce_csrf_checks=True)
    csrf.force_login(owner)
    assert csrf.post(route, {'run_id': str(run.pk)}, format='json').status_code == 403

    valid = APIClient()
    valid.force_authenticate(owner)
    malformed = valid.post(route, {'run_id': 'invalid-uuid'}, format='json')
    assert malformed.status_code == 400
    assert malformed.data['error_code'] == 'invalid_run_id'
    response = valid.post(route, {'run_id': str(run.pk)}, format='json')
    assert response.status_code == 200
    assert response.data['run_id'] == str(run.pk)
    assert set(response.data) == {'run_id', 'status'}
    assert len(fake_executor) == 1  # The original in-process dispatch remains sole owner.
