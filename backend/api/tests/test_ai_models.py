from __future__ import annotations

import base64
import json
import socket

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import AICallAttempt, UserAIConnection, UserAIModelConfig
from api.services.ai_credentials import encrypt_credential
from api.services.ai_model_test import ProbeOutcome


ENCRYPTION_KEY = base64.urlsafe_b64encode(b't02-synthetic-app-encryption-key').decode('ascii').rstrip('=')
SYNTHETIC_PROVIDER_KEY = 'sk-t02-synthetic-provider-key-never-real'


@pytest.fixture(autouse=True)
def enable_test_settings(settings):
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 't02-test-key-v1'
    settings.PUBLIC_SITE_MODE = 'full'
    settings.AI_BYOK_GATEWAY_URL = 'http://127.0.0.1:4000'
    settings.AI_BYOK_GATEWAY_PROJECT_KEY = 'sk-' + ('a' * 32)


def _authenticated_client(username):
    user = User.objects.create_user(username=username, password='synthetic-password-123!')
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get(reverse('auth-csrf'))
    assert csrf.status_code == 200
    return client, user, csrf.json()['csrfToken']


def _create_connection(client, csrf, *, username='t02-owner'):
    response = client.post(
        reverse('ai-connection-list'),
        {
            'provider_id': 'deepseek',
            'endpoint_profile': 'deepseek_default',
            'display_name': username,
            'api_key': SYNTHETIC_PROVIDER_KEY,
        },
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 201
    return response.json()['id']


def _add_model(client, csrf, connection_id, *, model_id='vendor/model-one'):
    return client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'model_id': model_id},
        format='json',
        HTTP_X_CSRFTOKEN=csrf,
    )


@pytest.mark.django_db
def test_versioned_catalog_is_fixed_no_store_and_does_not_contact_provider(monkeypatch):
    client, _user, _csrf = _authenticated_client('model-catalog-owner')

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError('model catalog reads must not contact a provider')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    response = client.get(reverse('ai-model-catalog'), {'provider_id': 'deepseek', 'lang': 'zh'})

    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    payload = response.json()
    assert payload['catalog_version'] == '2026-10-12.1'
    assert len(payload['models']) == 1
    preset = payload['models'][0]
    assert preset['catalog_model_id'] == 'deepseek-flash'
    assert preset['model_id'] == 'deepseek-flash'
    assert preset['context_window_tokens'] == 1_048_576
    assert preset['max_output_tokens'] == 393_216
    assert 'proxy_model_alias' not in preset
    assert UserAIConnection.objects.count() == 0


@pytest.mark.django_db
def test_owner_can_add_multiple_catalog_and_manual_models_without_provider_calls(monkeypatch):
    owner, owner_user, owner_csrf = _authenticated_client('model-config-owner')
    owner_connection = _create_connection(owner, owner_csrf, username='owner connection')
    other, _other_user, other_csrf = _authenticated_client('model-config-other')
    other_connection = _create_connection(other, other_csrf, username='other connection')

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError('model config CRUD must not contact a provider')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    catalog_model = owner.post(
        reverse('ai-model-list'),
        {'connection_id': owner_connection, 'catalog_model_id': 'deepseek-flash'},
        format='json',
        HTTP_X_CSRFTOKEN=owner_csrf,
    )
    manual_model = _add_model(owner, owner_csrf, owner_connection, model_id='vendor/custom-2026')
    duplicate_model = _add_model(owner, owner_csrf, owner_connection, model_id='vendor/custom-2026')

    assert catalog_model.status_code == 201
    assert manual_model.status_code == 201
    assert duplicate_model.status_code == 409
    assert catalog_model['Cache-Control'] == 'no-store'
    assert manual_model['Cache-Control'] == 'no-store'
    catalog_payload = catalog_model.json()
    manual_payload = manual_model.json()
    assert catalog_payload['source'] == 'catalog'
    assert catalog_payload['catalog_version'] == '2026-10-12.1'
    assert catalog_payload['has_trusted_context_limit'] is True
    assert catalog_payload['context_window_tokens'] == 1_048_576
    assert catalog_payload['verification_status'] == 'not_tested'
    assert catalog_payload['capabilities'] == {
        'text': 'unknown', 'tools': 'unknown', 'structured_output': 'unknown',
        'thinking': 'unknown', 'stream': 'unknown',
    }
    assert manual_payload['source'] == 'manual'
    assert manual_payload['has_trusted_context_limit'] is False
    assert manual_payload['context_window_tokens'] is None
    assert manual_payload['verification_status'] == 'not_tested'
    assert 'proxy_model_alias' not in manual_payload
    assert SYNTHETIC_PROVIDER_KEY not in json.dumps([catalog_payload, manual_payload])

    listing = owner.get(reverse('ai-model-list'))
    assert listing.status_code == 200
    assert len(listing.json()['models']) == 2
    assert other.get(reverse('ai-model-list')).json()['models'] == []
    assert other.patch(
        reverse('ai-model-detail', kwargs={'model_id': manual_payload['id']}),
        {'display_name': 'Cross-connection attempt'}, format='json', HTTP_X_CSRFTOKEN=other_csrf,
    ).status_code == 404

    cross_owner = owner.post(
        reverse('ai-model-list'),
        {'connection_id': other_connection, 'model_id': 'vendor/forbidden'},
        format='json', HTTP_X_CSRFTOKEN=owner_csrf,
    )
    assert cross_owner.status_code == 404
    assert UserAIModelConfig.objects.filter(connection__user=owner_user).count() == 2


@pytest.mark.django_db
def test_manual_model_ids_are_still_available_when_directory_fetch_fails(monkeypatch):
    client, _user, csrf = _authenticated_client('manual-model-fallback')
    connection_id = _create_connection(client, csrf)
    catalog_url = reverse('ai-model-catalog')
    monkeypatch.setattr('api.ai_model_views.model_catalog', lambda *_args: (_ for _ in ()).throw(RuntimeError('catalog unavailable')))
    client.raise_request_exception = False

    failed_catalog = client.get(catalog_url, {'provider_id': 'openai'})
    manual = _add_model(client, csrf, connection_id, model_id='unlisted/custom-model')

    assert failed_catalog.status_code == 503
    assert failed_catalog.json()['models'] == []
    assert failed_catalog.json()['catalog_available'] is False
    assert manual.status_code == 201
    assert manual.json()['model_id'] == 'unlisted/custom-model'
    assert manual.json()['verification_status'] == 'not_tested'


@pytest.mark.django_db
def test_model_mutation_is_strict_and_config_revision_resets_capabilities(db):
    client, _user, csrf = _authenticated_client('model-update-owner')
    connection_id = _create_connection(client, csrf)
    created = _add_model(client, csrf, connection_id, model_id='vendor/model-before')
    model_id = created.json()['id']
    model = UserAIModelConfig.objects.get(pk=model_id)
    model.verification_status = 'verified'
    model.verified_credential_epoch = model.connection.credential_epoch
    model.verified_config_revision = model.config_revision
    model.verified_endpoint_profile_version = model.connection.endpoint_profile_version
    model.capability_snapshot = {'text': 'supported', 'tools': 'unknown'}
    model.save()

    extra_field = client.patch(
        reverse('ai-model-detail', kwargs={'model_id': model_id}),
        {'display_name': 'valid', 'extra_body': {'api_base': 'https://attacker.example'}},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    changed = client.patch(
        reverse('ai-model-detail', kwargs={'model_id': model_id}),
        {'model_id': 'vendor/model-after'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )

    assert extra_field.status_code == 400
    assert changed.status_code == 200
    assert changed.json()['config_revision'] == 2
    assert changed.json()['verification_status'] == 'not_tested'
    assert changed.json()['capabilities'] == {
        'text': 'unknown', 'tools': 'unknown', 'structured_output': 'unknown',
        'thinking': 'unknown', 'stream': 'unknown',
    }
    assert changed.json()['context_window_tokens'] is None
    assert client.delete(
        reverse('ai-model-detail', kwargs={'model_id': model_id}), HTTP_X_CSRFTOKEN=csrf,
    ).json() == {'deleted': True}
    assert UserAIModelConfig.objects.filter(pk=model_id).exists() is False


@pytest.mark.django_db
def test_key_rotation_marks_model_verification_stale_and_model_ids_reject_urls():
    client, _user, csrf = _authenticated_client('model-stale-owner')
    connection_id = _create_connection(client, csrf)
    created = _add_model(client, csrf, connection_id, model_id='vendor/stale-test')
    model = UserAIModelConfig.objects.get(pk=created.json()['id'])
    model.verification_status = 'verified'
    model.verified_credential_epoch = model.connection.credential_epoch
    model.verified_config_revision = model.config_revision
    model.verified_endpoint_profile_version = model.connection.endpoint_profile_version
    model.save()

    replaced = client.put(
        reverse('ai-connection-key', kwargs={'connection_id': connection_id}),
        {'api_key': 'sk-t02-replacement-synthetic-key'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    stale = client.get(reverse('ai-model-list')).json()['models'][0]
    url_model = _add_model(client, csrf, connection_id, model_id='https://attacker.example/v1')
    unknown_parameter = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'model_id': 'vendor/unsafe', 'api_base': 'https://attacker.example'},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )

    assert replaced.status_code == 200
    assert stale['verification_status'] == 'stale'
    assert url_model.status_code == 400
    assert unknown_parameter.status_code == 400


@pytest.mark.django_db
def test_endpoint_profile_revision_marks_existing_model_test_stale():
    client, _user, csrf = _authenticated_client('model-endpoint-revision-owner')
    connection_id = _create_connection(client, csrf)
    created = _add_model(client, csrf, connection_id, model_id='vendor/profile-bound')
    model = UserAIModelConfig.objects.get(pk=created.json()['id'])
    connection = model.connection
    model.verification_status = 'verified'
    model.verified_credential_epoch = connection.credential_epoch
    model.verified_config_revision = model.config_revision
    model.verified_endpoint_profile_version = connection.endpoint_profile_version
    model.save()
    connection.endpoint_profile_version += 1
    connection.save(update_fields=['endpoint_profile_version'])

    refreshed = client.get(reverse('ai-model-list'))

    assert refreshed.status_code == 200
    assert refreshed.json()['models'][0]['verification_status'] == 'stale'


@pytest.mark.django_db
def test_model_endpoints_require_session_and_csrf_for_mutation():
    anonymous = APIClient(enforce_csrf_checks=True)
    anonymous_list = anonymous.get(reverse('ai-model-list'))
    assert anonymous_list.status_code == 403
    assert anonymous_list['Cache-Control'] == 'no-store'
    blocked = anonymous.post(
        reverse('ai-model-list'),
        {'connection_id': '00000000-0000-0000-0000-000000000001', 'model_id': 'vendor/model'},
        format='json',
    )
    assert blocked.status_code == 403
    assert blocked['Cache-Control'] == 'no-store'

    owner = User.objects.create_user(username='model-csrf-owner', password='synthetic-password-123!')
    authenticated_without_csrf = APIClient(enforce_csrf_checks=True)
    authenticated_without_csrf.force_login(owner)
    blocked_session_mutation = authenticated_without_csrf.post(
        reverse('ai-model-list'),
        {'connection_id': '00000000-0000-0000-0000-000000000001', 'model_id': 'vendor/model'},
        format='json',
    )
    assert blocked_session_mutation.status_code == 403
    assert blocked_session_mutation['Cache-Control'] == 'no-store'
    blocked_session_test = authenticated_without_csrf.post(
        reverse('ai-model-test', kwargs={'model_id': '00000000-0000-0000-0000-000000000001'}),
        {'probe_kind': 'text'}, format='json',
    )
    assert blocked_session_test.status_code == 403
    assert blocked_session_test['Cache-Control'] == 'no-store'


@pytest.mark.django_db
def test_only_server_routed_presets_can_be_tested(monkeypatch):
    client, _user, csrf = _authenticated_client('model-route-owner')
    connection_id = _create_connection(client, csrf)
    manual = _add_model(client, csrf, connection_id, model_id='vendor/unlisted-model').json()

    def forbidden_provider_request(**_kwargs):
        raise AssertionError('an unknown manual model must not reach the gateway')

    monkeypatch.setattr('api.ai_model_test_views.send_model_probe', forbidden_provider_request)
    rejected = client.post(
        reverse('ai-model-test', kwargs={'model_id': manual['id']}),
        {'probe_kind': 'text'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )

    assert rejected.status_code == 409
    assert rejected.json() == {'error_code': 'model_test_route_unavailable'}
    assert rejected['Cache-Control'] == 'no-store'
    assert AICallAttempt.objects.count() == 0


@pytest.mark.django_db
def test_probe_api_rejects_user_supplied_article_content(monkeypatch):
    client, _user, csrf = _authenticated_client('model-probe-content-owner')
    connection_id = _create_connection(client, csrf)
    created = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'catalog_model_id': 'deepseek-flash'},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    ).json()

    def forbidden_provider_request(**_kwargs):
        raise AssertionError('the explicit capability probe must not accept article content')

    monkeypatch.setattr('api.ai_model_test_views.send_model_probe', forbidden_provider_request)
    article = 'synthetic unpublished article content ' * 1000
    rejected = client.post(
        reverse('ai-model-test', kwargs={'model_id': created['id']}),
        {
            'probe_kind': 'text',
            'messages': [{'role': 'user', 'content': article}],
        },
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )

    assert rejected.status_code == 400
    assert article not in rejected.content.decode('utf-8')
    assert AICallAttempt.objects.count() == 0


@pytest.mark.django_db
def test_explicit_text_and_tools_probes_record_secret_free_attempts(monkeypatch):
    client, user, csrf = _authenticated_client('model-test-owner')
    connection_id = _create_connection(client, csrf)
    created = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'catalog_model_id': 'deepseek-flash'},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    ).json()
    received = []

    def fake_probe(**kwargs):
        received.append(kwargs)
        return ProbeOutcome(
            'succeeded', provider_request_id=f'proxy-request-{len(received)}',
            input_tokens=7, output_tokens=2,
        )

    monkeypatch.setattr('api.ai_model_test_views.send_model_probe', fake_probe)
    text_result = client.post(
        reverse('ai-model-test', kwargs={'model_id': created['id']}),
        {'probe_kind': 'text'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    tools_result = client.post(
        reverse('ai-model-test', kwargs={'model_id': created['id']}),
        {'probe_kind': 'tools'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )

    assert text_result.status_code == tools_result.status_code == 200
    assert text_result['Cache-Control'] == 'no-store'
    assert text_result.json()['capability'] == 'supported'
    assert tools_result.json()['capability'] == 'supported'
    assert SYNTHETIC_PROVIDER_KEY not in text_result.content.decode()
    assert len(received) == 2
    assert received == [
        {
            'gateway_url': 'http://127.0.0.1:4000',
            'project_key': 'sk-' + ('a' * 32),
            'provider_key': SYNTHETIC_PROVIDER_KEY,
            'model_alias': 'news.deepseek-flash',
            'probe_kind': 'text',
        },
        {
            'gateway_url': 'http://127.0.0.1:4000',
            'project_key': 'sk-' + ('a' * 32),
            'provider_key': SYNTHETIC_PROVIDER_KEY,
            'model_alias': 'news.deepseek-flash',
            'probe_kind': 'tools',
        },
    ]
    attempts = list(AICallAttempt.objects.filter(user=user).order_by('created_at', 'id'))
    assert len(attempts) == 2
    assert [(row.purpose, row.probe_kind, row.status) for row in attempts] == [
        ('model_test', 'text', 'succeeded'), ('model_test', 'tools', 'succeeded'),
    ]
    assert all(len(row.snapshot_digest) == 64 for row in attempts)
    assert all(row.input_tokens == 7 and row.output_tokens == 2 for row in attempts)
    assert SYNTHETIC_PROVIDER_KEY not in json.dumps([
        {field.name: getattr(row, field.name) for field in row._meta.fields if field.name != 'id'}
        for row in attempts
    ], default=str)
    refreshed = client.get(reverse('ai-model-list')).json()['models'][0]
    assert refreshed['capabilities']['text'] == 'supported'
    assert refreshed['capabilities']['tools'] == 'supported'


@pytest.mark.django_db
def test_probe_failure_is_safe_and_unknown_result_is_not_retried(monkeypatch):
    client, user, csrf = _authenticated_client('model-unknown-result-owner')
    connection_id = _create_connection(client, csrf)
    created = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'catalog_model_id': 'deepseek-flash'},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    ).json()
    calls = []

    def ambiguous_result(**_kwargs):
        calls.append(True)
        return ProbeOutcome('unknown', 'result_unknown')

    monkeypatch.setattr('api.ai_model_test_views.send_model_probe', ambiguous_result)
    result = client.post(
        reverse('ai-model-test', kwargs={'model_id': created['id']}),
        {'probe_kind': 'text'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )

    assert result.status_code == 200
    assert result.json()['status'] == 'unknown'
    assert result.json()['safe_error_code'] == 'result_unknown'
    assert 'response_body' not in result.json()
    assert calls == [True]
    attempt = AICallAttempt.objects.get(user=user)
    assert attempt.status == 'unknown'
    assert attempt.safe_error_code == 'result_unknown'


@pytest.mark.django_db
def test_stale_probe_result_cannot_overwrite_a_new_connection_epoch(monkeypatch):
    client, _user, csrf = _authenticated_client('model-stale-probe-owner')
    connection_id = _create_connection(client, csrf)
    created = client.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'catalog_model_id': 'deepseek-flash'},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    ).json()
    model = UserAIModelConfig.objects.get(pk=created['id'])
    model.verification_status = 'verified'
    model.verified_credential_epoch = model.connection.credential_epoch
    model.verified_config_revision = model.config_revision
    model.verified_endpoint_profile_version = model.connection.endpoint_profile_version
    model.capability_snapshot = {'text': 'supported', 'tools': 'unknown'}
    model.save()

    def rotate_while_probe_is_in_flight(**_kwargs):
        UserAIConnection.objects.filter(pk=connection_id).update(credential_epoch=2)
        return ProbeOutcome('succeeded', input_tokens=7, output_tokens=2)

    monkeypatch.setattr('api.ai_model_test_views.send_model_probe', rotate_while_probe_is_in_flight)
    result = client.post(
        reverse('ai-model-test', kwargs={'model_id': created['id']}),
        {'probe_kind': 'tools'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    refreshed = client.get(reverse('ai-model-list')).json()['models'][0]

    assert result.status_code == 200
    assert result.json()['status'] == 'stale'
    assert result.json()['stale'] is True
    assert refreshed['verification_status'] == 'stale'
    assert refreshed['capabilities']['text'] == 'supported'
    assert refreshed['capabilities']['tools'] == 'unknown'
    assert AICallAttempt.objects.get(model_config__isnull=False).status == 'succeeded'


@pytest.mark.django_db
def test_test_action_requires_owner_and_gateway_configuration(monkeypatch):
    owner, _owner_user, owner_csrf = _authenticated_client('model-test-route-owner')
    connection_id = _create_connection(owner, owner_csrf)
    created = owner.post(
        reverse('ai-model-list'),
        {'connection_id': connection_id, 'catalog_model_id': 'deepseek-flash'},
        format='json', HTTP_X_CSRFTOKEN=owner_csrf,
    ).json()
    other, _other_user, other_csrf = _authenticated_client('model-test-route-other')
    model_test_url = reverse('ai-model-test', kwargs={'model_id': created['id']})
    assert other.post(
        model_test_url, {'probe_kind': 'text'}, format='json', HTTP_X_CSRFTOKEN=other_csrf,
    ).status_code == 404

    monkeypatch.setattr('api.ai_model_test_views.settings.AI_BYOK_GATEWAY_URL', '')
    forbidden = owner.post(
        model_test_url, {'probe_kind': 'text'}, format='json', HTTP_X_CSRFTOKEN=owner_csrf,
    )
    assert forbidden.status_code == 503
    assert forbidden.json() == {'error_code': 'model_test_gateway_unavailable'}
    assert AICallAttempt.objects.count() == 0
