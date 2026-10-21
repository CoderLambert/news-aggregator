"""Bounded raw Chat proof and a DNS-pinned httpcore connect boundary.

No model routing or credential selection occurs here. The caller supplies a
validated administrator policy and rechecks its current authorization.
"""
import asyncio
import importlib.metadata
import ipaddress
import json
import socket
from urllib.parse import urlsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpcore._backends.base import AsyncNetworkBackend


MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_FRAME_BYTES = 256 * 1024
MAX_STREAM_BYTES = 4 * 1024 * 1024


class TerminalInvalid(ValueError):
    def __init__(self):
        super().__init__('trusted_response_incomplete')


class EgressDenied(ValueError):
    def __init__(self):
        super().__init__('trusted_endpoint_egress_denied')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TerminalInvalid()
        result[key] = value
    return result


def _reject_constant(_value):
    raise TerminalInvalid()


def strict_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, TypeError, RecursionError):
        raise TerminalInvalid() from None


def verify_completion(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BODY_BYTES:
        raise TerminalInvalid()
    data = strict_json(raw)
    if type(data) is not dict or data.get('error') is not None:
        raise TerminalInvalid()
    choices = data.get('choices')
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        raise TerminalInvalid()
    choice = choices[0]
    reason = choice.get('finish_reason')
    message = choice.get('message')
    if (type(choice.get('index')) is not int or choice['index'] != 0 or type(message) is not dict
            or reason not in ('stop', 'tool_calls', 'length', 'content_filter', 'function_call')):
        raise TerminalInvalid()
    if (message.get('role') != 'assistant' or message.get('refusal')
            or (message.get('content') is not None and type(message['content']) is not str)):
        raise TerminalInvalid()
    calls = message.get('tool_calls')
    if calls is not None:
        if type(calls) is not list or len(calls) > 32 or calls and reason != 'tool_calls':
            raise TerminalInvalid()
        for call in calls:
            if (type(call) is not dict or type(call.get('id')) is not str or call.get('type') != 'function'
                    or type(call.get('function')) is not dict or type(call['function'].get('name')) is not str
                    or type(call['function'].get('arguments')) is not str):
                raise TerminalInvalid()
    if reason == 'tool_calls' and not calls:
        raise TerminalInvalid()
    return reason


class SSEVerifier:
    """Release deltas now; release terminal bytes only after raw stop+DONE+EOF."""
    def __init__(self):
        self._buffer = bytearray()
        self._held = []
        self._total = 0
        self._stop = self._done = self._usage = False
        self.verified = False

    def feed(self, data):
        if self.verified or not isinstance(data, bytes):
            raise TerminalInvalid()
        self._total += len(data)
        if self._total > MAX_STREAM_BYTES:
            raise TerminalInvalid()
        self._buffer.extend(data)
        result = []
        while True:
            # Preserve actual wire bytes while accepting ordinary LF/CRLF SSE.
            indices = [(self._buffer.find(boundary), boundary) for boundary in (b'\n\n', b'\r\n\r\n')]
            indices = [(position, boundary) for position, boundary in indices if position >= 0]
            if not indices:
                if len(self._buffer) > MAX_FRAME_BYTES:
                    raise TerminalInvalid()
                break
            position, boundary = min(indices, key=lambda entry: entry[0])
            end = position + len(boundary)
            if end > MAX_FRAME_BYTES:
                raise TerminalInvalid()
            wire = bytes(self._buffer[:end])
            del self._buffer[:end]
            self._event(wire)
            if self._stop:
                self._held.append(wire)
            else:
                result.append(wire)
        return result

    def _event(self, wire):
        try:
            lines = wire.decode('utf-8', errors='strict').splitlines()
        except UnicodeDecodeError:
            raise TerminalInvalid() from None
        values = []
        for line in lines:
            if not line or line.startswith(':'):
                continue
            field, _separator, value = line.partition(':')
            value = value[1:] if value.startswith(' ') else value
            if field == 'data':
                values.append(value)
            elif field == 'event' and value not in ('message', ''):
                raise TerminalInvalid()
            elif field not in ('id', 'retry', 'event'):
                raise TerminalInvalid()
        if not values:
            return
        data = '\n'.join(values)
        if self._done:
            raise TerminalInvalid()
        if data == '[DONE]':
            if not self._stop:
                raise TerminalInvalid()
            self._done = True
            return
        parsed = strict_json(data)
        if type(parsed) is not dict or parsed.get('error') is not None:
            raise TerminalInvalid()
        choices = parsed.get('choices')
        if choices == [] and type(parsed.get('usage')) is dict:
            if not self._stop or self._usage:
                raise TerminalInvalid()
            self._usage = True
            return
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict or self._stop:
            raise TerminalInvalid()
        choice = choices[0]
        delta = choice.get('delta')
        if (choice.get('index') != 0 or type(delta) is not dict
                or delta.get('tool_calls') or delta.get('function_call') or delta.get('refusal')):
            raise TerminalInvalid()
        if any(delta.get(field) is not None and type(delta[field]) is not str
               for field in ('content', 'reasoning', 'reasoning_content')):
            raise TerminalInvalid()
        reason = choice.get('finish_reason')
        if reason is not None:
            if reason != 'stop':
                raise TerminalInvalid()
            self._stop = True

    def finish(self):
        if self.verified or self._buffer or not self._stop or not self._done:
            raise TerminalInvalid()
        self.verified = True
        return self._held


class PinnedBackend(AsyncNetworkBackend):
    """Resolve once, validate every answer, then connect one approved literal IP.

    httpcore keeps the original URL hostname for Host/SNI/certificate checking.
    Its network backend receives only our literal address for the TCP connect.
    """
    def __init__(self, profile, check_current):
        self._url = urlsplit(profile['api_base'])
        self._port = self._url.port or (443 if self._url.scheme == 'https' else 80)
        self._allowed_ips = frozenset(profile['allowed_ips'])
        self._check_current = check_current
        self._backend = AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self._check_current()
        if host != self._url.hostname or port != self._port or local_address is not None:
            raise EgressDenied()
        try:
            address = ipaddress.ip_address(host)
            addresses = [str(address)]
        except ValueError:
            loop = asyncio.get_running_loop()
            async with asyncio.timeout(timeout or 5):
                records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            try:
                addresses = list(dict.fromkeys(str(ipaddress.ip_address(record[4][0])) for record in records))
            except (ValueError, TypeError, IndexError):
                raise EgressDenied() from None
        if not addresses or any(address not in self._allowed_ips for address in addresses):
            raise EgressDenied()
        self._check_current()
        # No retry across candidate IPs. A failed or uncertain dispatch stays failed.
        return await self._backend.connect_tcp(addresses[0], port, timeout=timeout,
                                               local_address=None, socket_options=socket_options)

    async def connect_unix_socket(self, *args, **kwargs):
        raise EgressDenied()


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, profile, check_current):
        # httpx does not expose a network_backend constructor argument. This
        # small pinned adapter retains its standard request/exception mapping.
        if (importlib.metadata.version('httpx') != '0.28.1'
                or importlib.metadata.version('httpcore') != '1.0.9'):
            raise EgressDenied()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            network_backend=PinnedBackend(profile, check_current), retries=0,
            max_connections=1, max_keepalive_connections=0, http1=True, http2=False,
        )


class _VerifiedStream(httpx.AsyncByteStream):
    def __init__(self, response, owner):
        self.response = response
        self.owner = owner
        self.verifier = SSEVerifier()

    async def __aiter__(self):
        try:
            async with asyncio.timeout_at(self.owner._deadline):
                async for data in self.response.aiter_raw():
                    for wire in self.verifier.feed(data):
                        yield wire
                held = self.verifier.finish()
                self.owner._check_current()
                self.owner.terminal_verified = True
        finally:
            # Release the socket before yielding the cached terminal. A parser
            # may stop immediately at stop or DONE and never request another byte.
            await self.aclose()
        for wire in held:
            yield wire

    async def aclose(self):
        await self.response.aclose()
        await self.owner.close()


class OneShotClient:
    """One admitted Chat request through the standard, controlled HTTP stack."""
    def __init__(self, profile, *, provider_key, model_id, check_current):
        mode = 'none' if provider_key is None else 'api_key'
        if (mode not in profile['auth_modes'] or (mode == 'api_key' and (
                type(provider_key) is not str or not provider_key
                or any(ord(char) <= 32 or ord(char) >= 127 for char in provider_key)))):
            raise EgressDenied()
        self.profile = dict(profile)
        self.model_id = model_id
        self._provider_key = provider_key
        self._check_current = check_current
        self._sent = False
        self.terminal_verified = False
        self.client = httpx.AsyncClient(
            transport=_PinnedTransport(profile, check_current), trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(180, connect=5),
        )

    async def close(self):
        self._provider_key = None
        await self.client.aclose()

    async def get_models(self):
        """Explicit bounded catalog read, with the identical fixed egress boundary."""
        from ai_endpoint_profiles import valid_upstream_model_id
        response = None
        try:
            self._check_current()
            if self._sent:
                raise EgressDenied()
            self._sent = True
            headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
            if self._provider_key is not None:
                headers['Authorization'] = 'Bearer ' + self._provider_key
            request = self.client.build_request('GET', self.profile['api_base'].rstrip('/') + '/models', headers=headers)
            async with asyncio.timeout(15):
                response = await self.client.send(request, stream=True, follow_redirects=False)
                response.raise_for_status()
                if (response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity')
                        or not response.headers.get('content-type', '').lower().startswith('application/json')):
                    raise TerminalInvalid()
                raw = bytearray()
                async for chunk in response.aiter_raw():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise TerminalInvalid()
                data = strict_json(bytes(raw))
                if type(data) is not dict or type(data.get('data')) is not list or data.get('error') is not None:
                    raise TerminalInvalid()
                models = []
                for row in data['data']:
                    if type(row) is dict and valid_upstream_model_id(row.get('id')) and row['id'] not in models:
                        models.append(row['id'])
                    if len(models) == 100:
                        break
                self._check_current()
                return {'models': models, 'truncated': len(data['data']) > 100 or data.get('has_more') is True}
        finally:
            if response is not None:
                await response.aclose()
            await self.close()

    async def post(self, url, *, data, stream=False, headers=None, timeout=None, logging_obj=None):
        response = None
        handoff = False
        try:
            self._check_current()
            if self._sent or url != self.profile['api_base'].rstrip('/') + '/chat/completions':
                raise EgressDenied()
            if not isinstance(data, (str, bytes)) or len(data) > MAX_BODY_BYTES or type(stream) is not bool:
                raise EgressDenied()
            payload = strict_json(data)
            if (type(payload) is not dict or payload.get('model') != self.model_id
                    or payload.get('stream', False) is not stream):
                raise EgressDenied()
            if self.profile.get('provider_id') == 'openrouter':
                # This controls upstream provider fallback too; never forward
                # an unverified provider-selection override from a caller.
                payload['provider'] = {'allow_fallbacks': False}
            request_headers = {'Content-Type': 'application/json',
                               'Accept': 'text/event-stream' if stream else 'application/json',
                               'Accept-Encoding': 'identity'}
            if self._provider_key is not None:
                request_headers['Authorization'] = 'Bearer ' + self._provider_key
            # Ignore adapter/ambient Authorization and never persist cookies.
            # All requests go to this one URL once; a bodyless/connect failure
            # cannot cause a parent LiteLLM helper to resend this client.
            self._sent = True
            self._check_current()
            self._deadline = asyncio.get_running_loop().time() + 180
            request = self.client.build_request('POST', url, headers=request_headers,
                                                content=json.dumps(payload, separators=(',', ':')).encode())
            async with asyncio.timeout(180):
                response = await self.client.send(request, stream=True, follow_redirects=False)
                # Never enter HTTPx's decompressor with an untrusted response.
                # Decoders may allocate a whole expanded chunk before any body
                # budget check can run, even with a tiny compressed wire body.
                if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                    raise TerminalInvalid()
                if stream and response.status_code == 200:
                    if not response.headers.get('content-type', '').lower().startswith('text/event-stream'):
                        raise TerminalInvalid()
                    result = httpx.Response(response.status_code, headers=response.headers,
                                             request=response.request, stream=_VerifiedStream(response, self))
                    handoff = True
                    return result
                raw = bytearray()
                async for chunk in response.aiter_raw():
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY_BYTES:
                        raise TerminalInvalid()
                result = httpx.Response(response.status_code, headers=response.headers,
                                         request=response.request, content=bytes(raw))
                result.raise_for_status()  # Includes redirects; no second request.
                verify_completion(bytes(raw))
                self.terminal_verified = True
                return result
        finally:
            if not handoff:
                if response is not None:
                    await response.aclose()
                await self.close()
