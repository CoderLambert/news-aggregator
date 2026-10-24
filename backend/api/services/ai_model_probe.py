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

from api.services.ai_gateway import (
    AIGatewayError, ARTICLE_CHAT_SUPPORTED_ALIAS, _gateway_configuration, trusted_request_metadata,
)
from api.services.ai_responses_protocol import (
    uses_responses_protocol, ResponsesProtocolError, responses_completion, responses_payload,
)

from api.services.ai_messages_protocol import (
    uses_messages_protocol, MessagesProtocolError, messages_completion, messages_payload,
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
    if (not isinstance(data, dict) or data.get('error') is not None
            or not isinstance(data.get('choices'), list) or len(data['choices']) != 1):
        return ProbeOutcome('unknown', 'invalid_response', request_id)
    choice = data['choices'][0]
    if not isinstance(choice, dict) or not isinstance(choice.get('message'), dict):
        return ProbeOutcome('unknown', 'invalid_response', request_id)
    finish, message = choice.get('finish_reason'), choice['message']
    if message.get('refusal'):
        return ProbeOutcome('unknown', 'incomplete_or_invalid', request_id)
    if probe_kind == 'text':
        if (finish != 'stop' or message.get('tool_calls') or message.get('function_call')
                or not isinstance(message.get('content'), str) or not message['content'].strip()):
            return ProbeOutcome('unknown', 'incomplete_or_invalid', request_id)
        status = 'succeeded'
    elif probe_kind == 'tools':
        if finish == 'tool_calls' and _tool_call_valid(message):
            status = 'succeeded'
        elif (finish == 'stop' and not message.get('tool_calls')
              and isinstance(message.get('content'), str) and message['content'].strip()):
            # Auto selection is portable across trusted providers. Plain text
            # does not prove lack of tools, and never authorizes research.
            return ProbeOutcome('unknown', 'tool_call_not_observed', request_id)
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
    flash = model_alias == ARTICLE_CHAT_SUPPORTED_ALIAS
    options = {'thinking': {'type': 'disabled'}} if flash else {}
    # Compatible reasoning models can consume the old 8/32-token caps before
    # emitting even one answer/tool call. Keep one bounded explicit request;
    # never retry a clipped result or claim a capability from length/EOF.
    # Legacy Flash tools also need headroom: after tool_choice became auto,
    # real deepseek-flash replies hit the 32-token length terminal before a
    # complete tool_calls finish_reason (spend logs: completion_tokens==32).
    compatible = model_alias.startswith('newshub/')
    if probe_kind == 'tools':
        # With thinking disabled, named tool_choice is accepted on Flash and
        # keeps the one-shot call short; other routes keep portable auto.
        tool_choice = ({'type': 'function', 'function': {'name': 'byok_probe'}}
                       if flash else 'auto')
        max_tokens = 512 if compatible else (128 if flash else 32)
        return {
            'model': model_alias, 'stream': False, 'max_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': 'Call the requested function to confirm tool support.'},
                         {'role': 'user', 'content': 'Run the capability check now.'}],
            'tools': [{'type': 'function', 'function': {
                'name': 'byok_probe', 'description': 'Confirm tool invocation.',
                'parameters': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                               'required': ['ok'], 'additionalProperties': False}}}],
            'tool_choice': tool_choice,
            'api_key': provider_key,
            **options,
        }
    return {
        'model': model_alias, 'stream': False, 'max_tokens': 512 if compatible else 8,
        'messages': [{'role': 'user', 'content': 'Reply with one short word confirming text output.'}],
        'api_key': provider_key,
        **options,
    }


def send_model_probe(*, provider_key: str | None, model_alias: str, probe_kind: str,
                     connection_snapshot=None) -> ProbeOutcome:
    """One explicit paid-capable request; no retries, fallback or outside URLs."""
    if probe_kind not in ('text', 'tools'):
        return ProbeOutcome('not_sent', 'invalid_probe')
    if not isinstance(model_alias, str) or not model_alias or len(model_alias) > 256:
        return ProbeOutcome('not_sent', 'invalid_route')
    metadata = {}
    if model_alias.startswith('newshub/'):
        try:
            metadata = trusted_request_metadata(connection_snapshot, model_alias, provider_key)
        except AIGatewayError:
            return ProbeOutcome('not_sent', 'authorization_changed')
    elif type(provider_key) is not str or not provider_key:
        return ProbeOutcome('not_sent', 'invalid_probe')
    try:
        gateway, project_key = _gateway_configuration()  # enforces local loopback
    except AIGatewayError:
        return ProbeOutcome('not_sent', 'gateway_unavailable')
    payload = _payload(model_alias, probe_kind, provider_key)
    if metadata:
        payload['metadata'] = metadata
    native_responses = uses_responses_protocol(model_alias)
    native_messages = uses_messages_protocol(model_alias)
    endpoint = 'chat/completions'
    if native_responses:
        payload.pop('api_key')
        payload['max_tokens'] = 64 if probe_kind == 'text' else 128
        payload = {**responses_payload(payload), 'api_key': provider_key}
        endpoint = 'responses'
    elif native_messages:
        payload.pop('api_key')
        payload['max_tokens'] = 64 if probe_kind == 'text' else 128
        payload = {**messages_payload(payload), 'api_key': provider_key}
        endpoint = 'messages'
    data = json.dumps(payload, separators=(',', ':')).encode()
    request = urllib.request.Request(
        f'{gateway}/v1/{endpoint}', data=data, method='POST',
        headers={'Accept': 'application/json', 'Authorization': f'Bearer {project_key}',
                 'Content-Type': 'application/json'})
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if native_responses or native_messages:
                if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                    return ProbeOutcome('unknown', 'result_unknown', _request_id(response.headers))
                try:
                    normalize = responses_completion if native_responses else messages_completion
                    raw = json.dumps(normalize(_json_parse(raw))).encode()
                except (ResponsesProtocolError, MessagesProtocolError, TypeError, ValueError, UnicodeDecodeError):
                    return ProbeOutcome('unknown', 'incomplete_or_invalid', _request_id(response.headers))
            return parse_completion(response.status, response.headers, raw, probe_kind)
    except urllib.error.HTTPError as exc:
        # 429, upstream validation and redirects do not prove lack of capability;
        # no error body is persisted or reflected to a user.
        return ProbeOutcome('unknown', 'gateway_rejected', _request_id(exc.headers))
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        # It may have been billed upstream even if the response was lost.
        return ProbeOutcome('unknown', 'result_unknown')


class ModelDiscoveryError(RuntimeError):
    def __init__(self):
        super().__init__('model_discovery_unavailable')


def send_model_discovery(*, provider_key, connection_snapshot):
    """One explicit catalog request through the existing trusted local Proxy."""
    from api.services.ai_registry import profile_route_prefix
    from api.services.ai_endpoint_profiles import valid_upstream_model_id
    try:
        prefix = profile_route_prefix(connection_snapshot)
        if not prefix or not prefix.startswith('newshub/'):
            raise ModelDiscoveryError()
        alias = prefix + '/model-discovery'
        metadata = trusted_request_metadata(connection_snapshot, alias, provider_key)
        gateway, project_key = _gateway_configuration()
        payload = {'model': alias, 'api_key': provider_key, 'metadata': metadata}
        request = urllib.request.Request(gateway + '/newshub/models/discover', method='POST',
            data=json.dumps(payload, separators=(',', ':')).encode(), headers={
                'Authorization': 'Bearer ' + project_key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if response.status != 200 or len(raw) > MAX_RESPONSE_BYTES:
                raise ModelDiscoveryError()
        result = _json_parse(raw)
        if (type(result) is not dict or type(result.get('models')) is not list or len(result['models']) > 100
                or type(result.get('truncated')) is not bool
                or any(not valid_upstream_model_id(model) for model in result['models'])):
            raise ModelDiscoveryError()
        return {'models': result['models'], 'truncated': result['truncated']}
    except Exception:
        raise ModelDiscoveryError() from None
