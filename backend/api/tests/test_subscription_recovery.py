"""Fake-only regression coverage for persistent subscription translation recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time
import uuid
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from api.models import (
    Category,
    ChatGPTArticleTranslation,
    ChatGPTSubscriptionConnection,
    ChatGPTTranslationTask,
    News,
    SharedArticleTranslation,
    Source,
)
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_jobs as jobs
from api.services import shared_translations
from api.subscription_views import subscription_translation_response

pytestmark = pytest.mark.django_db(transaction=True)
User = get_user_model()


@pytest.fixture
def local_mode(settings):
    settings.CHATGPT_AUTH_MODE = 'local_oss'
    settings.DJANGO_ENV = 'development'
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True


@pytest.fixture
def owner(db, local_mode):
    return User.objects.create_user(username='translation-owner', password='not-used')


@pytest.fixture
def article(db):
    return News.objects.create(
        title='Recovery article',
        url='https://example.test/article',
        publish_time=timezone.now(),
        source=Source.objects.create(
            name='Recovery source', url='https://example.test', language='en',
        ),
        category=Category.objects.create(name='Recovery', slug='recovery'),
        full_content='# Recovery article\n\nOriginal source text.',
    )


def make_connection(user):
    return ChatGPTSubscriptionConnection.objects.create(
        user=user,
        subject_hash='a' * 64,
        issuer='https://auth.example.test',
        issued_client_id='synthetic-client',
        registration_key_hash=str(uuid.uuid4()),
        encrypted_access_token='synthetic-encrypted-access',
        encrypted_refresh_token='synthetic-encrypted-refresh',
        granted_scopes=[subscription.REQUIRED_DIRECT_SCOPE],
        access_token_expires_at=timezone.now() + timedelta(hours=1),
        selected_model='visible-test-model',
        is_active=True,
        needs_reauth=False,
        generation=1,
    )


def start_queued(user, connection, news, monkeypatch, *, shared_lease=None, force=False):
    monkeypatch.setattr(jobs, '_dispatch_task', lambda *_args: None)
    return jobs.start_or_get_job(
        user, connection, news, shared_lease=shared_lease, force=force,
    )


def wait_for_terminal(task_id, *, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            task = ChatGPTTranslationTask.objects.filter(pk=task_id).first()
        except OperationalError:
            # A concurrent SQLite writer may briefly lock an in-memory test
            # table. Keep polling: the final terminal-state assertion is
            # unchanged, and a persistent lock still fails at the deadline.
            time.sleep(0.02)
            continue
        if task is None or task.status in jobs.TERMINAL_STATUSES:
            return task
        time.sleep(0.02)
    return ChatGPTTranslationTask.objects.filter(pk=task_id).first()


class FakeResponse:
    def __init__(self, lines=(), status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._lines = list(lines)
        self._payload = payload or {}
        self.text = text
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


def test_simultaneous_database_connections_share_one_unique_task(owner, article, monkeypatch):
    connection = make_connection(owner)

    def submit():
        close_old_connections()
        try:
            worker_user = User.objects.get(pk=owner.pk)
            worker_connection = ChatGPTSubscriptionConnection.objects.get(pk=connection.pk)
            worker_news = News.objects.get(pk=article.pk)
            handle = jobs.start_or_get_job(worker_user, worker_connection, worker_news)
            return handle.id
        finally:
            close_old_connections()

    monkeypatch.setattr(jobs, '_dispatch_task', lambda *_args: None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        handles = list(executor.map(lambda _: submit(), range(2)))

    assert handles[0] == handles[1]
    assert ChatGPTTranslationTask.objects.filter(
        user=owner, connection=connection, news=article,
    ).count() == 1


def test_worker_claim_is_single_and_started_state_precedes_provider(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    provider_calls = []
    entered = threading.Event()
    finish = threading.Event()

    def fake_stream(**kwargs):
        task = ChatGPTTranslationTask.objects.get(pk=handle.id)
        assert task.status == 'running'
        assert task.provider_started is True
        provider_calls.append(task.run_token)
        kwargs['on_delta']('one chunk')
        entered.set()
        assert finish.wait(4)
        return 'complete translation'

    monkeypatch.setattr(jobs, 'stream_full_translation', fake_stream)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(jobs._run_persistent_task, handle.id, handle.generation)
        assert entered.wait(3)
        second = executor.submit(jobs._run_persistent_task, handle.id, handle.generation)
        second.result(timeout=3)
        finish.set()
        first.result(timeout=4)

    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert task.status == 'succeeded'
    assert task.progress == 'one chunk'
    assert task.result['full_content_zh'] == 'complete translation'
    assert len(provider_calls) == 1
    assert ChatGPTArticleTranslation.objects.get(user=owner, news=article).content == 'complete translation'


def test_registry_reset_and_new_handle_read_persistent_progress_and_result(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    monkeypatch.setattr(
        jobs, 'stream_full_translation',
        lambda **kwargs: (kwargs['on_delta']('persistent chunk') or 'persistent result'),
    )
    jobs._run_persistent_task(handle.id, handle.generation)
    with jobs._jobs_lock:
        jobs._jobs.clear()

    attached = jobs.get_job(owner.pk, connection.pk, article.pk, subscription.source_hash(article.full_content))
    assert attached is not None
    assert attached.text == 'persistent chunk'
    assert attached.result['full_content_zh'] == 'persistent result'
    assert attached.done


def test_unstarted_expiry_returns_to_queue_and_claims_once(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    old_token = uuid.uuid4()
    ChatGPTTranslationTask.objects.filter(pk=handle.id).update(
        status='running', run_token=old_token, provider_started=False,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )
    recovered = jobs.get_task(handle.id, user_id=owner.pk)
    assert recovered.status == 'queued'
    assert recovered.run_token is None

    calls = []
    monkeypatch.setattr(jobs, 'stream_full_translation', lambda **_kwargs: calls.append('call') or 'done')
    jobs._run_persistent_task(handle.id, handle.generation)
    assert calls == ['call']
    assert ChatGPTTranslationTask.objects.get(pk=handle.id).status == 'succeeded'


def test_started_expiry_interrupted_and_only_explicit_force_retries(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    ChatGPTTranslationTask.objects.filter(pk=handle.id).update(
        status='running', run_token=uuid.uuid4(), provider_started=True,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )
    recovered = jobs.get_task(handle.id, user_id=owner.pk)
    assert recovered.status == 'interrupted'
    assert recovered.error_code == 'worker_interrupted'
    calls = []
    monkeypatch.setattr(jobs, 'stream_full_translation', lambda **_kwargs: calls.append('call') or 'done')
    jobs._run_persistent_task(handle.id, handle.generation)
    assert calls == []

    retried = jobs.start_or_get_job(owner, connection, article, force=True)
    assert retried.id == handle.id
    assert retried.generation == handle.generation + 1
    assert retried.status == 'queued'
    jobs._run_persistent_task(retried.id, retried.generation)
    assert calls == ['call']
    assert ChatGPTTranslationTask.objects.get(pk=handle.id).status == 'succeeded'
    assert handle.done and handle.text == '' and handle.result is None
    assert handle.error == jobs.RESTART_ERROR
    assert handle.status == 'interrupted'


def test_force_attaches_active_task_and_advances_only_terminal_generation(owner, article, monkeypatch):
    connection = make_connection(owner)
    first = start_queued(owner, connection, article, monkeypatch)
    attached = jobs.start_or_get_job(owner, connection, article, force=True)
    assert attached.generation == first.generation
    assert ChatGPTTranslationTask.objects.get(pk=first.id).status == 'queued'

    ChatGPTTranslationTask.objects.filter(pk=first.id).update(
        status='failed', error_code='translation_failed',
        error_message='safe failure', finished_at=timezone.now(),
    )
    retry = jobs.start_or_get_job(owner, connection, article, force=True)
    assert retry.generation == first.generation + 1
    assert retry.status == 'queued'


def test_old_finally_cannot_release_shared_lease_after_unstarted_reclaim(owner, article, monkeypatch):
    connection = make_connection(owner)
    shared_lease = shared_translations.claim_task(article)
    assert shared_lease is not None
    handle = start_queued(owner, connection, article, monkeypatch, shared_lease=shared_lease)
    old_token = uuid.uuid4()
    ChatGPTTranslationTask.objects.filter(pk=handle.id).update(
        status='running', run_token=old_token, provider_started=False,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert jobs.get_task(handle.id, user_id=owner.pk).status == 'queued'

    provider_entered = threading.Event()
    finish_provider = threading.Event()

    def fake_stream(**kwargs):
        kwargs['on_delta']('new run')
        provider_entered.set()
        assert finish_provider.wait(4)
        return 'saved after reclaim'

    monkeypatch.setattr(jobs, 'stream_full_translation', fake_stream)
    worker = threading.Thread(
        target=jobs._run_persistent_task, args=(handle.id, handle.generation), daemon=True,
    )
    worker.start()
    assert provider_entered.wait(3)
    with pytest.raises(subscription.SubscriptionError):
        jobs._finalize_task(handle.id, handle.generation, old_token, 'stale finalization')
    assert shared_lease.current().exists()
    jobs._mark_failed(handle.id, handle.generation, old_token, RuntimeError('RAW_PROVIDER_SENTINEL'))
    assert shared_lease.current().exists()
    finish_provider.set()
    worker.join(timeout=5)

    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert not worker.is_alive()
    assert task.status == 'succeeded'
    assert task.result['full_content_zh'] == 'saved after reclaim'
    assert shared_translations.get_shared_translation(article).content == 'saved after reclaim'


def test_shared_lease_cancel_uses_only_stored_token(owner, article, monkeypatch):
    connection = make_connection(owner)
    old_lease = shared_translations.claim_task(article)
    handle = start_queued(owner, connection, article, monkeypatch, shared_lease=old_lease)
    old_lease.finish('failed')
    replacement = shared_translations.claim_task(article)
    assert replacement is not None and replacement.token != old_lease.token

    cancelled, changed = jobs.cancel_task(handle.id, user_id=owner.pk, generation=handle.generation)
    assert changed and cancelled.status == 'cancelled'
    assert replacement.current().exists()


def test_owner_get_cancel_authentication_csrf_and_private_dto(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    route = f'/api/chatgpt-subscription/jobs/{handle.id}/'
    cancel_route = f'{route}cancel/'
    client = APIClient()
    client.force_authenticate(owner)

    response = client.get(route)
    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    assert set(response.data) == {
        'id', 'status', 'generation', 'progress', 'result', 'error_code',
        'error_message', 'updated_at', 'finished_at',
    }
    assert 'run_token' not in response.data and 'shared_lease_token' not in response.data

    other = User.objects.create_user(username='other-reader', password='not-used')
    client.force_authenticate(other)
    assert client.get(route).status_code == 404
    assert client.post(cancel_route, {'generation': handle.generation}, format='json').status_code == 404

    client.force_authenticate(None)
    assert client.get(route).status_code == 403
    assert client.post(cancel_route, {'generation': handle.generation}, format='json').status_code == 403

    csrf_client = APIClient(enforce_csrf_checks=True)
    csrf_client.force_login(owner)
    csrf_response = csrf_client.post(
        cancel_route, {'generation': handle.generation}, format='json',
    )
    assert csrf_response.status_code == 403
    assert csrf_response['Cache-Control'] == 'no-store'


def test_cancel_validation_stale_generation_and_idempotent_terminal(owner, article, monkeypatch):
    connection = make_connection(owner)
    shared_lease = shared_translations.claim_task(article)
    handle = start_queued(owner, connection, article, monkeypatch, shared_lease=shared_lease)
    client = APIClient()
    client.force_authenticate(owner)
    route = f'/api/chatgpt-subscription/jobs/{handle.id}/cancel/'

    for body in ({}, {'generation': True}, {'generation': 0}, {'generation': -1},
                 {'generation': '1'}, {'generation': 9223372036854775808}):
        invalid = client.post(route, body, format='json')
        assert invalid.status_code == 400
        assert invalid.data['error_code'] == 'invalid_generation'
        assert invalid['Cache-Control'] == 'no-store'

    stale = client.post(route, {'generation': handle.generation + 1}, format='json')
    assert stale.status_code == 409
    assert stale.data['error_code'] == 'task_generation_changed'
    assert shared_lease.current().exists()
    assert ChatGPTTranslationTask.objects.get(pk=handle.id).status == 'queued'

    cancelled = client.post(route, {'generation': handle.generation}, format='json')
    assert cancelled.status_code == 200
    assert cancelled.data['status'] == 'cancelled'
    assert not shared_lease.current().exists()
    repeated = client.post(route, {'generation': handle.generation}, format='json')
    assert repeated.status_code == 200 and repeated.data['status'] == 'cancelled'
    assert not ChatGPTArticleTranslation.objects.exists()


def test_invalid_cancel_does_not_start_provider(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    with patch.object(jobs, 'stream_full_translation') as provider:
        client = APIClient()
        client.force_authenticate(owner)
        response = client.post(
            f'/api/chatgpt-subscription/jobs/{handle.id}/cancel/',
            {'generation': handle.generation}, format='json',
        )
        assert response.status_code == 200 and response.data['status'] == 'cancelled'
        provider.assert_not_called()
    assert ChatGPTTranslationTask.objects.get(pk=handle.id).provider_started is False


def test_sse_disconnect_does_not_cancel_background_worker(owner, article, monkeypatch):
    connection = make_connection(owner)
    provider_entered = threading.Event()
    finish_provider = threading.Event()

    def fake_stream(**kwargs):
        kwargs['on_delta']('visible progress')
        provider_entered.set()
        assert finish_provider.wait(5)
        return 'complete after disconnect'

    monkeypatch.setattr(jobs, 'stream_full_translation', fake_stream)
    request = APIRequestFactory().post('/api/news/1/translate/', {'force': False}, format='json')
    request.user = owner
    response = subscription_translation_response(request, article, force=False)
    assert response['Cache-Control'] == 'no-store'
    assert response['Job-ID']
    stream = iter(response.streaming_content)
    try:
        first_event = next(stream)
        assert b'progress' in first_event
        assert provider_entered.wait(3)
    finally:
        response.close()
        close = getattr(stream, 'close', None)
        if close:
            close()
    task_id = response['Job-ID']
    task = ChatGPTTranslationTask.objects.get(pk=task_id)
    assert task.status == 'running'
    finish_provider.set()
    terminal = wait_for_terminal(task_id)
    assert terminal.status == 'succeeded'
    assert terminal.result['full_content_zh'] == 'complete after disconnect'


def test_cancel_during_token_refresh_wait_blocks_decrypt_and_network(owner, monkeypatch):
    connection = make_connection(owner)
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=1)
    connection.save(update_fields=['access_token_expires_at'])
    cancelled = threading.Event()

    def guard():
        if cancelled.is_set():
            raise subscription.SubscriptionError('任务已取消。', 'task_cancelled', 409)

    monkeypatch.setattr(subscription, '_acquire_refresh_lease', lambda *_args: False)
    monkeypatch.setattr(subscription.time, 'sleep', lambda _seconds: cancelled.set())
    with patch.object(subscription, 'decrypt_secret') as decrypt, \
            patch.object(subscription.requests, 'get') as get, \
            patch.object(subscription.requests, 'post') as post:
        with pytest.raises(subscription.SubscriptionError, match='已取消'):
            subscription._refresh_access_token(connection.pk, connection.generation, guard)
    decrypt.assert_not_called()
    get.assert_not_called()
    post.assert_not_called()


def test_cancel_between_discovery_and_token_post_blocks_next_request(owner, monkeypatch):
    connection = make_connection(owner)
    cancelled = threading.Event()

    def guard():
        if cancelled.is_set():
            raise subscription.SubscriptionError('任务已取消。', 'task_cancelled', 409)

    def discovery(execution_guard=None):
        cancelled.set()
        return {'token_endpoint': 'https://auth.example.test/token'}

    monkeypatch.setattr(subscription, '_discovery', discovery)
    with patch.object(subscription, 'decrypt_secret', return_value='refresh-secret'), \
            patch.object(subscription.requests, 'post') as post:
        with pytest.raises(subscription.SubscriptionError, match='已取消'):
            subscription._refresh_access_token_with_lease(
                connection, connection.generation, 'refresh-lease', guard,
            )
    post.assert_not_called()


def test_cancel_during_delta_blocks_later_delta_and_closes_response(owner, article, monkeypatch):
    connection = make_connection(owner)
    cancelled = threading.Event()
    response = FakeResponse(lines=[
        'event: response.output_text.delta',
        'data: {"type":"response.output_text.delta","delta":"first"}',
        '',
        'event: response.output_text.delta',
        'data: {"type":"response.output_text.delta","delta":"second"}',
        '',
        'event: response.completed',
        'data: {"type":"response.completed","response":{"output_text":"complete"}}',
    ])
    deltas = []

    def guard():
        if cancelled.is_set():
            raise subscription.SubscriptionError('任务已取消。', 'task_cancelled', 409)

    def append(delta):
        deltas.append(delta)
        cancelled.set()

    monkeypatch.setattr(subscription, 'access_token_for', lambda *_args, **_kwargs: 'synthetic-token')
    with patch.object(subscription.requests, 'post', return_value=response) as post:
        with pytest.raises(subscription.SubscriptionError, match='已取消'):
            subscription.stream_full_translation(
                connection.pk, connection.generation, connection.selected_model,
                article.full_content, append, execution_guard=guard,
            )
    assert post.call_count == 1
    assert response.closed is True
    assert deltas == ['first']
    assert not ChatGPTArticleTranslation.objects.exists()


def test_cancelled_worker_stops_after_current_delta_and_cannot_save(owner, article, monkeypatch):
    connection = make_connection(owner)
    shared_lease = shared_translations.claim_task(article)
    handle = start_queued(
        owner, connection, article, monkeypatch, shared_lease=shared_lease,
    )
    response = FakeResponse(lines=[
        'event: response.output_text.delta',
        'data: {"type":"response.output_text.delta","delta":"first"}',
        '',
        'event: response.output_text.delta',
        'data: {"type":"response.output_text.delta","delta":"second"}',
        '',
        'event: response.completed',
        'data: {"type":"response.completed","response":{"output_text":"complete"}}',
    ])
    append_delta = jobs._append_delta

    def append_then_cancel(task_id, generation, run_token, delta):
        append_delta(task_id, generation, run_token, delta)
        if delta == 'first':
            jobs.cancel_task(task_id, user_id=owner.pk, generation=generation)

    monkeypatch.setattr(jobs, '_append_delta', append_then_cancel)
    monkeypatch.setattr(subscription, 'access_token_for', lambda *_args, **_kwargs: 'synthetic-token')
    with patch.object(subscription.requests, 'post', return_value=response) as post:
        jobs._run_persistent_task(handle.id, handle.generation)

    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert post.call_count == 1
    assert response.closed is True
    assert task.status == 'cancelled'
    assert task.progress == 'first'
    assert not ChatGPTArticleTranslation.objects.exists()
    assert not SharedArticleTranslation.objects.exists()


def test_guard_after_refresh_return_blocks_model_post(owner, article):
    connection = make_connection(owner)
    cancelled = threading.Event()

    def after_refresh(*_args, **_kwargs):
        cancelled.set()
        return 'synthetic-token'

    def guard():
        if cancelled.is_set():
            raise subscription.SubscriptionError('任务已取消。', 'task_cancelled', 409)

    with patch.object(subscription, 'access_token_for', side_effect=after_refresh), \
            patch.object(subscription.requests, 'post') as post:
        with pytest.raises(subscription.SubscriptionError, match='已取消'):
            subscription.stream_full_translation(
                connection.pk, connection.generation, connection.selected_model,
                article.full_content, lambda _delta: None, execution_guard=guard,
            )
    post.assert_not_called()


def test_lost_private_lease_cannot_finalize(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)

    def lose_lease(**_kwargs):
        ChatGPTTranslationTask.objects.filter(pk=handle.id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        return 'must not be saved'

    monkeypatch.setattr(jobs, 'stream_full_translation', lose_lease)
    jobs._run_persistent_task(handle.id, handle.generation)
    assert not ChatGPTArticleTranslation.objects.exists()
    recovered = jobs.get_task(handle.id, user_id=owner.pk)
    assert recovered.status == 'interrupted'
    assert recovered.error_code == 'worker_interrupted'


def test_deleted_article_prevents_queued_provider_start(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    article.delete()
    with patch.object(jobs, 'stream_full_translation') as provider:
        jobs._run_persistent_task(handle.id, handle.generation)
        provider.assert_not_called()
    assert not ChatGPTTranslationTask.objects.filter(pk=handle.id).exists()


def test_owner_connection_model_and_source_fences_stop_queued_worker(owner, article, monkeypatch):
    cases = ('inactive-user', 'connection-generation', 'selected-model', 'source')
    for case in cases:
        connection = make_connection(owner)
        handle = start_queued(owner, connection, article, monkeypatch)
        if case == 'inactive-user':
            User.objects.filter(pk=owner.pk).update(is_active=False)
        elif case == 'connection-generation':
            ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(generation=2)
        elif case == 'selected-model':
            ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(selected_model='other-model')
        else:
            News.objects.filter(pk=article.pk).update(full_content='changed source')
        with patch.object(jobs, 'stream_full_translation') as provider:
            jobs._run_persistent_task(handle.id, handle.generation)
            provider.assert_not_called()
        assert ChatGPTTranslationTask.objects.get(pk=handle.id).status == 'failed'
        if case == 'inactive-user':
            User.objects.filter(pk=owner.pk).update(is_active=True)
        if case == 'connection-generation':
            ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(generation=connection.generation)
        if case == 'selected-model':
            ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(selected_model=connection.selected_model)
        if case == 'source':
            News.objects.filter(pk=article.pk).update(full_content='# Recovery article\n\nOriginal source text.')
        ChatGPTTranslationTask.objects.filter(pk=handle.id).delete()
        connection.delete()


def test_provider_exceptions_are_redacted_in_persistent_failure_and_logs(owner, article, monkeypatch, caplog):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    monkeypatch.setattr(
        jobs, 'stream_full_translation',
        Mock(side_effect=RuntimeError('RAW_PROVIDER_ERROR_SENTINEL')),
    )
    jobs._run_persistent_task(handle.id, handle.generation)
    failed = ChatGPTTranslationTask.objects.get(pk=handle.id)
    assert failed.status == 'failed'
    assert failed.error_code == 'translation_failed'
    assert 'RAW_PROVIDER_ERROR_SENTINEL' not in failed.error_message
    assert 'RAW_PROVIDER_ERROR_SENTINEL' not in caplog.text
    assert 'RuntimeError' in caplog.text


@pytest.mark.parametrize(('mode', 'expected_status'), [('disabled', 403), ('website', 503)])
def test_disabled_and_website_modes_fail_closed_without_task_writes_or_network(
    owner, article, settings, monkeypatch, mode, expected_status,
):
    connection = make_connection(owner)
    settings.CHATGPT_AUTH_MODE = mode
    before = ChatGPTTranslationTask.objects.count()
    with patch.object(subscription.requests, 'get') as get, \
            patch.object(subscription.requests, 'post') as post:
        with pytest.raises(subscription.SubscriptionError):
            jobs.start_or_get_job(owner, connection, article)
        client = APIClient()
        client.force_authenticate(owner)
        response = client.get('/api/chatgpt-subscription/jobs/00000000-0000-0000-0000-000000000001/')
        assert response.status_code == expected_status
        assert response['Cache-Control'] == 'no-store'
    get.assert_not_called()
    post.assert_not_called()
    assert ChatGPTTranslationTask.objects.count() == before


def test_sse_reattach_redispatches_persisted_queued_task(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    dispatch = Mock()
    monkeypatch.setattr(jobs, '_dispatch_task', dispatch)
    request = APIRequestFactory().post('/api/news/1/translate/', {'force': False}, format='json')
    request.user = owner

    response = subscription_translation_response(request, article, force=False)
    assert response['Job-ID'] == str(handle.id)
    dispatch.assert_called_once_with(handle.id, handle.generation)
    response.close()


def test_sse_success_reconnect_replays_private_terminal_result(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    monkeypatch.setattr(
        jobs, 'stream_full_translation',
        lambda **kwargs: (kwargs['on_delta']('saved progress') or 'replayed result'),
    )
    jobs._run_persistent_task(handle.id, handle.generation)
    request = APIRequestFactory().post('/api/news/1/translate/', {'force': False}, format='json')
    request.user = owner
    response = subscription_translation_response(request, article, force=False)
    payload = b''.join(response.streaming_content).decode()
    assert response['Job-ID'] == str(handle.id)
    assert response['Cache-Control'] == 'no-store'
    assert 'event: complete' in payload
    assert 'replayed result' in payload
    assert 'progress' in payload


def test_failed_old_token_cannot_finalize_after_generation_reset(owner, article, monkeypatch):
    connection = make_connection(owner)
    handle = start_queued(owner, connection, article, monkeypatch)
    task = ChatGPTTranslationTask.objects.get(pk=handle.id)
    old_generation = task.generation
    ChatGPTTranslationTask.objects.filter(pk=task.pk).update(
        status='failed', error_code='translation_failed', finished_at=timezone.now(),
    )
    retried = jobs.start_or_get_job(owner, connection, article, force=True)
    assert retried.generation == old_generation + 1
    jobs._mark_failed(task.pk, old_generation, uuid.uuid4(), RuntimeError('stale'))
    fresh = ChatGPTTranslationTask.objects.get(pk=task.pk)
    assert fresh.generation == retried.generation
    assert fresh.status == 'queued'
    assert not SharedArticleTranslation.objects.exists()
