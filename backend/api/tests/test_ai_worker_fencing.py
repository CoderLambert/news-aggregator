"""T01 synthetic worker lifecycle races; no real provider/Proxy/model calls."""
import json
import uuid
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.services.ai_credentials import CredentialUnavailable
from api.services.ai_worker_fencing import (
    capture_at_enqueue, check_at_claim, commit_result, dispatch_once, is_revoked,
)

pytestmark = pytest.mark.django_db
KEY = 'synthetic-worker-t01-only-not-real'
BASE = '/api/me/ai/connections/'


@pytest.fixture(autouse=True)
def synthetic_settings(settings):
    settings.AI_BYOK_ENABLED = True
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = False
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = 'synthetic-worker-master-encryption-key-2026'


@pytest.fixture
def users():
    model = get_user_model()
    return model.objects.create_user('worker-a'), model.objects.create_user('worker-b')


def make_connection(owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(BASE, {
        'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
        'display_name': 'worker', 'api_key': KEY, 'request_id': str(uuid.uuid4()),
    }, format='json')
    assert response.status_code == 201, response.content
    return client, response.data


def snapshot(owner, row):
    return capture_at_enqueue(owner=owner, connection_id=row['id'])


def disable(client, row):
    result = client.patch(BASE + row['id'] + '/',
        {'revision': row['revision'], 'is_enabled': False}, format='json')
    assert result.status_code == 200, result.content
    return result.data


def replace(client, row):
    result = client.put(BASE + row['id'] + '/key/',
        {'revision': row['revision'], 'api_key': 'replacement-synthetic-t01-worker-key'}, format='json')
    assert result.status_code == 200, result.content
    return result.data


def delete(client, row):
    result = client.delete(BASE + row['id'] + '/',
        {'revision': row['revision']}, format='json')
    assert result.status_code == 200, result.content


def test_capture_is_secret_free_versioned_and_works_across_json_queue(users):
    owner, _ = users
    _, row = make_connection(owner)
    queued = snapshot(owner, row)
    wire = json.loads(json.dumps(queued))
    assert queued == wire
    assert set(wire) == {'schema_version', 'user_id', 'connection_id',
                         'credential_epoch', 'credential_version',
                         'provider_id', 'endpoint_profile', 'endpoint_profile_version',
                         'auth_mode', 'endpoint_policy_digest'}
    assert KEY not in json.dumps(wire)
    assert 'credential_ciphertext' not in wire
    assert check_at_claim(wire, task_owner_id=owner.pk).credential_epoch == 1
    transport = Mock(return_value='synthetic-terminal')
    assert dispatch_once(wire, task_owner_id=owner.pk, send=transport) == 'synthetic-terminal'
    transport.assert_called_once_with(KEY)
    persist = Mock(return_value='saved')
    assert commit_result(wire, task_owner_id=owner.pk, persist=persist) == 'saved'
    persist.assert_called_once_with()


@pytest.mark.parametrize('revoke', [disable, replace, delete])
def test_queued_claim_send_retry_and_commit_reject_revoked_generation(users, revoke):
    owner, _ = users
    client, row = make_connection(owner)
    queued = snapshot(owner, row)
    revoke(client, row)
    transport, persist = Mock(), Mock()
    with pytest.raises(CredentialUnavailable):
        check_at_claim(queued, task_owner_id=owner.pk)
    with pytest.raises(CredentialUnavailable):
        check_at_claim(queued, task_owner_id=owner.pk)  # retry keeps original identity
    with pytest.raises(CredentialUnavailable):
        dispatch_once(queued, task_owner_id=owner.pk, send=transport)
    with pytest.raises(CredentialUnavailable):
        commit_result(queued, task_owner_id=owner.pk, persist=persist)
    assert is_revoked(queued, task_owner_id=owner.pk)
    transport.assert_not_called()
    persist.assert_not_called()


def test_disabled_then_reenabled_does_not_resurrect_previous_queue(users):
    owner, _ = users
    client, row = make_connection(owner)
    old = snapshot(owner, row)
    off = disable(client, row)
    on = client.patch(BASE + row['id'] + '/',
        {'revision': off['revision'], 'is_enabled': True}, format='json')
    assert on.status_code == 200
    assert snapshot(owner, on.data)['credential_epoch'] == old['credential_epoch'] + 2
    with pytest.raises(CredentialUnavailable):
        check_at_claim(old, task_owner_id=owner.pk)


def test_revoked_while_request_is_in_flight_never_commits_late_result(users):
    owner, _ = users
    client, row = make_connection(owner)
    queued = snapshot(owner, row)
    sent = []
    def fake_inflight(secret):
        assert secret == KEY
        sent.append('request-admitted-before-revoke')
        disable(client, row)  # deterministic revocation during synthetic send
        return 'complete-provider-reply'
    assert dispatch_once(queued, task_owner_id=owner.pk, send=fake_inflight) == 'complete-provider-reply'
    persist = Mock()
    with pytest.raises(CredentialUnavailable):
        commit_result(queued, task_owner_id=owner.pk, persist=persist)
    persist.assert_not_called()
    assert sent == ['request-admitted-before-revoke']


def test_two_worker_claims_do_not_grant_evergreen_commit_rights(users):
    owner, _ = users
    client, row = make_connection(owner)
    first, second = snapshot(owner, row), snapshot(owner, row)
    assert check_at_claim(first, task_owner_id=owner.pk)
    assert check_at_claim(second, task_owner_id=owner.pk)
    assert commit_result(first, task_owner_id=owner.pk, persist=lambda: 'first') == 'first'
    disable(client, row)
    with pytest.raises(CredentialUnavailable):
        commit_result(second, task_owner_id=owner.pk, persist=lambda: 'second')
    # A later stale retry cannot silently refresh the old task's epoch.
    with pytest.raises(CredentialUnavailable):
        check_at_claim(first, task_owner_id=owner.pk)


def test_owner_and_connection_isolation_are_enforced_at_all_phases(users):
    alice, bob = users
    _, alice_row = make_connection(alice)
    _, bob_row = make_connection(bob)
    queued = snapshot(alice, alice_row)
    with pytest.raises(CredentialUnavailable):
        capture_at_enqueue(owner=bob, connection_id=alice_row['id'])
    for operation in (
        lambda: check_at_claim(queued, task_owner_id=bob.pk),
        lambda: dispatch_once(queued, task_owner_id=bob.pk, send=Mock()),
        lambda: commit_result(queued, task_owner_id=bob.pk, persist=Mock()),
    ):
        with pytest.raises(CredentialUnavailable):
            operation()
    assert not is_revoked(queued, task_owner_id=alice.pk)
    assert snapshot(bob, bob_row)['connection_id'] != queued['connection_id']


@pytest.mark.parametrize('field,value', [
    ('schema_version', 0), ('schema_version', True),
    ('user_id', True), ('credential_epoch', True),
    ('credential_version', -1), ('connection_id', 'not-a-uuid'),
    ('provider_id', 'openai'), ('endpoint_profile', 'malicious'),
    ('endpoint_profile_version', 99),
])
def test_malformed_or_tampered_worker_identity_fails_closed(users, field, value):
    owner, _ = users
    _, row = make_connection(owner)
    queued = snapshot(owner, row)
    tampered = {**queued, field: value}
    send, persist = Mock(), Mock()
    with pytest.raises(CredentialUnavailable):
        dispatch_once(tampered, task_owner_id=owner.pk, send=send)
    with pytest.raises(CredentialUnavailable):
        commit_result(tampered, task_owner_id=owner.pk, persist=persist)
    send.assert_not_called()
    persist.assert_not_called()


def test_extra_secret_or_unversioned_old_job_is_rejected(users):
    owner, _ = users
    _, row = make_connection(owner)
    queued = snapshot(owner, row)
    for bad in ({**queued, 'api_key': KEY},
                {key: val for key, val in queued.items() if key != 'schema_version'},
                None):
        with pytest.raises(CredentialUnavailable):
            check_at_claim(bad, task_owner_id=owner.pk)


def test_invalid_ciphertext_and_missing_master_key_prevent_enqueue(users, settings):
    owner, _ = users
    _, row = make_connection(owner)
    UserAIConnection.objects.filter(pk=row['id']).update(credential_ciphertext='v2.invalid')
    with pytest.raises(CredentialUnavailable):
        snapshot(owner, row)
    UserAIConnection.objects.filter(pk=row['id']).update(credential_ciphertext='v2.invalid')
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = ''
    with pytest.raises(Exception) as failure:
        snapshot(owner, row)
    assert failure.type.__name__ in {'CredentialEncryptionUnavailable', 'CredentialUnavailable'}


def test_site_admin_key_cannot_rescue_disabled_personal_byok(users, settings):
    owner, _ = users
    _, row = make_connection(owner)
    queued = snapshot(owner, row)
    settings.AI_BYOK_ENABLED = False
    settings.PUBLIC_AI_ENABLED = True
    settings.OPENAI_API_KEY = 'synthetic-site-key-never-a-fallback'
    with patch('api.services.ai_gateway.build_gateway_client', side_effect=AssertionError('implicit site fallback')) as gateway:
        with pytest.raises(CredentialUnavailable):
            dispatch_once(queued, task_owner_id=owner.pk, send=Mock())
        gateway.assert_not_called()


def test_account_deactivation_and_result_transaction_failure(users):
    owner, _ = users
    _, row = make_connection(owner)
    queued = snapshot(owner, row)
    def broken_persist():
        get_user_model().objects.filter(pk=owner.pk).update(last_name='should-rollback')
        raise RuntimeError('synthetic DB failure')
    with pytest.raises(RuntimeError):
        commit_result(queued, task_owner_id=owner.pk, persist=broken_persist)
    owner.refresh_from_db()
    assert owner.last_name == ''
    get_user_model().objects.filter(pk=owner.pk).update(is_active=False)
    with pytest.raises(CredentialUnavailable):
        check_at_claim(queued, task_owner_id=owner.pk)
    with pytest.raises(CredentialUnavailable):
        commit_result(queued, task_owner_id=owner.pk, persist=Mock())


def test_corrupted_ciphertext_after_admission_cannot_commit_inflight_result(users):
    owner, _ = users
    _, row = make_connection(owner)
    queued = snapshot(owner, row)
    assert dispatch_once(queued, task_owner_id=owner.pk, send=lambda secret: 'sent') == 'sent'
    # Even a broken administrative write without an epoch bump fails closed.
    UserAIConnection.objects.filter(pk=row['id']).update(credential_ciphertext='v2.broken')
    persist = Mock()
    with pytest.raises(CredentialUnavailable):
        commit_result(queued, task_owner_id=owner.pk, persist=persist)
    persist.assert_not_called()


def test_revocation_after_key_read_but_before_send_stops_new_request(users):
    owner, _ = users
    client, row = make_connection(owner)
    queued = snapshot(owner, row)
    def revoke_after_decrypt(_snapshot):
        disable(client, row)
        return KEY
    transport = Mock()
    with patch('api.services.ai_worker_fencing.read_execution_credential',
               side_effect=revoke_after_decrypt):
        with pytest.raises(CredentialUnavailable):
            dispatch_once(queued, task_owner_id=owner.pk, send=transport)
    transport.assert_not_called()
