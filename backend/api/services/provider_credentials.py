"""Encrypted, owner-scoped API credentials for allow-listed LLM providers."""

import base64
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from api.models import UserProviderCredential


class ProviderCredentialError(Exception):
    """Safe credential error that may be returned to the credential owner."""


PROVIDER_SPECS = {
    'volcengine': {
        'label': 'Volcengine ARK',
        'prefix': 'ark-',
        'base_url': 'https://ark.cn-beijing.volces.com/api/coding/v3',
        'model': 'deepseek-v4-pro',
    },
    'dashscope': {
        'label': 'DashScope',
        'prefix': 'sk-',
        'base_url': 'https://coding.dashscope.aliyuncs.com/v1',
        'model': 'kimi-k2.5',
    },
}


def _key_material() -> bytes:
    material = getattr(settings, 'PROVIDER_CREDENTIAL_ENCRYPTION_KEY', '')
    if not material:
        raise ProviderCredentialError('服务端缺少稳定的用户凭据加密密钥。')
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'newshub-user-provider-credential-v1',
        info=b'provider-api-key-encryption',
    ).derive(material.encode('utf-8'))


def _purpose(user_id: int, provider: str) -> bytes:
    return f'provider-api-key:v1:{int(user_id)}:{provider}'.encode('utf-8')


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def encrypt_api_key(api_key: str, user_id: int, provider: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key_material()).encrypt(
        nonce, api_key.encode('utf-8'), _purpose(user_id, provider),
    )
    return _encode(nonce + ciphertext)


def decrypt_api_key(credential: UserProviderCredential) -> str:
    try:
        raw = _decode(credential.encrypted_api_key)
        plaintext = AESGCM(_key_material()).decrypt(
            raw[:12], raw[12:], _purpose(credential.user_id, credential.provider),
        )
        return plaintext.decode('utf-8')
    except ProviderCredentialError:
        raise
    except Exception as exc:
        raise ProviderCredentialError('已保存的 API Key 无法解密，请删除后重新配置。') from exc


def validate_api_key(provider: object, value: object) -> tuple[str, str]:
    if not isinstance(provider, str) or provider not in PROVIDER_SPECS:
        raise ProviderCredentialError('请选择受支持的模型提供方。')
    if not isinstance(value, str):
        raise ProviderCredentialError('API Key 必须是文本。')
    api_key = value.strip()
    if not 8 <= len(api_key) <= 512:
        raise ProviderCredentialError('API Key 长度必须在 8 到 512 个字符之间。')
    if any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in api_key):
        raise ProviderCredentialError('API Key 只能包含不带空格的 ASCII 可打印字符。')
    prefix = PROVIDER_SPECS[provider]['prefix']
    if not api_key.startswith(prefix):
        raise ProviderCredentialError(f'{PROVIDER_SPECS[provider]["label"]} API Key 格式不正确。')
    return provider, api_key


def personal_clients_for_user(user) -> list[tuple[object, str]]:
    """Return only the user's own configured client, never a global fallback."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    credential = UserProviderCredential.objects.filter(user_id=user.pk).first()
    if credential is None:
        return []
    api_key = decrypt_api_key(credential)
    spec = PROVIDER_SPECS.get(credential.provider)
    if spec is None:
        raise ProviderCredentialError('已保存的模型提供方不受支持，请重新配置。')
    from openai import OpenAI
    return [(
        OpenAI(api_key=api_key, base_url=spec['base_url']),
        spec['model'],
    )]


def has_personal_credential(user) -> bool:
    return bool(
        user is not None
        and getattr(user, 'is_authenticated', False)
        and UserProviderCredential.objects.filter(user_id=user.pk).exists()
    )
