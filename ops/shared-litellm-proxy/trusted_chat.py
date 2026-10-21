"""LiteLLM's native CustomLLM extension delegates to its mature raw Chat stack.

Only an admitted, request-local execution can invoke the provider. No custom
HTTP protocol, environment credential lookup or dynamic endpoint registration.
"""
import asyncio
from dataclasses import dataclass, field
import importlib.metadata
import json
import math
import re
import uuid

from litellm import CustomLLM
from litellm.llms.custom_llm import CustomLLMError
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from litellm.llms.custom_httpx.llm_http_handler import BaseLLMHTTPHandler
from litellm.llms.openai.chat.gpt_transformation import OpenAIUnknownModelConfig

from trusted_routes import resolve_route
from trusted_transport import EgressDenied, MAX_BODY_BYTES, OneShotClient

_EXECUTIONS = {}
_EXECUTION_FIELD = '_newshub_execution_id'
_FUNCTION_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_CHAT_OPTIONS = frozenset({'stream', 'max_tokens', 'max_completion_tokens', 'temperature', 'top_p',
                           'presence_penalty', 'frequency_penalty', 'seed', 'stop', 'n', 'tools',
                           'tool_choice', 'parallel_tool_calls', 'stream_options', 'response_format'})


def _function(value, *, definition):
    fields = {'name', 'description', 'parameters', 'strict'} if definition else {'name', 'arguments'}
    if (type(value) is not dict or value.keys() - fields
            or type(value.get('name')) is not str or not _FUNCTION_NAME.fullmatch(value['name'])):
        raise EgressDenied()
    if definition:
        if ('description' in value and type(value['description']) is not str
                or 'parameters' in value and type(value['parameters']) is not dict
                or 'strict' in value and type(value['strict']) is not bool):
            raise EgressDenied()
    elif type(value.get('arguments')) is not str:
        raise EgressDenied()


def validate_chat_input(messages, options, *, stream):
    """Limit input before mature adapters can download/transform media or tools.

    Function schemas/history are data only. This route never invokes built-in
    tools, fetches files/images/audio, or accepts provider/network overrides.
    """
    if (type(messages) is not list or not 1 <= len(messages) <= 1024
            or type(options) is not dict or options.keys() - _CHAT_OPTIONS or type(stream) is not bool):
        raise EgressDenied()
    for message in messages:
        if type(message) is not dict or message.keys() - {'role', 'content', 'name', 'tool_calls', 'tool_call_id', 'reasoning_content'}:
            raise EgressDenied()
        role, content = message.get('role'), message.get('content')
        if role not in ('system', 'developer', 'user', 'assistant', 'tool'):
            raise EgressDenied()
        if 'reasoning_content' in message and (role != 'assistant'
                or type(message['reasoning_content']) is not str or len(message['reasoning_content']) > MAX_BODY_BYTES):
            raise EgressDenied()
        if content is None:
            if role != 'assistant' or not message.get('tool_calls'):
                raise EgressDenied()
        elif type(content) is list:
            if not content or any(type(block) is not dict or set(block) != {'type', 'text'}
                                  or block['type'] != 'text' or type(block['text']) is not str for block in content):
                raise EgressDenied()
        elif type(content) is not str:
            raise EgressDenied()
        if 'name' in message and (type(message['name']) is not str or not _FUNCTION_NAME.fullmatch(message['name'])):
            raise EgressDenied()
        if (('tool_call_id' in message) != (role == 'tool') or (role == 'tool' and (
                type(message['tool_call_id']) is not str or not 1 <= len(message['tool_call_id']) <= 256))):
            raise EgressDenied()
        if 'tool_calls' in message:
            calls = message['tool_calls']
            if role != 'assistant' or type(calls) is not list or not 1 <= len(calls) <= 32:
                raise EgressDenied()
            for call in calls:
                if (type(call) is not dict or set(call) != {'id', 'type', 'function'} or call['type'] != 'function'
                        or type(call['id']) is not str or not 1 <= len(call['id']) <= 256):
                    raise EgressDenied()
                _function(call['function'], definition=False)
    for name, value in options.items():
        if name in ('max_tokens', 'max_completion_tokens'):
            if type(value) is not int or not 1 <= value <= 131072:
                raise EgressDenied()
        elif name in ('temperature', 'top_p', 'presence_penalty', 'frequency_penalty'):
            lower, upper = {'temperature': (0, 2), 'top_p': (0, 1),
                            'presence_penalty': (-2, 2), 'frequency_penalty': (-2, 2)}[name]
            if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
                raise EgressDenied()
        elif name == 'seed' and type(value) is not int:
            raise EgressDenied()
        elif name == 'n' and (type(value) is not int or value != 1):
            raise EgressDenied()
        elif name == 'stream' and (type(value) is not bool or value is not stream):
            raise EgressDenied()
        elif name == 'stop' and not (type(value) is str or type(value) is list
                and 1 <= len(value) <= 4 and all(type(part) is str for part in value)):
            raise EgressDenied()
        elif name == 'parallel_tool_calls' and type(value) is not bool:
            raise EgressDenied()
        elif name == 'stream_options' and (not stream or type(value) is not dict
                or set(value) != {'include_usage'} or type(value['include_usage']) is not bool):
            raise EgressDenied()
        elif name == 'response_format' and value != {'type': 'json_object'}:
            raise EgressDenied()
        elif name == 'tools':
            if stream or type(value) is not list or not 1 <= len(value) <= 32:
                raise EgressDenied()
            for tool in value:
                if type(tool) is not dict or set(tool) != {'type', 'function'} or tool['type'] != 'function':
                    raise EgressDenied()
                _function(tool['function'], definition=True)
        elif name == 'tool_choice':
            if stream:
                raise EgressDenied()
            if type(value) is str and value in ('auto', 'none', 'required'):
                continue
            if (type(value) is not dict or set(value) != {'type', 'function'} or value['type'] != 'function'
                    or type(value['function']) is not dict or set(value['function']) != {'name'}
                    or type(value['function']['name']) is not str or not _FUNCTION_NAME.fullmatch(value['function']['name'])):
                raise EgressDenied()
    try:
        if len(json.dumps([messages, options], allow_nan=False).encode()) > MAX_BODY_BYTES:
            raise EgressDenied()
    except (TypeError, ValueError, RecursionError):
        raise EgressDenied() from None


@dataclass
class _Execution:
    alias: str
    owner_id: int
    auth_mode: str
    profile: dict
    model_id: str
    provider_key: str | None = field(repr=False)
    client: OneShotClient | None = field(default=None, repr=False)
    timer: object = field(default=None, repr=False)

    def check_current(self):
        profile, model_id = resolve_route(self.alias, owner_id=self.owner_id, auth_mode=self.auth_mode)
        if profile['policy_digest'] != self.profile['policy_digest'] or model_id != self.model_id:
            raise EgressDenied()


def _metadata(data):
    if type(data) is not dict:
        return {}
    for field in ('metadata', 'litellm_metadata'):
        value = data.get(field)
        if type(value) is dict and _EXECUTION_FIELD in value:
            return value
    return {}


def execution_for(data):
    identity = _metadata(data).get(_EXECUTION_FIELD)
    return _EXECUTIONS.get(identity) if type(identity) is str else None


async def _finish_execution(identity):
    state = _EXECUTIONS.pop(identity, None) if type(identity) is str else None
    if state is not None:
        state.provider_key = None
        state.timer.cancel()
        if state.client is not None:
            await state.client.close()


async def finish_request(data):
    await _finish_execution(_metadata(data).get(_EXECUTION_FIELD))


def admit_request(data):
    if importlib.metadata.version('litellm') != '1.105.0' or len(_EXECUTIONS) >= 512:
        raise EgressDenied()
    metadata = data.get('metadata', {})
    if type(metadata) is not dict or _EXECUTION_FIELD in metadata:
        raise EgressDenied()
    validate_chat_input(data.get('messages'), {name: value for name, value in data.items() if name in _CHAT_OPTIONS},
                        stream=data.get('stream', False))
    owner_id, mode = metadata.get('newshub_owner_id'), metadata.get('newshub_auth_mode')
    profile, model = resolve_route(data.get('model'), owner_id=owner_id, auth_mode=mode)
    key = data.get('api_key')
    if ((mode == 'none' and key is not None) or (mode == 'api_key' and (
            type(key) is not str or not key or any(ord(char) <= 32 or ord(char) >= 127 for char in key)))):
        raise EgressDenied()
    identity = uuid.uuid4().hex
    state = _Execution(data['model'], owner_id, mode, profile, model, key)
    _EXECUTIONS[identity] = state
    data['metadata'] = {**metadata, _EXECUTION_FIELD: identity}
    loop = asyncio.get_running_loop()
    state.timer = loop.call_later(185, lambda: loop.create_task(_finish_execution(identity)))
    return data


class _OneShotHandler(AsyncHTTPHandler):
    def __init__(self, client):
        # Do not initialize the parent's environment/proxy session or its
        # reconnect retry path. Retain the official handler type contract.
        self._transport = client
        self._client = client.client
        self._owns_client = False

    async def post(self, *args, **kwargs):
        return await self._transport.post(*args, **kwargs)

    async def close(self):
        await self._transport.close()


class TrustedChatProvider(CustomLLM):
    async def _complete(self, arguments, *, stream):
        state = execution_for(arguments.get('litellm_params'))
        if (state is None or state.client is not None or arguments.get('model') != state.model_id
                or arguments.get('api_base') != state.profile['api_base']):
            raise EgressDenied()
        state.check_current()
        options = {**arguments.get('optional_params', {}), 'stream': stream}
        # Pinned LiteLLM translates its server-side num_retries=0 setting to
        # this adapter-only field. Accept only that exact inert value.
        if 'max_retries' in options:
            retries = options.pop('max_retries')
            if type(retries) is not int or retries != 0:
                raise EgressDenied()
        validate_chat_input(arguments.get('messages'), options, stream=stream)
        state.client = OneShotClient(state.profile, provider_key=state.provider_key,
                                     model_id=state.model_id, check_current=state.check_current)
        return await BaseLLMHTTPHandler().completion(
            model=state.model_id, messages=arguments['messages'], api_base=state.profile['api_base'],
            custom_llm_provider='openai', model_response=arguments['model_response'],
            encoding=arguments['encoding'], logging_obj=arguments['logging_obj'],
            optional_params=options, timeout=180,
            litellm_params=arguments.get('litellm_params', {}),
            acompletion=True, stream=stream, api_key=state.provider_key, headers={},
            client=_OneShotHandler(state.client), provider_config=OpenAIUnknownModelConfig(),
        )

    async def acompletion(self, **kwargs):
        try:
            return await self._complete(kwargs, stream=False)
        except Exception:
            # Normalizers can put entire malformed bodies in their exception
            # text. Never let that text reach outer Proxy logging or clients.
            raise CustomLLMError(status_code=502, message='BYOK_TRUSTED_UPSTREAM_FAILED') from None
        finally:
            state = execution_for(kwargs.get('litellm_params'))
            if state and state.client:
                await state.client.close()

    async def astreaming(self, **kwargs):
        response = None
        try:
            response = await self._complete(kwargs, stream=True)
            async for chunk in response:
                yield chunk
        except Exception:
            raise CustomLLMError(status_code=502, message='BYOK_TRUSTED_UPSTREAM_FAILED') from None
        finally:
            if response is not None:
                await response.aclose()
            state = execution_for(kwargs.get('litellm_params'))
            if state and state.client:
                await state.client.close()


provider = TrustedChatProvider()
