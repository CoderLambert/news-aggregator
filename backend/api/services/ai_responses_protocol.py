"""Stateless native Responses items behind the existing trusted BYOK gateway.

Research keeps its tool dispatcher and visible history. Native output items stay
server-side and are replayed intact, including encrypted reasoning items.
"""
import copy
import json
import re
from types import SimpleNamespace

OPENAI_RESPONSES_PRESET = 'openai/gpt-5.4-mini'


def uses_responses_protocol(alias):
    return isinstance(alias, str) and re.fullmatch(r'openai/[A-Za-z0-9][A-Za-z0-9._+-]{0,159}', alias) is not None

RESPONSES_PROTOCOL = 'openai-responses-v1'
MAX_NATIVE_BYTES = 4 * 1024 * 1024


class ResponsesProtocolError(ValueError):
    pass


def _native_items(items):
    if type(items) is not list or not items or len(items) > 256:
        raise ResponsesProtocolError('invalid_response')
    try:
        if len(json.dumps(items, allow_nan=False).encode('utf-8')) > MAX_NATIVE_BYTES:
            raise ResponsesProtocolError('invalid_response')
    except (TypeError, ValueError):
        raise ResponsesProtocolError('invalid_response') from None
    for item in items:
        if (type(item) is not dict or item.get('type') not in {'message', 'function_call', 'reasoning'}
                or item.get('status') not in (None, 'completed')):
            raise ResponsesProtocolError('invalid_response')
    return copy.deepcopy(items)


def responses_input(messages):
    if type(messages) is not list:
        raise ResponsesProtocolError('invalid_history')
    inputs, pending, answered, seen = [], set(), set(), set()
    for message in messages:
        if type(message) is not dict:
            raise ResponsesProtocolError('invalid_history')
        role = message.get('role')
        if role == 'assistant' and 'responses_output' in message:
            if pending:
                raise ResponsesProtocolError('missing_tool_result')
            items = _native_items(message['responses_output'])
            for item in items:
                if item['type'] == 'function_call':
                    call_id = item.get('call_id')
                    if not isinstance(call_id, str) or not call_id or call_id in seen:
                        raise ResponsesProtocolError('invalid_tool_call')
                    pending.add(call_id)
                    seen.add(call_id)
            inputs.extend(items)
        elif role == 'tool':
            call_id = message.get('tool_call_id')
            content = message.get('content')
            if (not isinstance(call_id, str) or call_id not in pending or call_id in answered
                    or type(content) is not str):
                raise ResponsesProtocolError('invalid_tool_result')
            inputs.append({'type': 'function_call_output', 'call_id': call_id, 'output': content})
            pending.remove(call_id)
            answered.add(call_id)
        elif role in {'system', 'user', 'assistant'}:
            if pending or message.get('tool_calls') or type(message.get('content')) is not str:
                raise ResponsesProtocolError('invalid_history')
            inputs.append({'role': role, 'content': message['content']})
        else:
            raise ResponsesProtocolError('invalid_history')
    if pending:
        raise ResponsesProtocolError('missing_tool_result')
    return inputs


def responses_payload(kwargs):
    allowed = {'model', 'messages', 'tools', 'tool_choice', 'max_tokens', 'temperature', 'stream', 'response_format'}
    if (set(kwargs) - allowed or not uses_responses_protocol(kwargs.get('model'))
            or (kwargs.get('stream') is not None and kwargs.get('stream') is not False)):
        raise ResponsesProtocolError('unsupported_request')
    maximum = kwargs.get('max_tokens')
    if type(maximum) is not int or not 1 <= maximum <= 8000:
        raise ResponsesProtocolError('invalid_limit')
    data = {'model': kwargs['model'], 'input': responses_input(kwargs.get('messages')),
            'store': False, 'include': ['reasoning.encrypted_content'], 'max_output_tokens': maximum}
    if kwargs['model'] == OPENAI_RESPONSES_PRESET:
        data['reasoning'] = {'effort': 'none'}
    if kwargs.get('response_format') is not None:
        if kwargs['response_format'] != {'type': 'json_object'}:
            raise ResponsesProtocolError('unsupported_format')
        data['text'] = {'format': {'type': 'json_object'}}
    tools = kwargs.get('tools')
    if tools is not None:
        if type(tools) is not list:
            raise ResponsesProtocolError('invalid_tools')
        converted = []
        for tool in tools:
            if (type(tool) is not dict or tool.get('type') != 'function'
                    or type(tool.get('function')) is not dict):
                raise ResponsesProtocolError('invalid_tools')
            function = copy.deepcopy(tool['function'])
            function.setdefault('strict', False)  # Existing server schemas allow optional arguments.
            converted.append({**function, 'type': 'function'})
        data['tools'] = converted
    choice = kwargs.get('tool_choice')
    if isinstance(choice, dict):
        if choice.get('type') != 'function' or type(choice.get('function')) is not dict:
            raise ResponsesProtocolError('invalid_tools')
        choice = {'type': 'function', 'name': choice['function'].get('name')}
    if choice is not None:
        data['tool_choice'] = choice
    # Keep the preset's documented non-thinking mode; do not forward the
    # research loop's Chat-specific sampling defaults to another protocol.
    return data


def responses_completion(data):
    if (type(data) is not dict or data.get('status') != 'completed'
            or data.get('error') is not None or data.get('incomplete_details') is not None):
        raise ResponsesProtocolError('incomplete_response')
    items = _native_items(data.get('output'))
    content, calls = [], []
    for item in items:
        if item['type'] == 'function_call':
            if (type(item.get('call_id')) is not str or not item['call_id']
                    or type(item.get('name')) is not str or not item['name']
                    or type(item.get('arguments')) is not str):
                raise ResponsesProtocolError('invalid_tool_call')
            calls.append({'id': item['call_id'], 'type': 'function',
                          'function': {'name': item['name'], 'arguments': item['arguments']}})
        elif item['type'] == 'message':
            if item.get('role') != 'assistant' or type(item.get('content')) is not list:
                raise ResponsesProtocolError('invalid_response')
            for block in item['content']:
                if (type(block) is not dict or block.get('type') != 'output_text'
                        or type(block.get('text')) is not str):
                    raise ResponsesProtocolError('invalid_response')
                content.append(block['text'])
    if not calls and not ''.join(content).strip():
        raise ResponsesProtocolError('incomplete_response')
    if len({call['id'] for call in calls}) != len(calls):
        raise ResponsesProtocolError('invalid_tool_call')
    usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
    return {'choices': [{'finish_reason': 'tool_calls' if calls else 'stop', 'message': {
        'role': 'assistant', 'content': None if calls else ''.join(content),
        'tool_calls': calls or None, 'responses_output': items}}],
        'usage': {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens')}}


def completion_object(data):
    choice = data['choices'][0]
    message = dict(choice['message'])
    message['tool_calls'] = [SimpleNamespace(id=call['id'], type='function',
        function=SimpleNamespace(**call['function'])) for call in message.get('tool_calls') or []]
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=choice['finish_reason'],
        message=SimpleNamespace(**message))], usage=SimpleNamespace(**data['usage']))
