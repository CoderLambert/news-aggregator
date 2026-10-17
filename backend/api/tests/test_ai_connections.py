"""Synthetic-only regressions for original BYOK T01; never use real keys."""
import copy
import json
import socket
import uuid
from dataclasses import asdict
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.models import UserProviderCredential
from api.services.ai_credentials import (CredentialUnavailable, decrypt_credential,
    locked_active_connection, read_execution_credential, require_active_connection, snapshot_connection)
from api.services.ai_registry import provider_catalog
from api.services.provider_credentials import encrypt_api_key, personal_clients_for_user

pytestmark = pytest.mark.django_db
BASE = '/api/me/ai/connections/'
KEY = 'synthetic-t01-key-not-real-12345'


@pytest.fixture(autouse=True)
def isolated(settings):
    settings.AI_BYOK_ENABLED = True
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = False
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = 'synthetic-stable-t01-encryption-material-only'


@pytest.fixture
def users():
    return [get_user_model().objects.create_user(username=name, password='SyntheticPassword123!')
            for name in ('alice-t01', 'bob-t01')]


@pytest.fixture
def client(users):
    value = APIClient()
    value.force_authenticate(user=users[0])
    return value


def body(**values):
    return {'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
        'display_name': '个人连接', 'api_key': KEY, 'request_id': str(uuid.uuid4()), **values}


def create(client, **values):
    response = client.post(BASE, body(**values), format='json')
    assert response.status_code == 201, response.content
    return response.data


def edit(client, row, **values):
    return client.patch(BASE + row['id'] + '/', {'revision': row['revision'], **values}, format='json')


def test_create_multiple_connections_and_read_masked_status(client):
    first = create(client)
    second = create(client, display_name='另一个连接')
    rows = client.get(BASE)
    assert rows.status_code == 200 and len(rows.data['connections']) == 2
    assert first['id'] != second['id']
    assert all(row['verification_status'] == 'not_tested' for row in rows.data['connections'])
    assert KEY not in rows.content.decode()
    assert 'credential_ciphertext' not in rows.content.decode()
    assert 'no-store' in rows['Cache-Control']
    saved = UserAIConnection.objects.get(pk=first['id'])
    assert KEY not in saved.credential_ciphertext
    assert decrypt_credential(saved) == KEY


def test_catalog_retains_all_current_provider_choices(client):
    from api.services.provider_credentials import PROVIDER_SPECS
    response = client.get('/api/me/ai/providers/')
    assert response.status_code == 200
    assert {row['provider_id'] for row in response.data['providers']} == set(PROVIDER_SPECS)
    assert all('base_url' not in row for row in provider_catalog())


def test_idempotent_create_reuses_same_row_but_different_payload_conflicts(client):
    request = body()
    first = client.post(BASE, request, format='json')
    second = client.post(BASE, request, format='json')
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.data['id'] == second.data['id']
    request['api_key'] = 'another-synthetic-key'
    assert client.post(BASE, request, format='json').status_code == 409
    assert UserAIConnection.objects.count() == 1


def test_rename_changes_revision_without_reencrypting_or_revoking(client):
    row = create(client)
    before = UserAIConnection.objects.get(pk=row['id'])
    response = edit(client, row, display_name='翻译专用')
    after = UserAIConnection.objects.get(pk=row['id'])
    assert response.status_code == 200
    assert after.display_name == '翻译专用'
    assert after.revision == before.revision + 1
    assert after.credential_ciphertext == before.credential_ciphertext
    assert after.credential_epoch == before.credential_epoch


def test_disable_enable_preserve_ciphertext_version_but_revoke_old_epochs(client):
    row = create(client)
    saved = UserAIConnection.objects.get(pk=row['id'])
    snapshot = snapshot_connection(saved)
    ciphertext = saved.credential_ciphertext
    disabled = edit(client, row, is_enabled=False)
    assert disabled.status_code == 200
    with pytest.raises(CredentialUnavailable):
        read_execution_credential(snapshot)
    enabled = edit(client, disabled.data, is_enabled=True)
    assert enabled.status_code == 200
    saved.refresh_from_db()
    assert saved.credential_ciphertext == ciphertext and saved.credential_version == 1
    assert saved.credential_epoch == 3 and decrypt_credential(saved) == KEY
    with pytest.raises(CredentialUnavailable):
        read_execution_credential(snapshot)


def test_replace_bumps_both_versions_and_invalidates_old_dispatch(client):
    row = create(client)
    snapshot = snapshot_connection(UserAIConnection.objects.get(pk=row['id']))
    result = client.put(BASE + row['id'] + '/key/', {'revision': row['revision'], 'api_key': 'replacement-synthetic-key'}, format='json')
    assert result.status_code == 200
    saved = UserAIConnection.objects.get(pk=row['id'])
    assert saved.credential_epoch == 2 and saved.credential_version == 2
    assert decrypt_credential(saved) == 'replacement-synthetic-key'
    with pytest.raises(CredentialUnavailable):
        read_execution_credential(snapshot)


def test_delete_tombstones_key_and_replay_cannot_resurrect(client):
    request = body()
    row = client.post(BASE, request, format='json').data
    deleted = client.delete(BASE + row['id'] + '/', {'revision': row['revision']}, format='json')
    assert deleted.status_code == 200
    saved = UserAIConnection.objects.get(pk=row['id'])
    assert saved.is_deleted and not saved.is_enabled and not saved.credential_ciphertext
    assert client.get(BASE).data['connections'] == []
    assert client.get(BASE + row['id'] + '/').status_code == 404
    assert client.post(BASE, request, format='json').status_code == 409


@pytest.mark.parametrize('method', ['get', 'patch', 'delete', 'put'])
def test_other_user_cannot_read_or_mutate_connection(client, users, method):
    row = create(client)
    client.force_authenticate(user=users[1])
    path = BASE + row['id'] + ('/key/' if method == 'put' else '/')
    if method == 'get':
        response = client.get(path)
    else:
        response = getattr(client, method)(path, {'revision': 1, 'is_enabled': False, 'api_key': KEY}, format='json')
    assert response.status_code == 404
    assert not UserAIConnection.objects.get(pk=row['id']).is_deleted
    assert client.get(BASE).data['connections'] == []


@pytest.mark.parametrize('method', ['patch', 'delete', 'put'])
def test_stale_revision_does_not_overwrite_a_newer_change(client, method):
    row = create(client)
    assert edit(client, row, display_name='更新的名称').status_code == 200
    url = BASE + row['id'] + ('/key/' if method == 'put' else '/')
    values = {'revision': 1, **({'api_key': KEY} if method == 'put' else {'is_enabled': False} if method == 'patch' else {})}
    assert getattr(client, method)(url, values, format='json').status_code == 409
    assert UserAIConnection.objects.get(pk=row['id']).display_name == '更新的名称'


@pytest.mark.parametrize('field,value', [
    ('user_id', 99999), ('id', uuid.UUID(int=19)), ('provider_id', 'openai'),
    ('endpoint_profile', 'different'), ('endpoint_profile_version', 2), ('credential_version', 2),
])
def test_aad_rejects_identity_or_ciphertext_generation_tampering(client, field, value):
    row = create(client)
    saved = copy.copy(UserAIConnection.objects.get(pk=row['id']))
    setattr(saved, field, value)
    with pytest.raises(CredentialUnavailable):
        decrypt_credential(saved)


def test_disabled_gate_and_read_only_fail_closed(client, settings):
    settings.AI_BYOK_ENABLED = False
    assert client.get(BASE).status_code == 403
    assert client.post(BASE, body(), format='json').status_code == 403
    settings.AI_BYOK_ENABLED = True
    settings.PUBLIC_SITE_MODE = 'read_only'
    assert client.get(BASE).status_code == 403
    assert client.post(BASE, body(), format='json').status_code == 403
    assert UserAIConnection.objects.count() == 0


def test_missing_master_key_prevents_new_key_and_enable_but_allows_revocation(client, settings):
    row = create(client)
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = ''
    assert client.post(BASE, body(), format='json').status_code == 503
    assert client.put(BASE + row['id'] + '/key/', {'revision': 1, 'api_key': KEY}, format='json').status_code == 503
    disabled = edit(client, row, is_enabled=False)
    assert disabled.status_code == 200
    assert edit(client, disabled.data, is_enabled=True).status_code == 503
    assert client.delete(BASE + row['id'] + '/', {'revision': disabled.data['revision']}, format='json').status_code == 200


def test_queued_and_inflight_revocation_fences_reject_without_committing(client):
    row = create(client)
    snapshot = snapshot_connection(UserAIConnection.objects.get(pk=row['id']))
    assert KEY not in json.dumps(asdict(snapshot))
    assert read_execution_credential(snapshot) == KEY
    assert edit(client, row, is_enabled=False).status_code == 200
    committed = []
    with pytest.raises(CredentialUnavailable):
        with locked_active_connection(snapshot):
            committed.append('result')
    assert not committed
    with pytest.raises(CredentialUnavailable):
        read_execution_credential(snapshot)


def test_final_commit_is_allowed_only_for_current_owner_epoch(client):
    row = create(client)
    snapshot = snapshot_connection(UserAIConnection.objects.get(pk=row['id']))
    with locked_active_connection(snapshot) as active:
        assert active.pk == uuid.UUID(row['id'])
        assert connection.in_atomic_block
    with pytest.raises(CredentialUnavailable):
        require_active_connection(user_id=snapshot.user_id, connection_id=snapshot.connection_id, expected_epoch=True)


def test_account_deactivation_revokes_dispatch_and_commit(client, users):
    row = create(client)
    snapshot = snapshot_connection(UserAIConnection.objects.get(pk=row['id']))
    get_user_model().objects.filter(pk=users[0].pk).update(is_active=False)
    with pytest.raises(CredentialUnavailable):
        read_execution_credential(snapshot)
    with pytest.raises(CredentialUnavailable):
        with locked_active_connection(snapshot):
            pytest.fail('inactive account obtained a commit fence')


def test_all_crud_is_network_free_and_never_becomes_a_legacy_default(client, users):
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('T01 may not use the network')) as network:
        row = create(client)
        assert client.get(BASE).status_code == 200
        renamed = edit(client, row, display_name='离线管理')
        assert renamed.status_code == 200
        assert client.delete(BASE + row['id'] + '/', {'revision': renamed.data['revision']}, format='json').status_code == 200
        network.assert_not_called()
    assert personal_clients_for_user(users[0]) == []


@pytest.mark.parametrize('extra', [{'api_base': 'https://malicious.example'}, {'extra_body': {'api_key': KEY}}, {'headers': {}}, {'provider_id': KEY}, {'display_name': KEY}])
def test_untrusted_fields_and_secret_like_names_are_rejected_without_reflection(client, extra):
    response = client.post(BASE, body(**extra), format='json')
    assert response.status_code == 400
    assert KEY not in response.content.decode()
    assert UserAIConnection.objects.count() == 0


def test_csrf_origin_and_anonymous_requests_are_denied(users):
    anonymous = APIClient(enforce_csrf_checks=True)
    assert anonymous.get(BASE).status_code in {401, 403}
    assert anonymous.post(BASE, body(), format='json').status_code in {401, 403}
    session = APIClient(enforce_csrf_checks=True)
    session.force_login(users[0])
    assert session.post(BASE, body(), format='json').status_code == 403
    session.get('/api/auth/csrf/')
    csrf = session.cookies['csrftoken'].value
    assert session.post(BASE, body(), format='json', HTTP_X_CSRFTOKEN=csrf, HTTP_ORIGIN='https://evil.example').status_code == 403
    assert session.post(BASE, body(), format='json', HTTP_X_CSRFTOKEN=csrf, HTTP_X_WORKSPACE_VIEWER=str(users[1].pk)).status_code == 409
    assert session.post(BASE, body(), format='json', HTTP_X_CSRFTOKEN=csrf, HTTP_X_WORKSPACE_VIEWER=str(users[0].pk)).status_code == 201


def test_connections_do_not_mutate_legacy_credentials(client, users):
    encrypted = encrypt_api_key(KEY, users[0].pk, 'deepseek')
    legacy = UserProviderCredential.objects.create(user=users[0], provider='deepseek', model_id='deepseek-chat', encrypted_api_key=encrypted)
    before = legacy.encrypted_api_key
    row = create(client)
    disabled = edit(client, row, is_enabled=False)
    assert disabled.status_code == 200
    assert client.delete(BASE + row['id'] + '/', {'revision': disabled.data['revision']}, format='json').status_code == 200
    legacy.refresh_from_db()
    assert legacy.encrypted_api_key == before and legacy.model_id == 'deepseek-chat'


def test_model_state_matches_forward_migration():
    call_command('makemigrations', 'api', check=True, dry_run=True, verbosity=0)


@pytest.mark.django_db(transaction=True)
def test_forward_schema_preserves_existing_legacy_ciphertext():
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([('api', '0059_bind_retained_legacy_translations')])
        old = executor.loader.project_state([('api', '0059_bind_retained_legacy_translations')]).apps
        owner = old.get_model('auth', 'User').objects.create(username='legacy-migration-t01')
        legacy = old.get_model('api', 'UserProviderCredential').objects.create(user_id=owner.pk,
            provider='deepseek', model_id='deepseek-chat', encrypted_api_key='unchanged-synthetic-ciphertext')
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        restored = UserProviderCredential.objects.get(pk=legacy.pk)
        assert restored.encrypted_api_key == 'unchanged-synthetic-ciphertext'
        assert restored.model_id == 'deepseek-chat' and restored.user_id == owner.pk
        assert not UserAIConnection.objects.filter(user_id=owner.pk).exists()
    finally:
        MigrationExecutor(connection).migrate(targets)


def test_connection_limit_is_per_owner_and_does_not_create_the_twenty_first(client):
    for index in range(20):
        create(client, display_name=f'连接 {index}')
    response = client.post(BASE, body(), format='json')
    assert response.status_code == 429
    assert UserAIConnection.objects.filter(is_deleted=False).count() == 20


def test_failed_key_write_rolls_back_ciphertext_and_all_versions(client):
    from django.db import OperationalError
    row = create(client)
    before = UserAIConnection.objects.values().get(pk=row['id'])
    with patch.object(UserAIConnection, 'save', side_effect=OperationalError(KEY)):
        response = client.put(BASE + row['id'] + '/key/', {'revision': 1, 'api_key': KEY}, format='json')
    assert response.status_code == 503
    assert KEY not in response.content.decode()
    assert UserAIConnection.objects.values().get(pk=row['id']) == before


@pytest.mark.parametrize('value,expected', [(None, 'False'), ('0', 'False'), ('1', 'True'), ('true', None), ('', None)])
def test_connection_gate_environment_defaults_off_and_rejects_non_boolean(value, expected, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    backend = Path(__file__).resolve().parents[2]
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(backend),
        'PYTHONDONTWRITEBYTECODE': '1', 'DJANGO_ENV': 'production', 'RUN_MAIN': 'true',
        'DJANGO_SECRET_KEY': 'synthetic-t01-config-only-strong-secret-9876543210-abcdef',
        'DJANGO_DB_PATH': str(tmp_path / 'unused.sqlite3'), 'WAITRESS_TRUSTED_PROXY': '127.0.0.1'}
    if value is not None:
        env['AI_BYOK_ENABLED'] = value
    result = subprocess.run([sys.executable, '-c',
        'from newsaggregator.settings import AI_BYOK_ENABLED; print(AI_BYOK_ENABLED)'],
        env=env, cwd=tmp_path, capture_output=True, text=True, timeout=15)
    if expected is None:
        assert result.returncode != 0 and 'AI_BYOK_ENABLED must be 0 or 1.' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
    assert not (tmp_path / 'unused.sqlite3').exists()
