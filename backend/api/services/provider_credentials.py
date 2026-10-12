"""Encrypted, owner-scoped API credentials for allow-listed LLM providers."""

import base64
import ipaddress
import re
import secrets
from types import SimpleNamespace
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from api.models import UserProviderCredential


class ProviderCredentialError(Exception):
    """Safe credential error that may be returned to the credential owner."""


PROVIDER_SPECS = {
    'openai': {
        'label': 'OpenAI',
        'route_prefix': 'openai',
        'default_model': 'gpt-5-mini',
    },
    'anthropic': {
        'label': 'Anthropic Claude',
        'route_prefix': 'anthropic',
        'default_model': 'claude-sonnet-4-6',
    },
    'deepseek': {
        'label': 'DeepSeek',
        'route_prefix': 'deepseek',
        'default_model': 'deepseek-chat',
    },
    'gemini': {
        'label': 'Google Gemini',
        'route_prefix': 'gemini',
        'default_model': 'gemini-2.5-flash',
    },
    'qwen': {
        'label': 'Qwen',
        'route_prefix': 'dashscope',
        'default_model': 'qwen-plus',
    },
    'glm': {
        'label': 'GLM / Z.AI',
        'route_prefix': 'zai',
        'default_model': 'glm-4.7',
    },
    'kimi': {
        'label': 'Kimi / Moonshot',
        'route_prefix': 'moonshot',
        'default_model': 'kimi-k2.5',
    },
    'mistral': {
        'label': 'Mistral AI',
        'route_prefix': 'mistral',
        'default_model': 'mistral-small-latest',
    },
    'groq': {
        'label': 'Groq',
        'route_prefix': 'groq',
        'default_model': 'llama-3.3-70b-versatile',
    },
    'xai': {
        'label': 'xAI',
        'route_prefix': 'xai',
        'default_model': 'grok-4.3',
    },
    'openrouter': {
        'label': 'OpenRouter',
        'route_prefix': 'openrouter',
        'default_model': 'openai/gpt-4o-mini',
    },
}

PROJECT_KEY_PATTERN = re.compile(r'^sk-[A-Za-z0-9_-]{16,256}$')
MODEL_ID_PATTERN = re.compile(
    r'^[A-Za-z0-9][A-Za-z0-9._:-]*(?:/[A-Za-z0-9][A-Za-z0-9._:-]*)*$',
)
GATEWAY_TIMEOUT_SECONDS = 180


class _OneShotCompletionStream:
    """Expose one verified non-streaming completion to existing SSE callers."""

    def __init__(self, response):
        choices = getattr(response, 'choices', None) or []
        if not choices:
            self._chunks = []
            return
        choice = choices[0]
        message = getattr(choice, 'message', None)
        self._chunks = [SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=getattr(message, 'content', None)),
            finish_reason=getattr(choice, 'finish_reason', None),
        )])]

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        return None


class _GatewayCompletions:
    def __init__(self, completions, provider_key: str):
        self._completions = completions
        self._provider_key = provider_key

    def create(self, **kwargs):
        if kwargs.pop('extra_body', None) not in (None, {}):
            raise ProviderCredentialError('个人模型请求包含不受支持的额外参数。')
        requested_stream = kwargs.get('stream') is True
        if requested_stream:
            # The pinned gateway intentionally blocks Chat Completions streaming
            # while its upstream EOF terminal ambiguity remains unresolved.
            kwargs['stream'] = False
        kwargs['extra_body'] = {'api_key': self._provider_key}
        response = self._completions.create(**kwargs)
        return _OneShotCompletionStream(response) if requested_stream else response


class _GatewayClient:
    """Narrow client adapter that never exposes the provider key as SDK auth."""

    _newshub_max_attempts = 1

    def __init__(self, client, http_client, provider_key: str):
        self._client = client
        self._http_client = http_client
        self.chat = SimpleNamespace(
            completions=_GatewayCompletions(client.chat.completions, provider_key),
        )

    def close(self):
        try:
            self._client.close()
        finally:
            self._http_client.close()


def _gateway_configuration() -> tuple[str, str]:
    raw_url = getattr(settings, 'AI_BYOK_GATEWAY_URL', '')
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
        address = ipaddress.ip_address(parsed.hostname or '')
    except (TypeError, ValueError):
        raise ProviderCredentialError('个人模型网关配置无效。') from None
    if (
        parsed.scheme != 'http'
        or not address.is_loopback
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {'', '/'}
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderCredentialError('个人模型网关必须使用本机回环地址。')

    project_key = getattr(settings, 'AI_BYOK_GATEWAY_PROJECT_KEY', '')
    key_file = getattr(settings, 'AI_BYOK_GATEWAY_PROJECT_KEY_FILE', '')
    if key_file:
        try:
            with open(key_file, 'r', encoding='ascii') as handle:
                project_key = handle.read(513).strip()
        except OSError:
            raise ProviderCredentialError('个人模型网关凭据不可用。') from None
    if not isinstance(project_key, str) or not PROJECT_KEY_PATTERN.fullmatch(project_key):
        raise ProviderCredentialError('个人模型网关凭据不可用。')
    return f'http://{parsed.netloc}', project_key


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


def validate_credential(provider: object, model_id: object, value: object) -> tuple[str, str, str]:
    if not isinstance(provider, str) or provider not in PROVIDER_SPECS:
        raise ProviderCredentialError('请选择受支持的模型提供方。')
    if (
        not isinstance(model_id, str)
        or len(model_id.strip()) > 128
        or not MODEL_ID_PATTERN.fullmatch(model_id.strip())
    ):
        raise ProviderCredentialError('Model ID 格式不正确，只能使用受限字符和非空路径分段。')
    normalized_model = model_id.strip()
    if not isinstance(value, str):
        raise ProviderCredentialError('API Key 必须是文本。')
    api_key = value.strip()
    if not 8 <= len(api_key) <= 512:
        raise ProviderCredentialError('API Key 长度必须在 8 到 512 个字符之间。')
    if any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in api_key):
        raise ProviderCredentialError('API Key 只能包含不带空格的 ASCII 可打印字符。')
    return provider, normalized_model, api_key


def personal_clients_for_user(user) -> list[tuple[object, str]]:
    """Return only the user's own configured client, never a global fallback."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    credential = UserProviderCredential.objects.filter(user_id=user.pk).first()
    if credential is None:
        return []
    spec = PROVIDER_SPECS.get(credential.provider)
    if spec is None:
        raise ProviderCredentialError('已保存的旧模型提供方已移除，请在设置中重新配置。')
    if not MODEL_ID_PATTERN.fullmatch(credential.model_id or ''):
        raise ProviderCredentialError('已保存的模型配置无效，请在设置中重新配置。')
    api_key = decrypt_api_key(credential)
    gateway_url, project_key = _gateway_configuration()
    import httpx
    from openai import OpenAI
    http_client = httpx.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(GATEWAY_TIMEOUT_SECONDS, connect=5),
    )
    client = OpenAI(
        api_key=project_key,
        base_url=f'{gateway_url}/v1',
        http_client=http_client,
        max_retries=0,
        timeout=GATEWAY_TIMEOUT_SECONDS,
    )
    return [(
        _GatewayClient(client, http_client, api_key),
        f'{spec["route_prefix"]}/{credential.model_id}',
    )]


def has_personal_credential(user) -> bool:
    return bool(
        user is not None
        and getattr(user, 'is_authenticated', False)
        and UserProviderCredential.objects.filter(
            user_id=user.pk,
            provider__in=PROVIDER_SPECS,
        ).exclude(model_id='').exists()
    )
