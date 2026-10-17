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
from contextlib import contextmanager
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
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
    user_id: int
    connection_id: str
    credential_epoch: int


def snapshot_connection(connection):
    return ConnectionSnapshot(connection.user_id, str(connection.pk), connection.credential_epoch)


def read_execution_credential(snapshot):
    """Recheck immediately before dispatch. A key is never stored in a snapshot."""
    connection = require_active_connection(user_id=snapshot.user_id,
        connection_id=snapshot.connection_id, expected_epoch=snapshot.credential_epoch)
    return decrypt_credential(connection)


@contextmanager
def locked_active_connection(snapshot):
    """Fence a final database-only commit against credential revocation.

    Consumers must also check before dispatch. This helper does not claim to
    cancel an upstream request already sent or revoke its billing.
    """
    with transaction.atomic():
        lock_owner(snapshot.user_id)
        connection = require_active_connection(user_id=snapshot.user_id,
            connection_id=snapshot.connection_id, expected_epoch=snapshot.credential_epoch)
        yield connection
