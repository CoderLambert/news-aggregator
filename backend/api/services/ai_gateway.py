"""Neutral trusted LiteLLM Proxy transport for explicit BYOK consumers.

No legacy user credential lookup, provider fallback, or implicit model selection.
The only enabled Chat streaming route is the separately guarded DeepSeek T04
alias; every other alias remains fail-closed.
"""
import ipaddress
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
from django.conf import settings
from api.services.ai_responses_protocol import (
    OPENAI_RESPONSES_MODELS, ResponsesProtocolError, completion_object,
    responses_completion, responses_payload,
)


class AIGatewayError(RuntimeError):
    pass


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
GATEWAY_TIMEOUT_SECONDS = 180
# Keep the single verified T04 stream route shared by the registry and gateway.
ARTICLE_CHAT_SUPPORTED_ALIAS = 'deepseek/deepseek-flash'


class _GatewayCompletions:
    def __init__(self, completions, provider_key: str, responses=None):
        self._completions = completions
        self._provider_key = provider_key
        self._responses = responses

    def create(self, **kwargs):
        if kwargs.pop('extra_body', None) not in (None, {}):
            raise AIGatewayError('个人模型请求包含不受支持的额外参数。')
        requested_stream = kwargs.get('stream') is True
        if requested_stream and kwargs.get('model') != ARTICLE_CHAT_SUPPORTED_ALIAS:
            raise AIGatewayError('个人模型流式路由不可用。')
        if kwargs.get('model') in OPENAI_RESPONSES_MODELS:
            if self._responses is None:
                raise AIGatewayError('个人模型原生协议不可用。')
            try:
                data = responses_payload(kwargs)
                result = self._responses.create(**data, extra_body={'api_key': self._provider_key})
                raw = result if isinstance(result, dict) else result.model_dump(mode='json', exclude_none=True)
                return completion_object(responses_completion(raw))
            except ResponsesProtocolError:
                raise AIGatewayError('个人模型返回了不完整或无法验证的响应。') from None
        kwargs['extra_body'] = {'api_key': self._provider_key}
        # OpenAI's SDK starts the HTTP request here and returns a closeable
        # iterator. Do not buffer, defer, retry, or convert an uncertain stream.
        return self._completions.create(**kwargs)


class _GatewayClient:
    """Narrow client adapter that never exposes the provider key as SDK auth."""

    _newshub_max_attempts = 1

    def __init__(self, client, http_client, provider_key: str):
        self._client = client
        self._http_client = http_client
        self.chat = SimpleNamespace(
            completions=_GatewayCompletions(client.chat.completions, provider_key,
                                           responses=getattr(client, 'responses', None)),
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
        raise AIGatewayError('个人模型网关配置无效。') from None
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
        raise AIGatewayError('个人模型网关必须使用本机回环地址。')

    project_key = getattr(settings, 'AI_BYOK_GATEWAY_PROJECT_KEY', '')
    key_file = getattr(settings, 'AI_BYOK_GATEWAY_PROJECT_KEY_FILE', '')
    if key_file:
        try:
            with open(key_file, 'r', encoding='ascii') as handle:
                project_key = handle.read(513).strip()
        except OSError:
            raise AIGatewayError('个人模型网关凭据不可用。') from None
    if not isinstance(project_key, str) or not PROJECT_KEY_PATTERN.fullmatch(project_key):
        raise AIGatewayError('个人模型网关凭据不可用。')
    return f'http://{parsed.netloc}', project_key



def build_gateway_client(provider_key: str):
    """Create only a request-scoped client from an explicitly authorized key.

    The T01 management service does not call this function. T02+ must validate
    model capabilities and epoch immediately before any dispatch.
    """
    from openai import OpenAI
    import httpx
    gateway_url, project_key = _gateway_configuration()
    http_client = httpx.Client(
        trust_env=False, follow_redirects=False,
        timeout=httpx.Timeout(GATEWAY_TIMEOUT_SECONDS, connect=5),
    )
    try:
        client = OpenAI(api_key=project_key, base_url=f'{gateway_url}/v1',
                        http_client=http_client, max_retries=0,
                        timeout=GATEWAY_TIMEOUT_SECONDS)
    except Exception:
        http_client.close()
        raise
    return _GatewayClient(client, http_client, provider_key)
