"""Neutral trusted LiteLLM Proxy transport for explicit BYOK consumers.

No legacy user credential lookup, provider fallback, or implicit model selection.
Approved manifest Chat routes and the existing DeepSeek route stream only with
their Proxy proof. Native one-shot protocols use explicit buffered delivery.
"""
import ipaddress
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
from django.conf import settings
from api.services.ai_responses_protocol import (
    uses_responses_protocol, ResponsesProtocolError, completion_object,
    responses_completion, responses_payload,
)

from api.services.ai_messages_protocol import (
    uses_messages_protocol, MessagesProtocolError, messages_completion, messages_payload,
)


class AIGatewayError(RuntimeError):
    pass


class _BufferedText:
    """Deliver a complete verified one-shot response through the text consumer API."""
    def __init__(self, response):
        choices = getattr(response, 'choices', None)
        if not isinstance(choices, (list, tuple)) or len(choices) != 1:
            raise AIGatewayError('个人模型返回了不完整或无法验证的响应。')
        choice = choices[0]
        message = getattr(choice, 'message', None)
        content = getattr(message, 'content', None)
        if (getattr(choice, 'finish_reason', None) != 'stop' or type(content) is not str or not content.strip()
                or len(content) > 262144 or any(getattr(message, name, None)
                    for name in ('tool_calls', 'function_call', 'refusal'))):
            raise AIGatewayError('个人模型返回了不完整或无法验证的响应。')
        self.content, self.usage = content, getattr(response, 'usage', None)
        self.closed = False

    def __iter__(self):
        if self.closed:
            return
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=self.content), finish_reason=None)])
        if not self.closed:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason='stop')],
                                  usage=self.usage)

    def close(self):
        self.closed = True


def trusted_request_metadata(connection_snapshot, model_alias, provider_key):
    """Build trusted-issuer metadata only after the shared current credential fence."""
    from api.services.ai_credentials import ConnectionSnapshot, require_active_snapshot, read_execution_credential
    from api.services.ai_model_registry import get_trusted_route
    from api.services.ai_registry import profile_route_prefix
    import hmac
    if type(connection_snapshot) is not ConnectionSnapshot or type(model_alias) is not str:
        raise AIGatewayError('个人模型身份不可用。')
    try:
        connection = require_active_snapshot(connection_snapshot)
        expected = read_execution_credential(connection_snapshot)
        if not ((expected is None and provider_key is None) or type(expected) is str
                and type(provider_key) is str and hmac.compare_digest(expected.encode(), provider_key.encode())):
            raise ValueError
        prefix = profile_route_prefix(connection)
        if not prefix or not model_alias.startswith(prefix + '/'):
            raise ValueError
        route = get_trusted_route(connection, model_alias[len(prefix) + 1:])
        if route is None or route['proxy_alias'] != model_alias:
            raise ValueError
    except Exception:
        raise AIGatewayError('个人模型身份不可用。') from None
    return ({'newshub_owner_id': connection_snapshot.user_id, 'newshub_auth_mode': connection_snapshot.auth_mode}
            if model_alias.startswith('newshub/') else {})


def text_generation_options(selection, maximum):
    """Keep provider-specific thinking settings on their verified legacy route."""
    options = {'max_tokens': min(maximum, 8000) if uses_responses_protocol(selection.proxy_alias)
               or uses_messages_protocol(selection.proxy_alias) else maximum}
    if selection.proxy_alias == ARTICLE_CHAT_SUPPORTED_ALIAS:
        options['reasoning_effort'] = 'none'
    return options


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
    def __init__(self, completions, provider_key: str | None, responses=None, messages_getter=None, selection=None):
        self._completions = completions
        self._provider_key = provider_key
        self._responses = responses
        self._messages_getter = messages_getter
        self._selection = selection
        self._route = None
        if selection is not None:
            from api.services.ai_model_registry import get_trusted_route
            self._route = get_trusted_route(selection.connection, selection.model_id)

    def create(self, **kwargs):
        metadata = {}
        if kwargs.pop('extra_body', None) not in (None, {}):
            raise AIGatewayError('个人模型请求包含不受支持的额外参数。')
        if 'metadata' in kwargs:
            raise AIGatewayError('个人模型请求包含不受支持的额外参数。')
        if self._selection is not None:
            from api.services.ai_task_preferences import require_task_model_snapshot
            require_task_model_snapshot(self._selection, owner_id=self._selection.user_id)
            if not self._route or kwargs.get('model') != self._selection.proxy_alias:
                raise AIGatewayError('个人模型路由不可用。')
            metadata = trusted_request_metadata(self._selection.connection, kwargs['model'], self._provider_key)
        elif str(kwargs.get('model', '')).startswith('newshub/'):
            raise AIGatewayError('个人模型身份不可用。')
        requested_stream = kwargs.get('stream') is True
        if requested_stream and self._route and self._route['delivery_mode'] == 'buffered':
            kwargs['stream'] = False
            kwargs.pop('stream_options', None)
            return _BufferedText(self.create(**kwargs))
        if requested_stream and kwargs.get('model') != ARTICLE_CHAT_SUPPORTED_ALIAS:
            if not self._route or self._route['delivery_mode'] != 'streaming':
                raise AIGatewayError('个人模型流式路由不可用。')
        native_options = {}
        if uses_messages_protocol(kwargs.get('model')) or uses_responses_protocol(kwargs.get('model')):
            timeout = kwargs.pop('timeout', None)
            if timeout is not None:
                if type(timeout) not in (int, float) or not 0 < timeout <= GATEWAY_TIMEOUT_SECONDS:
                    raise AIGatewayError('个人模型请求超时参数无效。')
                native_options['timeout'] = timeout
        if uses_messages_protocol(kwargs.get('model')):
            if self._messages_getter is None:
                raise AIGatewayError('个人模型原生协议不可用。')
            try:
                data = messages_payload(kwargs)
                result = self._messages_getter().create(**data, **native_options,
                                                       extra_body={'api_key': self._provider_key})
                raw = result if isinstance(result, dict) else result.model_dump(mode='json', exclude_none=True)
                return completion_object(messages_completion(raw))
            except MessagesProtocolError:
                raise AIGatewayError('个人模型返回了不完整或无法验证的响应。') from None
        if uses_responses_protocol(kwargs.get('model')):
            if self._responses is None:
                raise AIGatewayError('个人模型原生协议不可用。')
            try:
                data = responses_payload(kwargs)
                result = self._responses.create(**data, **native_options,
                                                extra_body={'api_key': self._provider_key})
                raw = result if isinstance(result, dict) else result.model_dump(mode='json', exclude_none=True)
                return completion_object(responses_completion(raw))
            except ResponsesProtocolError:
                raise AIGatewayError('个人模型返回了不完整或无法验证的响应。') from None
        kwargs['extra_body'] = {'api_key': self._provider_key, **({'metadata': metadata} if metadata else {})}
        # OpenAI's SDK starts the HTTP request here and returns a closeable
        # iterator. Do not buffer, defer, retry, or convert an uncertain stream.
        return self._completions.create(**kwargs)


class _GatewayClient:
    """Narrow client adapter that never exposes the provider key as SDK auth."""

    _newshub_max_attempts = 1

    def __init__(self, client, http_client, provider_key: str | None, messages_factory=None, selection=None):
        self._client = client
        self._http_client = http_client
        self._messages_factory = messages_factory
        self._messages_client = None
        self.chat = SimpleNamespace(
            completions=_GatewayCompletions(client.chat.completions, provider_key,
                                           responses=getattr(client, 'responses', None),
                                           messages_getter=self._native_messages, selection=selection),
        )

    def _native_messages(self):
        if self._messages_client is None:
            if self._messages_factory is None:
                raise AIGatewayError('个人模型原生协议不可用。')
            self._messages_client = self._messages_factory()
        return self._messages_client.messages

    def close(self):
        try:
            try:
                if self._messages_client is not None:
                    self._messages_client.close()
            finally:
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



def build_gateway_client(provider_key: str | None, *, selection=None):
    """Create only a request-scoped client from an explicitly authorized key.

    The T01 management service does not call this function. T02+ must validate
    model capabilities and epoch immediately before any dispatch.
    """
    from openai import OpenAI
    import httpx
    if selection is not None:
        from api.services.ai_task_preferences import require_task_model_snapshot
        require_task_model_snapshot(selection, owner_id=selection.user_id)
        trusted_request_metadata(selection.connection, selection.proxy_alias, provider_key)
    elif type(provider_key) is not str or not provider_key:
        raise AIGatewayError('个人模型身份不可用。')
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
    def messages_factory():
        from anthropic import Anthropic, DefaultHttpxClient
        import httpx2
        native_http = DefaultHttpxClient(
            trust_env=False, follow_redirects=False,
            timeout=httpx2.Timeout(GATEWAY_TIMEOUT_SECONDS, connect=5),
        )
        try:
            native = Anthropic(api_key=project_key, webhook_key='', base_url=gateway_url,
                             http_client=native_http, max_retries=0,
                             timeout=GATEWAY_TIMEOUT_SECONDS)
            # The pinned SDK otherwise merges ANTHROPIC_CUSTOM_HEADERS into
            # requests even with explicit auth. Only our project auth may flow
            # to the trusted Proxy; no ambient header configuration is allowed.
            native._custom_headers = {}
            return native
        except Exception:
            native_http.close()
            raise

    return _GatewayClient(client, http_client, provider_key, messages_factory=messages_factory, selection=selection)
