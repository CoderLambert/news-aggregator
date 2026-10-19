"""Native Claude Messages envelopes for the existing BYOK dispatcher.

Opaque thinking blocks stay in private history. Tool execution and permissions
remain with the research service; this module never executes provider tools.
"""
import copy
import json

ANTHROPIC_MESSAGES_MODELS = frozenset({'anthropic/claude-haiku-5-5'})
MESSAGES_PROTOCOL = 'anthropic-messages-v1'
MAX_NATIVE_BYTES = 4 * 1024 * 1024


class MessagesProtocolError(ValueError):
    pass


def _content(blocks):
    if type(blocks) is not list or not blocks or len(blocks) > 256:
        raise MessagesProtocolError('invalid_content')
    try:
        if len(json.dumps(blocks, allow_nan=False).encode('utf-8')) > MAX_NATIVE_BYTES:
            raise ValueError
    except (TypeError, ValueError):
        raise MessagesProtocolError('invalid_content') from None
    for block in blocks:
        if type(block) is not dict:
            raise MessagesProtocolError('invalid_content')
        kind = block.get('type')
        if kind == 'text':
            valid = type(block.get('text')) is str
        elif kind == 'thinking':
            valid = (type(block.get('thinking')) is str
                     and type(block.get('signature')) is str and bool(block['signature']))
        elif kind == 'redacted_thinking':
            valid = type(block.get('data')) is str and bool(block['data'])
        elif kind == 'tool_use':
            valid = (type(block.get('id')) is str and bool(block['id'])
                     and type(block.get('name')) is str and bool(block['name'])
                     and type(block.get('input')) is dict
                     and block.get('caller', {'type': 'direct'}) == {'type': 'direct'})
        else:
            valid = False
        if not valid:
            raise MessagesProtocolError('invalid_content')
    return copy.deepcopy(blocks)


def messages_input(messages):
    if type(messages) is not list:
        raise MessagesProtocolError('invalid_history')
    system, inputs, pending, seen = [], [], set(), set()
    for message in messages:
        if type(message) is not dict:
            raise MessagesProtocolError('invalid_history')
        role = message.get('role')
        if role == 'assistant' and 'anthropic_content' in message:
            if pending:
                raise MessagesProtocolError('missing_tool_result')
            blocks = _content(message['anthropic_content'])
            for block in blocks:
                if block['type'] == 'tool_use':
                    call_id = block['id']
                    if call_id in seen:
                        raise MessagesProtocolError('duplicate_tool_call')
                    pending.add(call_id)
                    seen.add(call_id)
            inputs.append({'role': 'assistant', 'content': blocks})
        elif role == 'tool':
            call_id, content = message.get('tool_call_id'), message.get('content')
            if type(call_id) is not str or call_id not in pending or type(content) is not str:
                raise MessagesProtocolError('invalid_tool_result')
            block = {'type': 'tool_result', 'tool_use_id': call_id, 'content': content}
            if inputs[-1]['role'] != 'user':
                inputs.append({'role': 'user', 'content': []})
            inputs[-1]['content'].append(block)
            pending.remove(call_id)
        elif role in {'system', 'user', 'assistant'}:
            if pending or message.get('tool_calls') or type(message.get('content')) is not str:
                raise MessagesProtocolError('invalid_history')
            if role == 'system':
                if inputs:
                    raise MessagesProtocolError('late_system_message')
                system.append(message['content'])
            else:
                inputs.append({'role': role, 'content': message['content']})
        else:
            raise MessagesProtocolError('invalid_history')
    if pending:
        raise MessagesProtocolError('missing_tool_result')
    return '\n\n'.join(system), inputs


def messages_payload(kwargs):
    allowed = {'model', 'messages', 'tools', 'tool_choice', 'max_tokens', 'temperature', 'stream', 'response_format'}
    if (set(kwargs) - allowed or kwargs.get('model') not in ANTHROPIC_MESSAGES_MODELS
            or (kwargs.get('stream') is not None and kwargs.get('stream') is not False)):
        raise MessagesProtocolError('unsupported_request')
    maximum = kwargs.get('max_tokens')
    if type(maximum) is not int or not 1 <= maximum <= 8000:
        raise MessagesProtocolError('invalid_limit')
    system, messages = messages_input(kwargs.get('messages'))
    if kwargs.get('response_format') is not None:
        if kwargs['response_format'] != {'type': 'json_object'}:
            raise MessagesProtocolError('unsupported_format')
        # Messages has no Chat JSON-object switch. The existing classifier
        # already validates the full response against its server-owned schema.
        system = (system + '\n\nRespond with one valid JSON object and no other text.').strip()
    data = {'model': kwargs['model'], 'messages': messages, 'max_tokens': maximum,
            'thinking': {'type': 'disabled'}, 'output_config': {'effort': 'low'}}
    if system:
        data['system'] = system
    tools = kwargs.get('tools')
    if tools is not None:
        if type(tools) is not list:
            raise MessagesProtocolError('invalid_tools')
        converted = []
        for tool in tools:
            if (type(tool) is not dict or tool.get('type') != 'function'
                    or type(tool.get('function')) is not dict):
                raise MessagesProtocolError('invalid_tools')
            function = tool['function']
            if type(function.get('name')) is not str or type(function.get('parameters')) is not dict:
                raise MessagesProtocolError('invalid_tools')
            converted.append({'name': function['name'], 'description': function.get('description', ''),
                              'input_schema': copy.deepcopy(function['parameters'])})
        data['tools'] = converted
    choice = kwargs.get('tool_choice')
    if type(choice) is dict:
        function = choice.get('function')
        if choice.get('type') != 'function' or type(function) is not dict or type(function.get('name')) is not str:
            raise MessagesProtocolError('invalid_tools')
        data['tool_choice'] = {'type': 'tool', 'name': function['name']}
    elif choice is not None:
        if choice not in ('auto', 'none', 'required'):
            raise MessagesProtocolError('invalid_tools')
        data['tool_choice'] = {'type': 'any' if choice == 'required' else choice}
    # Fixed preset mode: Chat sampling defaults are not valid on this model.
    return data


def messages_completion(data):
    if (type(data) is not dict or data.get('type') != 'message' or data.get('role') != 'assistant'
            or data.get('stop_reason') not in {'end_turn', 'tool_use'}):
        raise MessagesProtocolError('incomplete_response')
    blocks = _content(data.get('content'))
    content, calls = [], []
    for block in blocks:
        if block['type'] == 'text':
            content.append(block['text'])
        elif block['type'] == 'tool_use':
            calls.append({'id': block['id'], 'type': 'function', 'function': {
                'name': block['name'], 'arguments': json.dumps(block['input'], allow_nan=False)}})
    if ((data['stop_reason'] == 'tool_use') != bool(calls)
            or (not calls and not ''.join(content).strip())
            or len({call['id'] for call in calls}) != len(calls)):
        raise MessagesProtocolError('incomplete_response')
    usage = data.get('usage') if type(data.get('usage')) is dict else {}
    return {'choices': [{'finish_reason': 'tool_calls' if calls else 'stop', 'message': {
        'role': 'assistant', 'content': None if calls else ''.join(content),
        'tool_calls': calls or None, 'anthropic_content': blocks}}],
        'usage': {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens')}}
