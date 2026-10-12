from __future__ import annotations

import base64
import json
import socket
from dataclasses import FrozenInstanceError

import pytest
from django.contrib.auth.models import User
from django.db import connection as django_connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import UserAIConnection, UserAIModelConfig, UserAITaskPreference
from api.services.ai_execution import ModelSelectionError, resolve_execution


ENCRYPTION_KEY = base64.urlsafe_b64encode(b't03-synthetic-app-encryption-key').decode('ascii').rstrip('=')
SYNTHETIC_PROVIDER_KEY = 'sk-t03-synthetic-provider-key-never-real'
TASK_KINDS = ('default', 'article_qa', 'full_translation', 'deep_research', 'question_suggestions')


@pytest.fixture(autouse=True)
def enable_test_settings(settings, monkeypatch):
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 't03-test-key-v1'
    settings.PUBLIC_SITE_MODE = 'full'
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:4000'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-' + ('b' * 32)

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError('preference settings and resolution must not contact a provider')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)


def _authenticated_client(username):
    user = User.objects.create_user(username=username, password='synthetic-password-123!')
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get(reverse('auth-csrf'))
    assert csrf.status_code == 200
    return client, user, csrf.json()['csrfToken']


def _create_connection(client, csrf, *, name):
    response = client.post(
        reverse('ai-connection-list'),
        {
            'provider_id': 'deepseek',
            'endpoint_profile': 'deepseek_default',
            'display_name': name,
            'api_key': SYNTHETIC_PROVIDER_KEY,
        },
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 201, response.content
    return response.json()['id']


def _add_model(client, csrf, connection_id, model_id):
    response = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'model_id': model_id},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 201, response.content
    return response.json()


def _patch_payload(**overrides):
    selections = {task_kind: None for task_kind in TASK_KINDS}
    selections.update(overrides)
    return {
        'preferences': [
            {'task_kind': task_kind, 'model_config_id': selections[task_kind]}
            for task_kind in TASK_KINDS
        ],
    }


@pytest.mark.django_db
def test_owner_reads_and_atomically_saves_five_preferences_without_provider_calls(monkeypatch):
    owner, owner_user, owner_csrf = _authenticated_client('preference-owner')
    other, _other_user, other_csrf = _authenticated_client('preference-other')
    owner_connection = _create_connection(owner, owner_csrf, name='Owner DeepSeek')
    other_connection = _create_connection(other, other_csrf, name='Other DeepSeek')
    owner_model = _add_model(owner, owner_csrf, owner_connection, 'vendor/owner-model')
    other_model = _add_model(other, other_csrf, other_connection, 'vendor/other-model')

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError('preference reads and saves must not contact a provider')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    url = reverse('ai-task-preferences')
    initial = owner.get(url)
    assert initial.status_code == 200
    assert initial['Cache-Control'] == 'no-store'
    assert [item['task_kind'] for item in initial.json()['preferences']] == list(TASK_KINDS)
    assert all(item['model_config_id'] is None for item in initial.json()['preferences'])
    assert all(item['selection_state'] in {'unset', 'inherit_default'} for item in initial.json()['preferences'])
    assert owner.get(url, {'lang': 'zh'}).status_code == 200
    assert owner.get(url, {'lang': 'zh', 'unexpected': 'value'}).status_code == 400
    assert owner.get(reverse('ai-model-list'), {'lang': 'zh'}).status_code == 200
    assert owner.get(reverse('ai-model-catalog'), {'lang': 'en'}).status_code == 200

    saved = owner.patch(
        url,
        _patch_payload(default=owner_model['id'], article_qa=owner_model['id'], deep_research=owner_model['id']),
        format='json',
        HTTP_X_CSRFTOKEN=owner_csrf,
    )
    assert saved.status_code == 200
    assert saved['Cache-Control'] == 'no-store'
    assert len(saved.json()['preferences']) == 5
    assert all(
        item['selection_state'] == ('available' if item['model_config_id'] else ('unset' if item['task_kind'] == 'default' else 'inherit_default'))
        for item in saved.json()['preferences']
    )
    assert SYNTHETIC_PROVIDER_KEY not in json.dumps(saved.json())
    assert 'credential_ciphertext' not in json.dumps(saved.json())
    assert UserAITaskPreference.objects.filter(user=owner_user).count() == 5

    other_saved = other.get(url)
    assert other_saved.status_code == 200
    assert all(item['model_config_id'] is None for item in other_saved.json()['preferences'])
    cross_owner = owner.patch(
        url,
        _patch_payload(default=other_model['id']),
        format='json',
        HTTP_X_CSRFTOKEN=owner_csrf,
    )
    assert cross_owner.status_code == 404
    assert owner.get(url).json()['preferences'][0]['model_config_id'] == owner_model['id']


@pytest.mark.django_db
def test_preference_patch_requires_exact_task_set_and_csrf(settings):
    client, _user, csrf = _authenticated_client('preference-validation')
    url = reverse('ai-task-preferences')
    valid = _patch_payload()
    assert client.get(url, {'lang': 'zh'}).status_code == 200

    missing = client.patch(url, {'preferences': valid['preferences'][:-1]}, format='json', HTTP_X_CSRFTOKEN=csrf)
    duplicate = client.patch(
        url,
        {'preferences': valid['preferences'][:-1] + [valid['preferences'][0]]},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    extra_field = client.patch(url, {**valid, 'fallback': 'site'}, format='json', HTTP_X_CSRFTOKEN=csrf)
    no_csrf = client.patch(url, valid, format='json')

    assert missing.status_code == 400
    assert duplicate.status_code == 400
    assert extra_field.status_code == 400
    assert no_csrf.status_code == 403
    assert UserAITaskPreference.objects.count() == 0

    settings.AI_BYOK_ENABLED = False
    disabled = client.get(url)
    assert disabled.status_code == 403
    assert disabled['Cache-Control'] == 'no-store'


@pytest.mark.django_db
def test_disabled_task_model_is_rejected_without_falling_back_to_default():
    client, user, csrf = _authenticated_client('preference-no-fallback')
    default_connection = _create_connection(client, csrf, name='Default connection')
    task_connection = _create_connection(client, csrf, name='Task connection')
    default_model = _add_model(client, csrf, default_connection, 'vendor/default-model')
    task_model = _add_model(client, csrf, task_connection, 'vendor/taskmodel')
    url = reverse('ai-task-preferences')
    initial = client.patch(
        url,
        _patch_payload(default=default_model['id'], article_qa=task_model['id']),
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert initial.status_code == 200

    connection = UserAIConnection.objects.get(pk=task_connection, user=user)
    connection.is_enabled = False
    connection.save(update_fields=['is_enabled', 'updated_at'])

    rejected = client.patch(
        url,
        _patch_payload(default=default_model['id'], article_qa=task_model['id']),
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert rejected.status_code == 409
    assert rejected.json()['error_code'] == 'model_connection_unavailable'
    assert client.get(url).json()['preferences'][0]['model_config_id'] == default_model['id']
    assert client.get(url).json()['preferences'][1]['model_config_id'] == task_model['id']
    with pytest.raises(ModelSelectionError) as exc_info:
        resolve_execution(user, 'article_qa')
    assert exc_info.value.code == 'model_unavailable'


@pytest.mark.django_db
def test_execution_snapshot_is_immutable_and_new_tasks_use_new_preferences():
    client, user, csrf = _authenticated_client('preference-snapshot')
    first_connection = _create_connection(client, csrf, name='First connection')
    second_connection = _create_connection(client, csrf, name='Second connection')
    first_model = _add_model(client, csrf, first_connection, 'vendor/first-model')
    second_model = _add_model(client, csrf, second_connection, 'vendor/second-model')
    url = reverse('ai-task-preferences')

    assert client.patch(
        url, _patch_payload(default=first_model['id']), format='json', HTTP_X_CSRFTOKEN=csrf,
    ).status_code == 200
    first_snapshot = resolve_execution(user, 'article_qa')
    assert first_snapshot.model_config_id == first_model['id']
    assert first_snapshot.selected_by_task_kind == 'default'
    with pytest.raises(FrozenInstanceError):
        first_snapshot.model_id = 'vendor/changed'

    assert client.patch(
        url, _patch_payload(default=second_model['id']), format='json', HTTP_X_CSRFTOKEN=csrf,
    ).status_code == 200
    second_snapshot = resolve_execution(user, 'article_qa')
    assert first_snapshot.model_config_id == first_model['id']
    assert first_snapshot.model_id == 'vendor/first-model'
    assert second_snapshot.model_config_id == second_model['id']
    assert first_snapshot.digest != second_snapshot.digest


@pytest.mark.django_db
def test_resolver_locks_task_and_default_preferences_in_one_sorted_query():
    client, user, csrf = _authenticated_client('preference-lock-order')
    connection_id = _create_connection(client, csrf, name='Lock order connection')
    model = _add_model(client, csrf, connection_id, 'vendor/lock-order-model')
    assert client.patch(
        reverse('ai-task-preferences'),
        _patch_payload(default=model['id']),
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    ).status_code == 200

    with CaptureQueriesContext(django_connection) as captured:
        snapshot = resolve_execution(user, 'full_translation')

    table = UserAITaskPreference._meta.db_table.lower()
    preference_queries = [
        entry['sql'] for entry in captured.captured_queries
        if table in entry['sql'].lower() and 'task_kind' in entry['sql'].lower()
    ]
    assert len(preference_queries) == 1
    sql = preference_queries[0].lower()
    assert ' in ' in sql
    assert 'default' in sql and 'full_translation' in sql
    assert 'order by' in sql
    assert sql.index('order by') < sql.index('task_kind', sql.index('order by'))
    assert snapshot.selected_by_task_kind == 'default'
    assert snapshot.model_config_id == model['id']


@pytest.mark.django_db
def test_preference_patch_and_model_delete_lock_preferences_in_task_kind_order():
    client, _user, csrf = _authenticated_client('preference-mutation-lock-order')
    connection_id = _create_connection(client, csrf, name='Mutation lock order connection')
    model = _add_model(client, csrf, connection_id, 'vendor/lock-order')
    table = UserAITaskPreference._meta.db_table.lower()

    with CaptureQueriesContext(django_connection) as patch_queries:
        patched = client.patch(
            reverse('ai-task-preferences'),
            _patch_payload(default=model['id']),
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )
    assert patched.status_code == 200
    patch_locks = [
        entry['sql'].lower() for entry in patch_queries.captured_queries
        if table in entry['sql'].lower() and 'order by' in entry['sql'].lower()
    ]
    assert patch_locks
    assert all(
        sql.index('order by') < sql.index('task_kind', sql.index('order by'))
        for sql in patch_locks
    )

    with CaptureQueriesContext(django_connection) as delete_queries:
        deleted = client.delete(
            reverse('ai-model-detail', kwargs={'model_id': model['id']}),
            HTTP_X_CSRFTOKEN=csrf,
        )
    assert deleted.status_code == 200
    delete_locks = [
        entry['sql'].lower() for entry in delete_queries.captured_queries
        if table in entry['sql'].lower() and 'order by' in entry['sql'].lower()
    ]
    assert delete_locks
    assert all(
        sql.index('order by') < sql.index('task_kind', sql.index('order by'))
        for sql in delete_locks
    )


@pytest.mark.django_db
def test_deleted_selected_model_requires_reselection_and_never_inherits_implicitly():
    client, user, csrf = _authenticated_client('preference-deleted-model')
    connection_id = _create_connection(client, csrf, name='Selected connection')
    model = _add_model(client, csrf, connection_id, 'vendor/selected-model')
    url = reverse('ai-task-preferences')
    assert client.patch(
        url, _patch_payload(default=model['id']), format='json', HTTP_X_CSRFTOKEN=csrf,
    ).status_code == 200

    deleted = client.delete(
        reverse('ai-model-detail', kwargs={'model_id': model['id']}),
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert deleted.status_code == 200
    default_preference = client.get(url).json()['preferences'][0]
    assert default_preference['model_config_id'] is None
    assert default_preference['selection_state'] == 'needs_reselection'
    with pytest.raises(ModelSelectionError) as exc_info:
        resolve_execution(user, 'article_qa')
    assert exc_info.value.code == 'model_reselection_required'

    assert UserAIModelConfig.objects.filter(pk=model['id']).exists() is False
    assert UserAITaskPreference.objects.get(user=user, task_kind='default').requires_reselection is True

    accepted_inheritance = client.patch(
        url, _patch_payload(), format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert accepted_inheritance.status_code == 200
    with pytest.raises(ModelSelectionError) as no_default:
        resolve_execution(user, 'article_qa')
    assert no_default.value.code == 'model_not_configured'


@pytest.mark.django_db
def test_execution_override_is_still_owner_scoped_and_missing_default_fails_closed():
    owner, owner_user, owner_csrf = _authenticated_client('preference-override-owner')
    other, _other_user, other_csrf = _authenticated_client('preference-override-other')
    owner_connection = _create_connection(owner, owner_csrf, name='Owner connection')
    other_connection = _create_connection(other, other_csrf, name='Other connection')
    _add_model(other, other_csrf, other_connection, 'vendor/private-other-model')

    with pytest.raises(ModelSelectionError) as missing:
        resolve_execution(owner_user, 'article_qa')
    assert missing.value.code == 'model_not_configured'

    other_config = UserAIModelConfig.objects.get(connection__user=_other_user)
    with pytest.raises(ModelSelectionError) as cross_owner:
        resolve_execution(owner_user, 'article_qa', model_config_id=other_config.pk)
    assert cross_owner.value.code == 'model_not_found'

    connection = UserAIConnection.objects.get(pk=owner_connection)
    assert connection.user_id == owner_user.pk


@pytest.mark.django_db
def test_corrupt_cross_owner_preference_is_hidden_and_fails_closed():
    owner, owner_user, _owner_csrf = _authenticated_client('preference-corrupt-owner')
    other, other_user, other_csrf = _authenticated_client('preference-corrupt-other')
    other_connection = _create_connection(other, other_csrf, name='Private other connection')
    other_model = _add_model(other, other_csrf, other_connection, 'vendor/privateothermodel')
    foreign_config = UserAIModelConfig.objects.get(pk=other_model['id'], connection__user=other_user)
    UserAITaskPreference.objects.create(
        user=owner_user,
        task_kind='default',
        model_config=foreign_config,
    )

    response = owner.get(reverse('ai-task-preferences'))
    default_preference = response.json()['preferences'][0]
    assert response.status_code == 200
    assert default_preference == {
        'task_kind': 'default',
        'model_config_id': None,
        'selection_state': 'needs_reselection',
        'model': None,
    }
    assert str(foreign_config.pk) not in json.dumps(response.json())
    with pytest.raises(ModelSelectionError) as exc_info:
        resolve_execution(owner_user, 'default')
    assert exc_info.value.code == 'model_not_found'
