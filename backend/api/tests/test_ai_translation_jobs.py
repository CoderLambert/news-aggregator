from __future__ import annotations

import base64
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, close_old_connections, connection as django_connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Category,
    ChatGPTArticleTranslation,
    ChatGPTTranslationTask,
    News,
    SharedArticleTranslation,
    Source,
    UserAIModelConfig,
    UserAITaskPreference,
)
from api.services import ai_translation, chatgpt_subscription_jobs as translation_jobs
from api.services.ai_execution import ExecutionSnapshot
from api.services.ai_translation import BYOKTranslationError, BYOKTranslationExecution


SYNTHETIC_PROVIDER_KEY_A = 'sk-t05-synthetic-owner-a-key'
SYNTHETIC_PROVIDER_KEY_B = 'sk-t05-synthetic-owner-b-key'
ENCRYPTION_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode('ascii').rstrip('=')


@pytest.fixture(autouse=True)
def enable_test_settings(settings):
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 't05-test-key-v1'
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:4000'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-' + ('t' * 32)
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    settings.SECURE_SSL_REDIRECT = False


def _authenticated_client(username):
    user = User.objects.create_user(username=username, password='synthetic-password-123!')
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get(reverse('auth-csrf')).json()['csrfToken']
    return client, user, csrf


def _create_model(client, csrf, provider_key, suffix):
    connection = client.post(
        reverse('ai-connection-list'),
        {
            'provider_id': 'deepseek',
            'endpoint_profile': 'deepseek_default',
            'display_name': f'T05 {suffix} connection',
            'api_key': provider_key,
        },
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert connection.status_code == 201, connection.content
    model = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection.json()['id'], 'catalog_model_id': 'deepseek-flash'},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert model.status_code == 201, model.content
    config = UserAIModelConfig.objects.get(pk=model.json()['id'])
    UserAITaskPreference.objects.update_or_create(
        user=config.connection.user,
        task_kind='full_translation',
        defaults={'model_config': config, 'requires_reselection': False},
    )
    return connection.json()['id'], config


def _create_news(full_content='## Headline\n\nA safe synthetic article.'):
    sequence = News.objects.count()
    category = Category.objects.create(name=f'T05 Translation {sequence}', slug=f't05-{sequence}')
    source = Source.objects.create(name=f'T05 source {sequence}', url=f'https://t05-{sequence}.example.test')
    return News.objects.create(
        title='T05 article',
        content='Synthetic summary.',
        full_content=full_content,
        publish_time=timezone.now(),
        source=source,
        category=category,
        url=f'https://t05-{sequence}.example.test/article',
    )


def _post_translation(client, csrf, news, key):
    return client.post(
        reverse('ai-translation-start', args=[news.pk]),
        {},
        format='json',
        HTTP_IDEMPOTENCY_KEY=key,
        HTTP_X_CSRFTOKEN=csrf,
    )


def _run_inline(monkeypatch):
    monkeypatch.setattr(
        translation_jobs,
        '_dispatch_task',
        lambda task_id, generation: translation_jobs._run_persistent_task(task_id, generation),
    )


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_private_translation_completes_once_and_get_restores_owner_result(monkeypatch):
    client, user, csrf = _authenticated_client('t05-success')
    _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'success')
    news = _create_news()
    calls = []

    def fake_stream(execution, article, *, on_delta, execution_guard):
        calls.append((execution.provider_key, article))
        execution_guard()
        on_delta('完整中文译文')
        execution_guard()
        return '完整中文译文'

    monkeypatch.setattr(translation_jobs, 'stream_byok_translation', fake_stream)
    _run_inline(monkeypatch)

    response = _post_translation(client, csrf, news, 't05-success-1')
    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    body = b''.join(response.streaming_content).decode('utf-8')
    task = ChatGPTTranslationTask.objects.get(pk=response['Job-ID'])
    assert task.status == 'succeeded'
    assert task.result['full_content_zh'] == '完整中文译文'
    assert task.result['full_content_zh_scope'] == 'private'
    assert task.result['full_content_zh_source'] == 'byok'
    assert task.result['result_id']
    assert '"result_id"' in body and '"full_content_zh_scope": "private"' in body
    assert calls == [(SYNTHETIC_PROVIDER_KEY_A, news.full_content)]
    assert ChatGPTArticleTranslation.objects.filter(user=user, ai_connection=task.ai_connection).count() == 1
    assert SharedArticleTranslation.objects.count() == 0
    news.refresh_from_db()
    assert not news.full_content_zh

    again = _post_translation(client, csrf, news, 't05-success-1')
    assert again.status_code == 200
    b''.join(again.streaming_content)
    assert again['Job-ID'] == response['Job-ID']
    assert len(calls) == 1

    owner_get = client.get(reverse('ai-translation-job', args=[task.pk]))
    assert owner_get.status_code == 200
    assert owner_get['Cache-Control'] == 'no-store'
    assert owner_get.json()['result']['result_id'] == task.result['result_id']
    other_client, _other_user, _other_csrf = _authenticated_client('t05-other')
    assert other_client.get(reverse('ai-translation-job', args=[task.pk])).status_code == 404


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_same_idempotency_key_with_different_article_is_conflict(monkeypatch):
    client, _user, csrf = _authenticated_client('t05-idem-conflict')
    _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'conflict')
    first = _create_news('First article.')
    second = _create_news('Second article.')
    _run_inline(monkeypatch)
    monkeypatch.setattr(
        translation_jobs,
        'stream_byok_translation',
        lambda _execution, _article, **_kwargs: '完整译文',
    )
    success = _post_translation(client, csrf, first, 't05-reused-key')
    assert success.status_code == 200
    b''.join(success.streaming_content)
    conflict = _post_translation(client, csrf, second, 't05-reused-key')
    assert conflict.status_code == 409
    assert conflict.json()['error_code'] == 'idempotency_key_reused'
    assert ChatGPTTranslationTask.objects.filter(idempotency_key='t05-reused-key').count() == 1


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_two_users_get_separate_private_translations_for_same_article(monkeypatch):
    client_a, user_a, csrf_a = _authenticated_client('t05-owner-a')
    client_b, user_b, csrf_b = _authenticated_client('t05-owner-b')
    _create_model(client_a, csrf_a, SYNTHETIC_PROVIDER_KEY_A, 'owner-a')
    _create_model(client_b, csrf_b, SYNTHETIC_PROVIDER_KEY_B, 'owner-b')
    news = _create_news()
    observed_keys = []

    def fake_stream(execution, _article, **_kwargs):
        observed_keys.append(execution.provider_key)
        return 'A 的私有译文' if execution.provider_key == SYNTHETIC_PROVIDER_KEY_A else 'B 的私有译文'

    monkeypatch.setattr(translation_jobs, 'stream_byok_translation', fake_stream)
    _run_inline(monkeypatch)
    response_a = _post_translation(client_a, csrf_a, news, 'same-user-scoped-key')
    response_b = _post_translation(client_b, csrf_b, news, 'same-user-scoped-key')
    b''.join(response_a.streaming_content)
    b''.join(response_b.streaming_content)

    task_a = ChatGPTTranslationTask.objects.get(pk=response_a['Job-ID'])
    task_b = ChatGPTTranslationTask.objects.get(pk=response_b['Job-ID'])
    assert task_a.ai_connection_id != task_b.ai_connection_id
    assert task_a.result['full_content_zh'] == 'A 的私有译文'
    assert task_b.result['full_content_zh'] == 'B 的私有译文'
    assert observed_keys == [SYNTHETIC_PROVIDER_KEY_A, SYNTHETIC_PROVIDER_KEY_B]
    assert ChatGPTArticleTranslation.objects.filter(news=news).count() == 2
    assert not SharedArticleTranslation.objects.filter(news=news).exists()
    assert client_a.get(reverse('ai-translation-job', args=[task_b.pk])).status_code == 404
    assert client_b.get(reverse('ai-translation-job', args=[task_a.pk])).status_code == 404
    assert ChatGPTArticleTranslation.objects.filter(user=user_a, news=news).count() == 1
    assert ChatGPTArticleTranslation.objects.filter(user=user_b, news=news).count() == 1


@pytest.mark.django_db(transaction=True)
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_concurrent_same_idempotency_key_attaches_to_one_durable_task(monkeypatch):
    client, user, csrf = _authenticated_client('t05-concurrent-idempotency')
    _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'concurrent')
    news = _create_news()
    barrier = threading.Barrier(2)
    dispatch_lock = threading.Lock()
    dispatched = set()

    def count_once(task_id, _generation):
        with dispatch_lock:
            dispatched.add(str(task_id))

    monkeypatch.setattr(translation_jobs, '_dispatch_task', count_once)

    def submit_same_request():
        close_old_connections()
        try:
            current_user = User.objects.get(pk=user.pk)
            current_news = News.objects.get(pk=news.pk)
            barrier.wait(timeout=5)
            return translation_jobs.start_or_get_byok_job(
                current_user, current_news, 't05-concurrent-key',
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        handles = list(executor.map(lambda _index: submit_same_request(), range(2)))

    assert str(handles[0].id) == str(handles[1].id)
    assert ChatGPTTranslationTask.objects.filter(user=user, idempotency_key='t05-concurrent-key').count() == 1
    assert dispatched == {str(handles[0].id)}


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_long_article_and_missing_idempotency_key_are_rejected_without_task():
    client, _user, csrf = _authenticated_client('t05-budget')
    _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'budget')
    long_article = _create_news('x' * (ai_translation.MAX_TRANSLATION_SOURCE_CHARS + 1))

    too_long = _post_translation(client, csrf, long_article, 't05-too-long')
    assert too_long.status_code == 413
    assert too_long.json()['error_code'] == 'source_too_long'
    missing_key = client.post(
        reverse('ai-translation-start', args=[long_article.pk]),
        {}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert missing_key.status_code == 400
    assert missing_key.json()['error_code'] == 'invalid_idempotency_key'
    assert ChatGPTTranslationTask.objects.count() == 0


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_credential_epoch_change_during_worker_discards_partial_output(monkeypatch):
    client, user, csrf = _authenticated_client('t05-epoch')
    _connection_id, _model = _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'epoch')
    news = _create_news()
    connection = user.ai_connections.get()
    calls = []

    def revoke_during_stream(execution, _article, *, on_delta, execution_guard):
        calls.append('started')
        execution_guard()
        on_delta('未完成片段')
        from django.db.models import F
        from api.models import UserAIConnection
        UserAIConnection.objects.filter(pk=connection.pk).update(
            is_enabled=False,
            credential_epoch=F('credential_epoch') + 1,
        )
        execution_guard()
        calls.append('must-not-continue')
        return '不得保存的完整译文'

    monkeypatch.setattr(translation_jobs, 'stream_byok_translation', revoke_during_stream)
    _run_inline(monkeypatch)
    response = _post_translation(client, csrf, news, 't05-epoch-change')
    body = b''.join(response.streaming_content).decode('utf-8')
    task = ChatGPTTranslationTask.objects.get(pk=response['Job-ID'])
    assert task.status == 'failed'
    assert task.error_code == 'execution_changed'
    assert task.result == {}
    assert task.progress == '未完成片段'
    assert calls == ['started']
    assert not ChatGPTArticleTranslation.objects.filter(user=user, news=news).exists()
    assert 'complete' not in body


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_database_failure_after_private_result_write_rolls_back_result_and_success(monkeypatch):
    client, user, csrf = _authenticated_client('t05-db-failure')
    _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'db-failure')
    news = _create_news()
    original_save = translation_jobs._save_byok_translation_result

    def save_then_fail(task, text):
        original_save(task, text)
        raise IntegrityError('synthetic commit failure')

    monkeypatch.setattr(translation_jobs, '_save_byok_translation_result', save_then_fail)
    monkeypatch.setattr(
        translation_jobs,
        'stream_byok_translation',
        lambda _execution, _article, **_kwargs: '完整译文',
    )
    _run_inline(monkeypatch)
    response = _post_translation(client, csrf, news, 't05-db-failure')
    body = b''.join(response.streaming_content).decode('utf-8')
    task = ChatGPTTranslationTask.objects.get(pk=response['Job-ID'])
    assert task.status == 'failed'
    assert task.result == {}
    assert not ChatGPTArticleTranslation.objects.filter(user=user, news=news).exists()
    assert 'complete' not in body


def _unit_execution():
    snapshot = ExecutionSnapshot(
        user_id=1,
        task_kind='full_translation',
        selected_by_task_kind='full_translation',
        model_config_id='00000000-0000-0000-0000-000000000001',
        connection_id='00000000-0000-0000-0000-000000000002',
        provider_id='deepseek',
        endpoint_profile='deepseek_default',
        endpoint_profile_version=1,
        credential_epoch=1,
        config_revision=1,
        model_id='deepseek-flash',
        digest='synthetic-digest',
    )
    return BYOKTranslationExecution(
        snapshot=snapshot,
        gateway_url='http://127.0.0.1:4000',
        project_key='sk-synthetic-project-key',
        provider_key='sk-synthetic-provider-key',
        model_alias='news.deepseek-flash',
        model_source={'provider': 'DeepSeek', 'model': 'Synthetic Flash'},
    )


class _FakeResponseStream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def __iter__(self):
        return iter(self.events)

    def close(self):
        return None


class _FakeOpenAI:
    events = []

    def __init__(self, **_kwargs):
        self.http_client = _kwargs['http_client']
        self.responses = SimpleNamespace(
            create=lambda **_request: _FakeResponseStream(self.events),
        )

    def close(self):
        self.http_client.close()


def test_provider_stream_requires_explicit_completed_terminal(monkeypatch):
    deltas = []
    monkeypatch.setattr(ai_translation, 'OpenAI', _FakeOpenAI)
    _FakeOpenAI.events = [SimpleNamespace(type='response.output_text.delta', delta='partial')]
    with pytest.raises(BYOKTranslationError) as error:
        ai_translation.stream_byok_translation(
            _unit_execution(), 'Synthetic article.', on_delta=deltas.append,
            execution_guard=lambda: None,
        )
    assert error.value.code == 'incomplete_response'
    assert deltas == ['partial']

    deltas.clear()
    _FakeOpenAI.events = [
        SimpleNamespace(type='response.output_text.delta', delta='complete'),
        SimpleNamespace(
            type='response.completed',
            response=SimpleNamespace(status='completed', output_text='complete'),
        ),
    ]
    output = ai_translation.stream_byok_translation(
        _unit_execution(), 'Synthetic article.', on_delta=deltas.append,
        execution_guard=lambda: None,
    )
    assert output == 'complete'
    assert deltas == ['complete']


@pytest.mark.django_db(transaction=True)
def test_0037_migration_preserves_existing_subscription_translation_rows():
    executor = MigrationExecutor(django_connection)
    old_target = ('api', '0036_user_ai_task_preferences')
    new_target = ('api', '0037_byok_private_translation')
    executor.migrate([old_target])
    old_apps = executor.loader.project_state([old_target]).apps
    now = timezone.now()
    user = User.objects.create_user(username='t05-migration-owner', password='synthetic-password-123!')
    OldCategory = old_apps.get_model('api', 'Category')
    OldSource = old_apps.get_model('api', 'Source')
    OldNews = old_apps.get_model('api', 'News')
    OldConnection = old_apps.get_model('api', 'ChatGPTSubscriptionConnection')
    OldTranslation = old_apps.get_model('api', 'ChatGPTArticleTranslation')
    OldTask = old_apps.get_model('api', 'ChatGPTTranslationTask')

    category = OldCategory.objects.create(name='T05 Migration', slug='t05-migration')
    source = OldSource.objects.create(name='T05 Migration Source', url='https://t05-migration.example.test')
    news = OldNews.objects.create(
        title='Legacy translation',
        content='Legacy summary.',
        publish_time=now,
        source=source,
        category=category,
        url='https://t05-migration.example.test/article',
        full_content='Legacy source Markdown.',
    )
    legacy_connection = OldConnection.objects.create(
        user_id=user.pk,
        subject_hash='a' * 64,
        issuer='https://auth.example.test',
        issued_client_id='legacy-client',
        registration_key_hash='b' * 64,
        encrypted_access_token='encrypted-access',
        encrypted_refresh_token='encrypted-refresh',
        selected_model='legacy-model',
        is_active=True,
        generation=1,
    )
    translation = OldTranslation.objects.create(
        user_id=user.pk,
        connection_id=legacy_connection.pk,
        news_id=news.pk,
        source_hash='c' * 64,
        model_slug='legacy-model',
        content='保留的订阅译文',
        completed_at=now,
    )
    task = OldTask.objects.create(
        user_id=user.pk,
        connection_id=legacy_connection.pk,
        news_id=news.pk,
        source_hash='c' * 64,
        model_slug='legacy-model',
        connection_generation=1,
        status='succeeded',
        provider_started=True,
        progress='legacy progress',
        result={'full_content_zh': '保留的订阅译文'},
        finished_at=now,
    )

    try:
        executor = MigrationExecutor(django_connection)
        executor.migrate([new_target])
        new_apps = executor.loader.project_state([new_target]).apps
        NewTranslation = new_apps.get_model('api', 'ChatGPTArticleTranslation')
        NewTask = new_apps.get_model('api', 'ChatGPTTranslationTask')
        migrated_translation = NewTranslation.objects.get(pk=translation.pk)
        migrated_task = NewTask.objects.get(pk=task.pk)
        assert migrated_translation.connection_id == legacy_connection.pk
        assert migrated_translation.ai_connection_id is None
        assert migrated_translation.content == '保留的订阅译文'
        assert migrated_task.connection_id == legacy_connection.pk
        assert migrated_task.ai_connection_id is None
        assert migrated_task.connection_generation == 1
        assert migrated_task.status == 'succeeded'
        assert migrated_task.progress == 'legacy progress'
        assert migrated_task.result == {'full_content_zh': '保留的订阅译文'}
    finally:
        restore = MigrationExecutor(django_connection)
        restore.migrate(restore.loader.graph.leaf_nodes())


@pytest.mark.django_db
@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_closing_sse_reader_does_not_cancel_persistent_worker(monkeypatch):
    client, _user, csrf = _authenticated_client('t05-sse-close')
    _create_model(client, csrf, SYNTHETIC_PROVIDER_KEY_A, 'sse-close')
    news = _create_news()
    monkeypatch.setattr(translation_jobs, '_dispatch_task', lambda *_args: None)
    response = _post_translation(client, csrf, news, 't05-sse-close')
    task = ChatGPTTranslationTask.objects.get(pk=response['Job-ID'])
    ChatGPTTranslationTask.objects.filter(pk=task.pk).update(progress='先到的片段')
    stream = response.streaming_content
    first_chunk = next(stream)
    response.close()
    task.refresh_from_db()
    assert task.status == 'queued'

    def fake_stream(_execution, _article, *, on_delta, execution_guard):
        execution_guard()
        on_delta('后续片段')
        return '先到的片段后续片段'

    monkeypatch.setattr(translation_jobs, 'stream_byok_translation', fake_stream)
    translation_jobs._run_persistent_task(task.pk, task.generation)

    task.refresh_from_db()
    first_text = first_chunk.decode('utf-8') if isinstance(first_chunk, bytes) else first_chunk
    assert 'progress' in first_text
    assert task.status == 'succeeded'
    assert task.result['full_content_zh'] == '先到的片段后续片段'
