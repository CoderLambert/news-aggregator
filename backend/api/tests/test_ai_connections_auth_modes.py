"""No-Key is explicit authorization, never a missing/corrupt paid credential."""
import json
import uuid
from dataclasses import asdict, replace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.services.ai_credentials import (
    CredentialUnavailable, creation_digest, decrypt_credential, read_execution_credential,
    require_active_snapshot, snapshot_connection,
)
from api.services.ai_worker_fencing import capture_at_enqueue, check_at_claim, commit_result, dispatch_once
from api.tests.test_ai_endpoint_profiles import profile

pytestmark = pytest.mark.django_db
BASE = '/api/me/ai/connections/'
KEY = 'synthetic-unified-auth-key-only'


@pytest.fixture
def context(settings, tmp_path):
    settings.AI_BYOK_ENABLED = True
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = False
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = 'synthetic-unified-auth-encryption-material'
    owner = get_user_model().objects.create_user('unified-auth-owner')
    other = get_user_model().objects.create_user('unified-auth-other')
    api = APIClient()
    api.force_authenticate(owner)
    path = tmp_path / 'endpoints.json'
    item = profile(allowed_user_ids=[owner.pk], auth_modes=['none', 'api_key'])
    path.write_text(json.dumps([item]))
    settings.AI_BYOK_ENDPOINT_MANIFEST = str(path)
    return api, owner, other, path, item


def request(**changes):
    return dict(provider_id='ollama', endpoint_profile='office_ollama',
                display_name='受信推理', auth_mode='none', request_id=str(uuid.uuid4())) | changes


def created(context, **changes):
    api, *_ = context
    response = api.post(BASE, request(**changes), format='json')
    assert response.status_code == 201, response.content
    return response.data, UserAIConnection.objects.get(pk=response.data['id'])


def test_none_connection_has_no_ciphertext_and_dispatches_explicit_none(context, settings):
    api, owner, *_ = context
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = ''
    public, row = created(context)
    assert public['auth_mode'] == 'none' and public['key_saved'] is False
    assert row.credential_ciphertext == row.encryption_key_id == ''
    with pytest.raises(CredentialUnavailable):
        decrypt_credential(row)
    snapshot = capture_at_enqueue(owner=owner, connection_id=row.pk)
    assert snapshot['auth_mode'] == 'none'
    assert dispatch_once(snapshot, task_owner_id=owner.pk, send=lambda material: material) is None
    assert commit_result(snapshot, task_owner_id=owner.pk, persist=lambda: 'committed') == 'committed'
    assert api.get(BASE).status_code == 200


@pytest.mark.parametrize('changes', [
    {'api_key': KEY}, {'api_key': ''}, {'auth_mode': 'api_key'},
    {'auth_mode': 'inherit'}, {'auth_mode': None},
    {'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default'},
])
def test_missing_key_or_forged_none_cannot_create_paid_identity(context, changes):
    api, *_ = context
    assert api.post(BASE, request(**changes), format='json').status_code == 400
    assert UserAIConnection.objects.count() == 0


def test_private_profile_acl_applies_to_catalog_create_and_existing_jobs(context):
    api, owner, other, path, item = context
    public, row = created(context)
    snapshot = capture_at_enqueue(owner=owner, connection_id=row.pk)
    api.force_authenticate(other)
    catalog = api.get('/api/me/ai/providers/')
    assert not any(p['profile_id'] == 'office_ollama' for p in catalog.data['providers'])
    assert api.post(BASE, request(), format='json').status_code == 400
    with pytest.raises(CredentialUnavailable):
        check_at_claim(snapshot, task_owner_id=other.pk)
    item['allowed_user_ids'] = [other.pk]
    path.write_text(json.dumps([item]))
    with pytest.raises(CredentialUnavailable):
        commit_result(snapshot, task_owner_id=owner.pk, persist=lambda: 'must-not-commit')


def test_none_disable_reenable_revokes_snapshot_and_key_replacement_is_rejected(context):
    api, owner, *_ = context
    public, row = created(context)
    old = capture_at_enqueue(owner=owner, connection_id=row.pk)
    rejected = api.put(BASE + public['id'] + '/key/',
                       {'revision': public['revision'], 'api_key': KEY}, format='json')
    assert rejected.status_code == 400
    row.refresh_from_db()
    assert row.credential_epoch == 1 and row.auth_mode == 'none'
    disabled = api.patch(BASE + public['id'] + '/',
                         {'revision': 1, 'is_enabled': False}, format='json')
    assert disabled.status_code == 200
    with pytest.raises(CredentialUnavailable):
        check_at_claim(old, task_owner_id=owner.pk)
    enabled = api.patch(BASE + public['id'] + '/',
                        {'revision': 2, 'is_enabled': True}, format='json')
    assert enabled.status_code == 200
    row.refresh_from_db()
    assert row.credential_epoch == 3 and not row.credential_ciphertext
    with pytest.raises(CredentialUnavailable):
        read_execution_credential(replace(snapshot_connection(row), credential_epoch=1))


def test_key_mode_keeps_original_aad_and_create_digest_and_cannot_be_forged_none(context):
    api, owner, *_ = context
    values = request(provider_id='deepseek', endpoint_profile='deepseek_default', api_key=KEY)
    values.pop('auth_mode')
    response = api.post(BASE, values, format='json')
    assert response.status_code == 201
    row = UserAIConnection.objects.get(pk=response.data['id'])
    assert row.auth_mode == 'api_key' and decrypt_credential(row) == KEY
    assert creation_digest(owner.pk, values) == creation_digest(owner.pk, values | {'auth_mode': 'api_key'})
    assert api.post(BASE, values, format='json').status_code == 200
    snapshot = snapshot_connection(row)
    with pytest.raises(CredentialUnavailable):
        require_active_snapshot(replace(snapshot, auth_mode='none'))
    legacy = {'schema_version': 1, **asdict(snapshot)}
    legacy.pop('auth_mode')
    legacy.pop('endpoint_policy_digest')
    assert dispatch_once(legacy, task_owner_id=owner.pk, send=lambda key: key) == KEY
    # Removing a field from a no-Key snapshot never upgrades a legacy job.
    _, local = created(context)
    forged = {'schema_version': 1, **asdict(snapshot_connection(local))}
    forged.pop('auth_mode')
    forged.pop('endpoint_policy_digest')
    with pytest.raises(CredentialUnavailable):
        check_at_claim(forged, task_owner_id=owner.pk)


def test_same_request_cannot_switch_auth_semantics(context):
    api, *_ = context
    values = request()
    first = api.post(BASE, values, format='json')
    assert first.status_code == 201
    assert api.post(BASE, values, format='json').status_code == 200
    assert api.post(BASE, values | {'auth_mode': 'api_key', 'api_key': KEY}, format='json').status_code == 409
    assert UserAIConnection.objects.count() == 1


def test_corrupt_ciphertext_cannot_become_none_or_authorize_result(context):
    _, row = created(context)
    snapshot = snapshot_connection(row)
    UserAIConnection.objects.filter(pk=row.pk).update(credential_ciphertext='v2.invalid')
    with pytest.raises(CredentialUnavailable):
        require_active_snapshot(snapshot)


@pytest.mark.parametrize('auth_mode', ['none', 'api_key'])
def test_same_version_target_change_cannot_inherit_existing_authorization(context, auth_mode):
    _, owner, _, path, item = context
    values = {'auth_mode': auth_mode}
    if auth_mode == 'api_key':
        values['api_key'] = KEY
    _, row = created(context, **values)
    old = snapshot_connection(row)
    item['api_base'] = 'http://127.0.0.1:11435/v1'
    path.write_text(json.dumps([item]))
    with pytest.raises(CredentialUnavailable):
        require_active_snapshot(old)
    # A fresh enqueue cannot rebind the old connection to the changed server.
    with pytest.raises(CredentialUnavailable):
        capture_at_enqueue(owner=owner, connection_id=row.pk)


def test_decoder_accepts_only_complete_new_or_legacy_key_snapshot(context):
    from api.services.ai_credentials import decode_connection_snapshot
    _, row = created(context)
    raw = asdict(snapshot_connection(row))
    assert decode_connection_snapshot(raw).auth_mode == 'none'
    for altered in (raw | {'api_key': KEY}, raw | {'auth_mode': False},
                    {key: value for key, value in raw.items() if key != 'endpoint_policy_digest'}):
        with pytest.raises(CredentialUnavailable):
            decode_connection_snapshot(altered)


def test_new_endpoint_policy_is_authenticated_by_ciphertext(context):
    from api.services.ai_registry import get_profile
    _, _, _, path, item = context
    _, row = created(context, auth_mode='api_key', api_key=KEY)
    item['api_base'] = 'http://127.0.0.1:11435/v1'
    path.write_text(json.dumps([item]))
    row.endpoint_policy_digest = get_profile('ollama', 'office_ollama')['policy_digest']
    # Merely changing stored routing metadata must not rebind an existing Key.
    with pytest.raises(CredentialUnavailable):
        decrypt_credential(row)


@pytest.mark.parametrize('policy_change', ['target', 'owner', 'deleted'])
def test_create_rechecks_same_administrator_policy_after_validation(context, policy_change):
    from api.services.ai_registry import get_profile
    api, _, other, path, item = context
    reads = 0

    def publish_after_read(provider, profile_id):
        nonlocal reads
        result = get_profile(provider, profile_id)
        reads += 1
        if reads == 1:
            if policy_change == 'target':
                item['api_base'] = 'http://127.0.0.1:11435/v1'
            elif policy_change == 'owner':
                item['allowed_user_ids'] = [other.pk]
            path.write_text(json.dumps([] if policy_change == 'deleted' else [item]))
        return result

    with patch('api.ai_connection_views.get_profile', side_effect=publish_after_read):
        response = api.post(BASE, request(auth_mode='api_key', api_key=KEY), format='json')
    assert response.status_code == 409
    assert UserAIConnection.objects.count() == 0


def test_unavailable_encryption_only_marks_selected_task_unavailable(context, settings):
    from api.ai_model_models import UserAIModelConfig
    from api.ai_preference_models import TASK_KINDS, UserAITaskPreference
    api, owner, *_ = context
    _, row = created(context, provider_id='deepseek', endpoint_profile='deepseek_default',
                     auth_mode='api_key', api_key=KEY)
    model = UserAIModelConfig.objects.create(connection=row, model_id='deepseek-flash', display_name='Flash')
    for kind in TASK_KINDS:
        UserAITaskPreference.objects.create(
            user=owner, task_kind=kind,
            selection_source='byok' if kind == 'default' else 'inherit',
            model_config=model if kind == 'default' else None,
        )
    settings.PROVIDER_CREDENTIAL_ENCRYPTION_KEY = ''
    response = api.get('/api/me/ai/task-preferences/')
    assert response.status_code == 200
    default = next(item for item in response.data['preferences'] if item['task_kind'] == 'default')
    assert default['selection_state'] == 'needs_reselection'


@pytest.mark.parametrize('provider,namespace', [
    ('openai', 'openai'), ('deepseek', 'deepseek'), ('qwen', 'dashscope'),
])
def test_compatible_model_create_patch_and_routing_preserve_full_id(context, provider, namespace):
    from api.services.ai_model_registry import get_trusted_route
    api, _, _, path, item = context
    item['provider_id'] = provider
    path.write_text(json.dumps([item]))
    public, row = created(context, provider_id=provider)
    model_id = namespace + '/local-model:tag'
    root = BASE + public['id'] + '/models/'
    first = api.post(root, {'model_id': model_id}, format='json')
    assert first.status_code == 201 and first.data['model_id'] == model_id
    assert get_trusted_route(row, model_id)['proxy_alias'].endswith('/' + model_id)
    changed = api.patch(root + first.data['id'] + '/',
                        {'revision': first.data['config_revision'], 'model_id': model_id + '-v2'}, format='json')
    assert changed.status_code == 200 and changed.data['model_id'] == model_id + '-v2'
