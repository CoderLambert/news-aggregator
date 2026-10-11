"""Owner-bound AEAD storage and credential epoch checks for BYOK connections."""

from __future__ import annotations

import base64
import binascii
import json
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from django.conf import settings

from api.models import UserAIConnection


_KEY_PATTERN = re.compile(r'^[A-Za-z0-9_-]{43}$')
_CIPHERTEXT_PREFIX = 'v1.'


class CredentialEncryptionUnavailable(RuntimeError):
    """The application encryption key is absent or incorrectly configured."""


class CredentialUnavailable(RuntimeError):
    """A saved connection is not valid for the requested owner and epoch."""


def _key_material() -> tuple[bytes, str]:
    encoded_key = getattr(settings, 'AI_CONNECTION_ENCRYPTION_KEY', '')
    key_id = getattr(settings, 'AI_CONNECTION_ENCRYPTION_KEY_ID', '')
    if not isinstance(encoded_key, str) or not _KEY_PATTERN.fullmatch(encoded_key):
        raise CredentialEncryptionUnavailable('credential_storage_unavailable')
    try:
        key = base64.urlsafe_b64decode(encoded_key + '=')
    except (ValueError, binascii.Error):
        raise CredentialEncryptionUnavailable('credential_storage_unavailable') from None
    if len(key) != 32 or not isinstance(key_id, str) or not key_id or len(key_id) > 64:
        raise CredentialEncryptionUnavailable('credential_storage_unavailable')
    return key, key_id


def _aad(connection: UserAIConnection) -> bytes:
    return json.dumps(
        {
            'format': 1,
            'owner_id': connection.user_id,
            'connection_id': str(connection.pk),
            'provider_id': connection.provider_id,
            'endpoint_profile': connection.endpoint_profile,
            'endpoint_profile_version': connection.endpoint_profile_version,
            'credential_version': connection.credential_version,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('ascii')


def encrypt_credential(connection: UserAIConnection, api_key: str) -> tuple[str, str]:
    key, key_id = _key_material()
    import secrets

    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, api_key.encode('utf-8'), _aad(connection))
    packed = base64.urlsafe_b64encode(nonce + encrypted).decode('ascii').rstrip('=')
    return _CIPHERTEXT_PREFIX + packed, key_id


def decrypt_credential(connection: UserAIConnection) -> str:
    key, key_id = _key_material()
    if not connection.credential_ciphertext.startswith(_CIPHERTEXT_PREFIX):
        raise CredentialUnavailable('credential_unavailable')
    if connection.encryption_key_id != key_id:
        raise CredentialEncryptionUnavailable('credential_storage_unavailable')
    packed = connection.credential_ciphertext[len(_CIPHERTEXT_PREFIX):]
    try:
        combined = base64.urlsafe_b64decode(packed + '=' * (-len(packed) % 4))
        if len(combined) < 12 + 16:
            raise ValueError('ciphertext too short')
        return AESGCM(key).decrypt(combined[:12], combined[12:], _aad(connection)).decode('utf-8')
    except (ValueError, UnicodeDecodeError, binascii.Error, InvalidTag):
        raise CredentialUnavailable('credential_unavailable') from None


def require_active_connection(*, user_id: int, connection_id, expected_epoch: int) -> UserAIConnection:
    """Fail closed for stale ownership/epoch before a caller can obtain a key."""
    connection = UserAIConnection.objects.filter(
        pk=connection_id,
        user_id=user_id,
        is_enabled=True,
        is_deleted=False,
    ).first()
    if connection is None or connection.credential_epoch != expected_epoch:
        raise CredentialUnavailable('credential_unavailable')
    return connection
