from __future__ import annotations

import base64
import copy
import json
import socket
import uuid

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from api import ai_connection_views
from api.models import UserAIConnection
from api.services.ai_credentials import (
    CredentialEncryptionUnavailable,
    CredentialUnavailable,
    decrypt_credential,
    require_active_connection,
)


ENCRYPTION_KEY = base64.urlsafe_b64encode(b't01-synthetic-app-encryption-key').decode('ascii').rstrip('=')
SYNTHETIC_PROVIDER_KEY = 'sk-t01-synthetic-provider-key-never-real'


@pytest.fixture(autouse=True)
def enable_test_encryption(settings):
    settings.AI_BYOK_ENABLED = True
    settings.AI_CONNECTION_ENCRYPTION_KEY = ENCRYPTION_KEY
    settings.AI_CONNECTION_ENCRYPTION_KEY_ID = 'test-key-v1'
    settings.PUBLIC_SITE_MODE = 'full'


def _authenticated_client(username):
    user = User.objects.create_user(username=username, password='synthetic-password-123!')
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    csrf = client.get(reverse('auth-csrf'))
    assert csrf.status_code == 200
    return client, user, csrf.json()['csrfToken']


def _create_connection(client, csrf, *, api_key=SYNTHETIC_PROVIDER_KEY, **overrides):
    payload = {
        'provider_id': 'deepseek',
        'endpoint_profile': 'deepseek_default',
        'display_name': 'DeepSeek 本人账号',
        'api_key': api_key,
        **overrides,
    }
    return client.post(
        reverse('ai-connection-list'), payload, format='json', HTTP_X_CSRFTOKEN=csrf,
    )


def test_provider_catalog_is_a_fixed_allowlist_and_has_no_connection_side_effects(db, monkeypatch):
    client, _user, _csrf = _authenticated_client('catalog-user')

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError('BYOK settings must not contact a provider')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    response = client.get(reverse('ai-provider-catalog'))

    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    profiles = response.json()['providers']
    deepseek = next(item for item in profiles if item['provider_id'] == 'deepseek')
    assert deepseek == {
        'provider_id': 'deepseek',
        'provider_name': 'DeepSeek',
        'profile_id': 'deepseek_default',
        'region_name': '通用 API',
        'base_url': 'https://api.deepseek.com',
        'version': 1,
    }
    assert UserAIConnection.objects.count() == 0


def test_owner_crud_persists_only_aead_ciphertext_and_never_returns_the_key(db, monkeypatch):
    client, user, csrf = _authenticated_client('crud-owner')

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError('saving or reading a key must not contact a provider')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    created = _create_connection(client, csrf)

    assert created.status_code == 201
    assert created['Cache-Control'] == 'no-store'
    assert created.json()['key_saved'] is True
    assert created.json()['masked_key'] == '••••••••'
    assert created.json()['verification_status'] == 'not_tested'
    assert SYNTHETIC_PROVIDER_KEY not in json.dumps(created.json(), ensure_ascii=False)
    assert 'credential_ciphertext' not in created.json()

    connection = UserAIConnection.objects.get(user=user)
    assert SYNTHETIC_PROVIDER_KEY not in connection.credential_ciphertext
    assert connection.credential_ciphertext.startswith('v1.')
    assert decrypt_credential(connection) == SYNTHETIC_PROVIDER_KEY
    assert connection.credential_epoch == 1
    assert connection.credential_version == 1

    listed = client.get(reverse('ai-connection-list'))
    assert listed.status_code == 200
    assert SYNTHETIC_PROVIDER_KEY not in json.dumps(listed.json(), ensure_ascii=False)
    assert listed.json()['connections'][0]['id'] == str(connection.pk)

    changed_name = client.patch(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        {'display_name': '我的 DeepSeek'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert changed_name.status_code == 200
    connection.refresh_from_db()
    assert connection.display_name == '我的 DeepSeek'
    assert connection.credential_epoch == 1

    previous_ciphertext = connection.credential_ciphertext
    previous_version = connection.credential_version
    replaced = client.put(
        reverse('ai-connection-key', kwargs={'connection_id': connection.pk}),
        {'api_key': 'sk-t01-synthetic-replacement-key-never-real'},
        format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert replaced.status_code == 200
    assert replaced.json()['verification_status'] == 'not_tested'
    connection.refresh_from_db()
    assert connection.credential_epoch == 2
    assert connection.credential_version == 2
    assert decrypt_credential(connection) == 'sk-t01-synthetic-replacement-key-never-real'
    old_ciphertext_with_new_version = copy.copy(connection)
    old_ciphertext_with_new_version.credential_ciphertext = previous_ciphertext
    with pytest.raises(CredentialUnavailable):
        decrypt_credential(old_ciphertext_with_new_version)
    new_ciphertext_with_old_version = copy.copy(connection)
    new_ciphertext_with_old_version.credential_version = previous_version
    with pytest.raises(CredentialUnavailable):
        decrypt_credential(new_ciphertext_with_old_version)

    replaced_epoch = connection.credential_epoch
    disabled = client.patch(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        {'is_enabled': False}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert disabled.status_code == 200
    assert disabled.json()['is_enabled'] is False
    connection.refresh_from_db()
    assert connection.credential_epoch == 3
    assert connection.credential_version == 2

    reenabled = client.patch(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        {'is_enabled': True}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert reenabled.status_code == 200
    connection.refresh_from_db()
    assert connection.credential_epoch == 4
    assert connection.credential_version == 2
    assert decrypt_credential(connection) == 'sk-t01-synthetic-replacement-key-never-real'
    with pytest.raises(CredentialUnavailable):
        require_active_connection(
            user_id=user.pk, connection_id=connection.pk, expected_epoch=replaced_epoch,
        )
    assert require_active_connection(
        user_id=user.pk, connection_id=connection.pk, expected_epoch=connection.credential_epoch,
    ).pk == connection.pk

    deleted = client.delete(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert deleted.status_code == 200
    assert deleted.json() == {'deleted': True}
    connection.refresh_from_db()
    assert connection.is_deleted is True
    assert connection.is_enabled is False
    assert connection.credential_epoch == 5
    assert connection.credential_version == 2
    assert connection.credential_ciphertext == ''
    assert connection.encryption_key_id == ''
    assert client.get(reverse('ai-connection-list')).json()['connections'] == []
    cannot_reenable = client.patch(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        {'is_enabled': True}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert cannot_reenable.status_code == 404
    missing_patch_invalid = client.patch(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        {'unknown_field': True}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert missing_patch_invalid.status_code == 404
    missing_key_invalid = client.put(
        reverse('ai-connection-key', kwargs={'connection_id': connection.pk}),
        {'api_key': ''}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert missing_key_invalid.status_code == 404


def test_key_aad_binds_owner_connection_endpoint_profile_and_credential_version(db):
    client, user, csrf = _authenticated_client('aad-owner')
    assert _create_connection(client, csrf).status_code == 201
    saved = UserAIConnection.objects.get(user=user)
    assert decrypt_credential(saved) == SYNTHETIC_PROVIDER_KEY

    for attribute, value in (
        ('user_id', user.pk + 100),
        ('id', uuid.uuid4()),
        ('provider_id', 'openai'),
        ('endpoint_profile', 'qwen_beijing'),
        ('endpoint_profile_version', 2),
        ('credential_version', 2),
    ):
        changed = copy.copy(saved)
        setattr(changed, attribute, value)
        with pytest.raises(CredentialUnavailable):
            decrypt_credential(changed)


def test_b_anonymous_and_cross_site_requests_cannot_read_or_change_a_connection(db):
    owner_client, owner, owner_csrf = _authenticated_client('owner-a')
    created = _create_connection(owner_client, owner_csrf)
    connection_id = created.json()['id']
    detail_url = reverse('ai-connection-detail', kwargs={'connection_id': connection_id})
    key_url = reverse('ai-connection-key', kwargs={'connection_id': connection_id})

    other_client, _other, other_csrf = _authenticated_client('owner-b')
    assert other_client.get(reverse('ai-connection-list')).json()['connections'] == []
    assert other_client.patch(
        detail_url, {'is_enabled': False}, format='json', HTTP_X_CSRFTOKEN=other_csrf,
    ).status_code == 404
    assert other_client.put(
        key_url, {'api_key': 'sk-t01-other-synthetic-key'},
        format='json', HTTP_X_CSRFTOKEN=other_csrf,
    ).status_code == 404
    assert other_client.delete(detail_url, HTTP_X_CSRFTOKEN=other_csrf).status_code == 404

    anonymous = APIClient(enforce_csrf_checks=True)
    assert anonymous.get(reverse('ai-connection-list')).status_code == 403
    blocked_without_csrf = anonymous.post(
        reverse('ai-connection-list'),
        {'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default', 'api_key': 'sk-anon-synthetic'},
        format='json',
    )
    assert blocked_without_csrf.status_code == 403

    cross_site = owner_client.patch(
        detail_url, {'is_enabled': False}, format='json', HTTP_X_CSRFTOKEN=owner_csrf,
        HTTP_ORIGIN='https://attacker.example.test',
    )
    assert cross_site.status_code == 403
    saved = UserAIConnection.objects.get(pk=connection_id)
    assert saved.user_id == owner.pk
    assert saved.is_enabled is True


def test_stale_epoch_disabled_flag_read_only_and_missing_secret_fail_closed(db):
    client, user, csrf = _authenticated_client('fence-owner')

    with override_settings(AI_BYOK_ENABLED=False):
        disabled = _create_connection(client, csrf)
        assert disabled.status_code == 403
        assert disabled.json()['error_code'] == 'byok_disabled'
        assert UserAIConnection.objects.count() == 0

    with override_settings(PUBLIC_SITE_MODE='read_only', AI_BYOK_ENABLED=True):
        read_only = _create_connection(client, csrf)
        assert read_only.status_code == 403
        assert read_only.json()['error_code'] == 'public_read_only'
        assert UserAIConnection.objects.count() == 0

    with override_settings(AI_CONNECTION_ENCRYPTION_KEY=''):
        no_secret = _create_connection(client, csrf)
        assert no_secret.status_code == 503
        assert no_secret.json()['error_code'] == 'credential_storage_unavailable'
        assert SYNTHETIC_PROVIDER_KEY not in json.dumps(no_secret.json())
        assert UserAIConnection.objects.count() == 0

    assert _create_connection(client, csrf).status_code == 201
    connection = UserAIConnection.objects.get(user=user)
    assert require_active_connection(
        user_id=user.pk, connection_id=connection.pk, expected_epoch=connection.credential_epoch,
    ).pk == connection.pk

    old_epoch = connection.credential_epoch
    old_ciphertext = connection.credential_ciphertext
    old_version = connection.credential_version
    with override_settings(AI_CONNECTION_ENCRYPTION_KEY=''):
        no_secret_replace = client.put(
            reverse('ai-connection-key', kwargs={'connection_id': connection.pk}),
            {'api_key': 'sk-t01-unavailable-replacement-key'}, format='json', HTTP_X_CSRFTOKEN=csrf,
        )
        assert no_secret_replace.status_code == 503
        assert no_secret_replace.json()['error_code'] == 'credential_storage_unavailable'
    connection.refresh_from_db()
    assert connection.credential_epoch == old_epoch
    assert connection.credential_version == old_version
    assert connection.credential_ciphertext == old_ciphertext

    replaced = client.put(
        reverse('ai-connection-key', kwargs={'connection_id': connection.pk}),
        {'api_key': 'sk-t01-next-synthetic-key'}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert replaced.status_code == 200
    connection.refresh_from_db()
    with pytest.raises(CredentialUnavailable):
        require_active_connection(
            user_id=user.pk, connection_id=connection.pk, expected_epoch=old_epoch,
        )
    with pytest.raises(CredentialUnavailable):
        require_active_connection(
            user_id=user.pk + 1, connection_id=connection.pk, expected_epoch=connection.credential_epoch,
        )
    assert require_active_connection(
        user_id=user.pk, connection_id=connection.pk, expected_epoch=connection.credential_epoch,
    ).pk == connection.pk

    disabled = client.patch(
        reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
        {'is_enabled': False}, format='json', HTTP_X_CSRFTOKEN=csrf,
    )
    assert disabled.status_code == 200
    connection.refresh_from_db()
    with pytest.raises(CredentialUnavailable):
        require_active_connection(
            user_id=user.pk, connection_id=connection.pk, expected_epoch=connection.credential_epoch,
        )


def test_invalid_endpoint_or_user_supplied_base_url_is_rejected(db):
    client, _user, csrf = _authenticated_client('endpoint-owner')
    response = _create_connection(
        client,
        csrf,
        provider_id='deepseek',
        endpoint_profile='qwen_beijing',
        base_url='https://attacker.example.test',
    )
    assert response.status_code == 400
    assert UserAIConnection.objects.count() == 0


def test_decryption_fails_closed_when_application_secret_is_missing(db):
    client, user, csrf = _authenticated_client('decrypt-owner')
    assert _create_connection(client, csrf).status_code == 201
    connection = UserAIConnection.objects.get(user=user)
    with override_settings(AI_CONNECTION_ENCRYPTION_KEY=''):
        with pytest.raises(CredentialEncryptionUnavailable):
            decrypt_credential(connection)

        disabled = client.patch(
            reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
            {'is_enabled': False}, format='json', HTTP_X_CSRFTOKEN=csrf,
        )
        assert disabled.status_code == 200
        connection.refresh_from_db()
        disabled_epoch = connection.credential_epoch
        disabled_version = connection.credential_version
        ciphertext = connection.credential_ciphertext

        refused_reenable = client.patch(
            reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
            {'is_enabled': True}, format='json', HTTP_X_CSRFTOKEN=csrf,
        )
        assert refused_reenable.status_code == 503
        assert refused_reenable.json()['error_code'] == 'credential_storage_unavailable'
        connection.refresh_from_db()
        assert connection.is_enabled is False
        assert connection.credential_epoch == disabled_epoch
        assert connection.credential_version == disabled_version
        assert connection.credential_ciphertext == ciphertext

        deleted = client.delete(
            reverse('ai-connection-detail', kwargs={'connection_id': connection.pk}),
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert deleted.status_code == 200
        connection.refresh_from_db()
        assert connection.is_deleted is True
        assert connection.credential_ciphertext == ''


@pytest.mark.parametrize('mutation', ['patch', 'replace_key'])
def test_mutation_returns_404_when_delete_wins_before_owner_lock(db, monkeypatch, mutation):
    client, user, csrf = _authenticated_client(f'race-owner-{mutation}')
    created = _create_connection(client, csrf)
    connection_id = created.json()['id']
    real_lock = ai_connection_views._lock_owned_connection

    def delete_before_lock(owner, target_id):
        UserAIConnection.objects.filter(
            pk=target_id, user=owner, is_deleted=False,
        ).update(is_enabled=False, is_deleted=True, credential_epoch=2)
        return real_lock(owner, target_id)

    monkeypatch.setattr(ai_connection_views, '_lock_owned_connection', delete_before_lock)
    if mutation == 'patch':
        response = client.patch(
            reverse('ai-connection-detail', kwargs={'connection_id': connection_id}),
            {'is_enabled': False}, format='json', HTTP_X_CSRFTOKEN=csrf,
        )
    else:
        response = client.put(
            reverse('ai-connection-key', kwargs={'connection_id': connection_id}),
            {'api_key': 'sk-t01-race-synthetic-replacement'},
            format='json', HTTP_X_CSRFTOKEN=csrf,
        )

    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
    connection = UserAIConnection.objects.get(pk=connection_id)
    assert connection.user_id == user.pk
    assert connection.is_deleted is True
    assert connection.is_enabled is False
    assert decrypt_credential(connection) == SYNTHETIC_PROVIDER_KEY
