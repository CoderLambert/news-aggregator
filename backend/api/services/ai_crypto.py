"""Stable key derivation for new encrypted AI connections.

The salt is intentionally unchanged: historical connection ciphertext already
uses this HKDF material. Migration of v1 ciphertext is handled once by 0061,
not by the runtime service.
"""
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


class CredentialKeyUnavailable(RuntimeError):
    pass


def key_material() -> bytes:
    material = getattr(settings, 'PROVIDER_CREDENTIAL_ENCRYPTION_KEY', '')
    if not isinstance(material, str) or not material:
        raise CredentialKeyUnavailable('credential_storage_unavailable')
    return HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=b'newshub-user-provider-credential-v1',
        info=b'provider-api-key-encryption',
    ).derive(material.encode('utf-8'))
