"""One-shot BYOK model probes through the configured LiteLLM project route."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 15
REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')
PROJECT_KEY_PATTERN = re.compile(r'^sk-[A-Za-z0-9_-]{16,256}$')
TOOLS_PROBE_NAME = 'byok_probe'


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


_URL_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirectHandler(),
)


@dataclass(frozen=True)
class ProbeOutcome:
    status: str
    safe_error_code: str = ''
    provider_request_id: str = ''
    input_tokens: int | None = None
    output_tokens: int | None = None


def _valid_gateway_url(value: str) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 512:
        return None
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {'', '/'}
    ):
        return None
    return f'{parsed.scheme}://{parsed.netloc}'


def gateway_is_configured(gateway_url: str, project_key: str) -> bool:
    return _valid_gateway_url(gateway_url) is not None and isinstance(project_key, str) and bool(PROJECT_KEY_PATTERN.fullmatch(project_key))


def _probe_payload(model_alias: str, probe_kind: str, provider_key: str) -> dict:
    if probe_kind == 'tools':
        return {
            'model': model_alias,
            'messages': [
                {'role': 'system', 'content': 'Call the required function to complete this short capability check.'},
                {'role': 'user', 'content': 'Run the required capability check now.'},
            ],
            'tools': [{
                'type': 'function',
                'function': {
                    'name': TOOLS_PROBE_NAME,
                    'description': 'Report that the tool capability check ran.',
                    'parameters': {
                        'type': 'object',
                        'properties': {'ok': {'type': 'boolean'}},
                        'required': ['ok'],
                        'additionalProperties': False,
                    },
                },
            }],
            'tool_choice': {'type': 'function', 'function': {'name': TOOLS_PROBE_NAME}},
            'max_tokens': 32,
            'temperature': 0,
            'stream': False,
            'api_key': provider_key,
        }
    return {
        'model': model_alias,
        'messages': [
            {'role': 'user', 'content': 'Reply with one short word confirming this text capability check.'},
        ],
        'max_tokens': 8,
        'temperature': 0,
        'stream': False,
        'api_key': provider_key,
    }


def _token_count(value) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2_147_483_647:
        return value
    return None


def _request_id(headers) -> str:
    candidate = headers.get('x-request-id', '') if headers else ''
    return candidate if isinstance(candidate, str) and REQUEST_ID_PATTERN.fullmatch(candidate) else ''


def _parse_success(status_code: int, headers, body: bytes, probe_kind: str) -> ProbeOutcome:
    request_id = _request_id(headers)
    if status_code < 200 or status_code >= 300 or len(body) > MAX_RESPONSE_BYTES:
        return ProbeOutcome('failed', 'gateway_rejected', request_id)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ProbeOutcome('failed', 'invalid_gateway_response', request_id)
    if not isinstance(payload, dict):
        return ProbeOutcome('failed', 'invalid_gateway_response', request_id)
    choices = payload.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ProbeOutcome('failed', 'invalid_gateway_response', request_id)
    message = choices[0].get('message')
    if not isinstance(message, dict):
        return ProbeOutcome('failed', 'invalid_gateway_response', request_id)
    if probe_kind == 'tools':
        calls = message.get('tool_calls')
        supported = (
            isinstance(calls, list)
            and bool(calls)
            and isinstance(calls[0], dict)
            and isinstance(calls[0].get('function'), dict)
            and calls[0]['function'].get('name') == TOOLS_PROBE_NAME
        )
    else:
        supported = isinstance(message.get('content'), str) and bool(message['content'].strip())
    if not supported:
        return ProbeOutcome('failed', 'probe_not_supported', request_id)

    usage = payload.get('usage') if isinstance(payload.get('usage'), dict) else {}
    return ProbeOutcome(
        'succeeded',
        provider_request_id=request_id,
        input_tokens=_token_count(usage.get('prompt_tokens')),
        output_tokens=_token_count(usage.get('completion_tokens')),
    )


def send_model_probe(*, gateway_url: str, project_key: str, provider_key: str, model_alias: str, probe_kind: str) -> ProbeOutcome:
    """Send one bounded request; never follows redirects, retries, or exposes raw errors."""
    base_url = _valid_gateway_url(gateway_url)
    if base_url is None or not isinstance(project_key, str) or not PROJECT_KEY_PATTERN.fullmatch(project_key):
        return ProbeOutcome('not_sent', 'gateway_unavailable')
    if probe_kind not in {'text', 'tools'} or not isinstance(provider_key, str) or not provider_key:
        return ProbeOutcome('not_sent', 'invalid_probe')

    payload = json.dumps(
        _probe_payload(model_alias, probe_kind, provider_key),
        ensure_ascii=True,
        separators=(',', ':'),
    ).encode('utf-8')
    request = urllib.request.Request(
        f'{base_url}/v1/chat/completions',
        data=payload,
        headers={
            'Accept': 'application/json',
            'Authorization': f'Bearer {project_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with _URL_OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            return _parse_success(response.status, response.headers, body, probe_kind)
    except urllib.error.HTTPError as error:
        return ProbeOutcome('failed', 'gateway_rejected', _request_id(error.headers))
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        # The request may have reached the provider before the connection failed.
        return ProbeOutcome('unknown', 'result_unknown')
