"""Neutral, trusted LiteLLM Proxy transport for forthcoming T02–T09 consumers.

No legacy user credential lookup, provider fallback, or implicit model selection.
Chat Completions streaming retains the #101 fail-closed one-shot guard.
"""
import ipaddress
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
from django.conf import settings


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


class _OneShotCompletionStream:
    """Expose one verified non-streaming completion to existing SSE callers."""

    def __init__(self, response):
        # Our configured LiteLLM gateway does not safely expose a streamed
        # Chat Completions terminal yet. A non-streaming upstream response must
        # be fully terminal BEFORE any text becomes visible downstream.
        choices = getattr(response, 'choices', None)
        if not isinstance(choices, (list, tuple)) or len(choices) != 1:
            raise AIGatewayError('个人模型回复不完整，未接收有效结束状态。')
        choice = choices[0]
        if getattr(choice, 'finish_reason', None) != 'stop':
            # length, content_filter, tool_calls, EOF and unknown terminal
            # states must never masquerade as a completed text-only stream.
            raise AIGatewayError('个人模型回复未完整完成，未使用截断内容。')
        message = getattr(choice, 'message', None)
        content = getattr(message, 'content', None)
        if not isinstance(content, str) or not content.strip():
            raise AIGatewayError('个人模型回复内容为空或格式不正确。')
        self._chunks = [SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=content),
            finish_reason='stop',
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
            raise AIGatewayError('个人模型请求包含不受支持的额外参数。')
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
