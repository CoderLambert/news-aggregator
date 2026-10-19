"""T02 explicit, bounded, one-shot probes over the existing trusted Proxy.

No user URL, raw provider response, unbounded SDK retries or second gateway.
This module deliberately owns only protocol validation; owner and revision
authorization are checked by ai_model_views around each dispatch/commit.
"""
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from api.services.ai_gateway import AIGatewayError, ARTICLE_CHAT_SUPPORTED_ALIAS, _gateway_configuration
from api.services.ai_responses_protocol import (
    OPENAI_RESPONSES_MODELS, ResponsesProtocolError, responses_completion, responses_payload,
)

MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 15
_REQUEST_ID = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')
_CALL_ID = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')


@dataclass(frozen=True)
class ProbeOutcome:
    status: str
    safe_error_code: str = ''
    provider_request_id: str = ''
    input_tokens: int | None = None
    output_tokens: int | None = None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects())


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_property')
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError('non_standard_json')


def _json_parse(value):
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _request_id(headers):
    raw = headers.get('x-request-id', '') if headers else ''
    return raw if isinstance(raw, str) and _REQUEST_ID.fullmatch(raw) else ''


def _count(raw):
    return raw if type(raw) is int and 0 <= raw <= 2_147_483_647 else None


def _tool_call_valid(message):
    calls = message.get('tool_calls')
    if not isinstance(calls, list) or len(calls) != 1:
        return False
    call = calls[0]
    if (not isinstance(call, dict) or call.get('type') != 'function'
            or not isinstance(call.get('id'), str)
            or not _CALL_ID.fullmatch(call['id'])):
        return False
    function = call.get('function')
    if not isinstance(function, dict) or function.get('name') != 'byok_probe':
        return False
    raw = function.get('arguments')
    if not isinstance(raw, str) or len(raw) > 512:
        return False
    try:
        parsed = _json_parse(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and set(parsed) == {'ok'} and parsed['ok'] is True


def parse_completion(status_code, headers, raw, probe_kind):
    """Only an explicitly complete response may prove support or lack of tools."""
    request_id = _request_id(headers)
    if status_code != 200 or len(raw) > MAX_RESPONSE_BYTES:
        return ProbeOutcome('unknown', 'result_unknown', request_id)
    try:
        data = _json_parse(raw)
    except (ValueError, UnicodeDecodeError, TypeError):
        return ProbeOutcome('unknown', 'invalid_response', request_id)
    if not isinstance(data, dict) or not isinstance(data.get('choices'), list) or len(data['choices']) != 1:
        return ProbeOutcome('unknown', 'invalid_response', request_id)
    choice = data['choices'][0]
    if not isinstance(choice, dict) or not isinstance(choice.get('message'), dict):
        return ProbeOutcome('unknown', 'invalid_response', request_id)
    finish, message = choice.get('finish_reason'), choice['message']
    if probe_kind == 'text':
        if finish != 'stop' or not isinstance(message.get('content'), str) or not message['content'].strip():
            return ProbeOutcome('unknown', 'incomplete_or_invalid', request_id)
        status = 'succeeded'
    elif probe_kind == 'tools':
        if finish == 'tool_calls' and _tool_call_valid(message):
            status = 'succeeded'
        elif (finish == 'stop' and not message.get('tool_calls')
              and isinstance(message.get('content'), str) and message['content'].strip()):
            # A *complete* text response despite forced tool_choice explicitly
            # demonstrates this route declined the requested tool invocation.
            status = 'unsupported'
        else:
            return ProbeOutcome('unknown', 'incomplete_or_invalid', request_id)
    else:
        return ProbeOutcome('not_sent', 'invalid_probe')
    usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
    return ProbeOutcome(status, provider_request_id=request_id,
                        input_tokens=_count(usage.get('prompt_tokens')),
                        output_tokens=_count(usage.get('completion_tokens')))


def _payload(model_alias, probe_kind, provider_key):
    # Flash defaults to thinking, which rejects named tool_choice and can use
    # the probe's tiny output budget before producing a final text response.
    # These explicit capability checks need text/tools, not private reasoning.
    options = {'thinking': {'type': 'disabled'}} if model_alias == ARTICLE_CHAT_SUPPORTED_ALIAS else {}
    if probe_kind == 'tools':
        return {
            'model': model_alias, 'stream': False, 'max_tokens': 32,
            'messages': [{'role': 'system', 'content': 'Call the requested function to confirm tool support.'},
                         {'role': 'user', 'content': 'Run the capability check now.'}],
            'tools': [{'type': 'function', 'function': {
                'name': 'byok_probe', 'description': 'Confirm tool invocation.',
                'parameters': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                               'required': ['ok'], 'additionalProperties': False}}}],
            'tool_choice': {'type': 'function', 'function': {'name': 'byok_probe'}},
            'api_key': provider_key,
            **options,
        }
    return {
        'model': model_alias, 'stream': False, 'max_tokens': 8,
        'messages': [{'role': 'user', 'content': 'Reply with one short word confirming text output.'}],
        'api_key': provider_key,
        **options,
    }


def send_model_probe(*, provider_key: str, model_alias: str, probe_kind: str) -> ProbeOutcome:
    """One explicit paid-capable request; no retries, fallback or outside URLs."""
    if probe_kind not in ('text', 'tools') or not provider_key or not isinstance(provider_key, str):
        return ProbeOutcome('not_sent', 'invalid_probe')
    if not isinstance(model_alias, str) or not model_alias or len(model_alias) > 80:
        return ProbeOutcome('not_sent', 'invalid_route')
    try:
        gateway, project_key = _gateway_configuration()  # enforces local loopback
    except AIGatewayError:
        return ProbeOutcome('not_sent', 'gateway_unavailable')
    payload = _payload(model_alias, probe_kind, provider_key)
    native_responses = model_alias in OPENAI_RESPONSES_MODELS
    endpoint = 'chat/completions'
    if native_responses:
        payload.pop('api_key')
        payload['max_tokens'] = 64 if probe_kind == 'text' else 128
        payload = {**responses_payload(payload), 'api_key': provider_key}
        endpoint = 'responses'
    data = json.dumps(payload, separators=(',', ':')).encode()
    request = urllib.request.Request(
        f'{gateway}/v1/{endpoint}', data=data, method='POST',
        headers={'Accept': 'application/json', 'Authorization': f'Bearer {project_key}',
                 'Content-Type': 'application/json'})
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if native_responses:
                if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                    return ProbeOutcome('unknown', 'result_unknown', _request_id(response.headers))
                try:
                    raw = json.dumps(responses_completion(_json_parse(raw))).encode()
                except (ResponsesProtocolError, TypeError, ValueError, UnicodeDecodeError):
                    return ProbeOutcome('unknown', 'incomplete_or_invalid', _request_id(response.headers))
            return parse_completion(response.status, response.headers, raw, probe_kind)
    except urllib.error.HTTPError as exc:
        # 429, upstream validation and redirects do not prove lack of capability;
        # no error body is persisted or reflected to a user.
        return ProbeOutcome('unknown', 'gateway_rejected', _request_id(exc.headers))
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        # It may have been billed upstream even if the response was lost.
        return ProbeOutcome('unknown', 'result_unknown')
