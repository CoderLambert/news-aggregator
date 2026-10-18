"""T01 owner/endpoint-bound AEAD storage and explicit revocation fences.

Adapted from the reviewed historical T01 design, not its migrations. Existing
UserProviderCredential ciphertext and routing are intentionally not modified.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F

from api.ai_connection_models import UserAIConnection
from api.services.ai_registry import get_profile
from api.services.ai_crypto import key_material, CredentialKeyUnavailable


class CredentialEncryptionUnavailable(RuntimeError):
    pass


class CredentialUnavailable(RuntimeError):
    pass


def _key_material():
    # Reuse the installation's existing stable key and HKDF implementation.
    # The v2 AAD domain separates connection ciphertext from the legacy format.
    try:
        return key_material()
    except (CredentialKeyUnavailable, TypeError, ValueError):
        raise CredentialEncryptionUnavailable('credential_storage_unavailable') from None


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def _aad(connection):
    return _canonical({'purpose': 'newshub-ai-connection-v2', 'owner': connection.user_id,
        'id': str(connection.pk), 'provider': connection.provider_id,
        'endpoint': connection.endpoint_profile, 'endpoint_version': connection.endpoint_profile_version,
        'credential_version': connection.credential_version})


def encrypt_credential(connection, api_key):
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key_material()).encrypt(nonce, api_key.encode('utf-8'), _aad(connection))
    return 'v2.' + base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii'), 'provider-hkdf-v1'


def decrypt_credential(connection):
    if not connection.credential_ciphertext.startswith('v2.') or connection.encryption_key_id != 'provider-hkdf-v1':
        raise CredentialUnavailable('credential_unavailable')
    key = _key_material()
    try:
        packed = base64.b64decode(connection.credential_ciphertext[3:], altchars=b'-_', validate=True)
        if len(packed) < 28:
            raise ValueError()
        return AESGCM(key).decrypt(packed[:12], packed[12:], _aad(connection)).decode('utf-8')
    except (InvalidTag, ValueError, UnicodeDecodeError, binascii.Error):
        raise CredentialUnavailable('credential_unavailable') from None


def creation_digest(user_id, values):
    # Never persist a plain hash of a possibly low-entropy secret.
    payload = {key: str(values.get(key, '')) for key in ('provider_id', 'endpoint_profile', 'display_name', 'api_key')}
    payload.update(owner=str(user_id), purpose='ai-connection-create-v1')
    return hmac.new(_key_material(), _canonical(payload), hashlib.sha256).hexdigest()


def lock_owner(user_id):
    """Acquire a database write lock, including SQLite where SELECT FOR UPDATE is inert.

    Call only inside a short atomic block; never perform network I/O while held.
    """
    changed = get_user_model().objects.filter(pk=user_id, is_active=True).update(last_login=F('last_login'))
    if changed != 1:
        raise CredentialUnavailable('account_unavailable')


def require_active_connection(*, user_id, connection_id, expected_epoch):
    if (not getattr(settings, 'AI_BYOK_ENABLED', False) or settings.PUBLIC_SITE_MODE != 'full'
            or type(expected_epoch) is not int or expected_epoch < 1):
        raise CredentialUnavailable('credential_unavailable')
    connection = UserAIConnection.objects.filter(pk=connection_id, user_id=user_id,
        user__is_active=True, is_enabled=True, is_deleted=False).first()
    if connection is None or connection.credential_epoch != expected_epoch:
        raise CredentialUnavailable('credential_unavailable')
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if profile is None or profile['version'] != connection.endpoint_profile_version:
        raise CredentialUnavailable('endpoint_changed')
    return connection


@dataclass(frozen=True)
class ConnectionSnapshot:
    """Secret-free, immutable per-connection authorization captured at enqueue."""
    user_id: int
    connection_id: str
    credential_epoch: int
    credential_version: int
    provider_id: str
    endpoint_profile: str
    endpoint_profile_version: int


def snapshot_connection(connection):
    """Construct a snapshot; worker enqueue must additionally lock and recheck DB."""
    return ConnectionSnapshot(
        user_id=connection.user_id, connection_id=str(connection.pk),
        credential_epoch=connection.credential_epoch,
        credential_version=connection.credential_version,
        provider_id=connection.provider_id,
        endpoint_profile=connection.endpoint_profile,
        endpoint_profile_version=connection.endpoint_profile_version,
    )


def require_active_snapshot(snapshot):
    """Fail closed on obsolete, malformed, cross-owner or altered worker identity."""
    if type(snapshot) is not ConnectionSnapshot:
        raise CredentialUnavailable('execution_snapshot_invalid')
    if (type(snapshot.user_id) is not int or snapshot.user_id < 1 or
            type(snapshot.connection_id) is not str or
            type(snapshot.credential_epoch) is not int or snapshot.credential_epoch < 1 or
            type(snapshot.credential_version) is not int or snapshot.credential_version < 1 or
            type(snapshot.provider_id) is not str or not snapshot.provider_id or
            type(snapshot.endpoint_profile) is not str or not snapshot.endpoint_profile or
            type(snapshot.endpoint_profile_version) is not int or snapshot.endpoint_profile_version < 1):
        raise CredentialUnavailable('execution_snapshot_invalid')
    try:
        if str(uuid.UUID(snapshot.connection_id)) != snapshot.connection_id:
            raise CredentialUnavailable('execution_snapshot_invalid')
        connection = require_active_connection(
            user_id=snapshot.user_id,
            connection_id=snapshot.connection_id,
            expected_epoch=snapshot.credential_epoch,
        )
    except (ValueError, TypeError, ValidationError):
        raise CredentialUnavailable('execution_snapshot_invalid') from None
    if (connection.credential_version != snapshot.credential_version or
            connection.provider_id != snapshot.provider_id or
            connection.endpoint_profile != snapshot.endpoint_profile or
            connection.endpoint_profile_version != snapshot.endpoint_profile_version):
        raise CredentialUnavailable('execution_snapshot_stale')
    return connection


def read_execution_credential(snapshot):
    """Serialize request admission against revocation, without network in the lock.

    The caller must invoke upstream immediately after admission. Admission
    predating revocation is already in flight; only a final fenced DB commit
    can prevent its late result from being accepted.
    """
    if type(snapshot) is not ConnectionSnapshot or type(snapshot.user_id) is not int:
        raise CredentialUnavailable('execution_snapshot_invalid')
    with transaction.atomic():
        lock_owner(snapshot.user_id)
        return decrypt_credential(require_active_snapshot(snapshot))


@contextmanager
def locked_active_connection(snapshot):
    """Fence a result-only transaction against concurrent credential revocation.

    Never perform upstream I/O or lengthy computation inside this context.
    """
    if type(snapshot) is not ConnectionSnapshot or type(snapshot.user_id) is not int:
        raise CredentialUnavailable('execution_snapshot_invalid')
    with transaction.atomic():
        lock_owner(snapshot.user_id)
        yield require_active_snapshot(snapshot)
