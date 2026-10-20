"""Wire terminals and actual-connect admission for administrator endpoints."""
import asyncio
import gzip
import json
import socket
import ssl
import subprocess
import tempfile
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import AsyncMock, patch


def endpoint(**changes):
    return dict(api_base='http://127.0.0.1:11434/v1', allowed_ips=['127.0.0.1'],
                route_prefix='newshub/office-v1-policy', policy_digest='policy', enabled=True) | changes


def frame(reason=None, content='hello'):
    return ('data: ' + json.dumps({'choices': [{'index': 0, 'delta': {'content': content},
                                               'finish_reason': reason}]}) + '\n\n').encode()


class RawCompletionTests(unittest.TestCase):
    def test_raw_nonstream_cannot_invent_missing_or_duplicate_finish(self):
        from trusted_transport import TerminalInvalid, verify_completion
        for raw in (
            b'{"choices":[{"message":{"content":"partial"}}]}',
            b'{"choices":[{"message":{},"finish_reason":null,"finish_reason":"stop"}]}',
            b'{"error":{},"choices":[{"message":{},"finish_reason":"stop"}]}',
            b'{"choices":[{"message":{},"finish_reason":"stop"}],"extra":NaN}',
            b'{"choices":[{"index":0,"message":{"content":"private text"},"finish_reason":"stop"}]}',
            b'{"choices":[{"index":0,"message":{"role":"assistant","content":{}},"finish_reason":"stop"}]}',
            b'{"choices":[{"index":0,"message":{"role":"assistant","content":"partial","refusal":"denied"},"finish_reason":"stop"}]}',
        ):
            with self.subTest(raw=raw), self.assertRaises(TerminalInvalid):
                verify_completion(raw)
        self.assertEqual(verify_completion(b'{"choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}'), 'stop')
        self.assertEqual(verify_completion(b'{"choices":[{"index":0,"message":{"role":"assistant","tool_calls":[{"id":"call_1","type":"function","function":{"name":"lookup","arguments":"{}"}}]},"finish_reason":"tool_calls"}]}'), 'tool_calls')

    def test_new_stream_holds_stop_until_done_and_clean_body_end(self):
        from trusted_transport import SSEVerifier
        verifier = SSEVerifier()
        self.assertEqual(verifier.feed(frame()), [frame()])
        self.assertEqual(verifier.feed(frame('stop', '')), [])
        self.assertEqual(verifier.feed(b'data: [DONE]\n\n'), [])
        self.assertFalse(verifier.verified)
        self.assertEqual(verifier.finish(), [frame('stop', ''), b'data: [DONE]\n\n'])
        self.assertTrue(verifier.verified)

    def test_split_utf8_and_crlf_wire_is_preserved(self):
        from trusted_transport import SSEVerifier
        raw = frame(content='中文').replace(b'\n', b'\r\n')
        verifier = SSEVerifier()
        released = []
        for value in raw:
            released.extend(verifier.feed(bytes([value])))
        self.assertEqual(released, [raw])

    def test_no_terminal_can_escape_malformed_or_incomplete_stream(self):
        from trusted_transport import SSEVerifier, TerminalInvalid
        cases = (
            frame(), frame() + b'data: [DONE]\n\n', frame() + frame('stop', ''),
            frame('length'), frame('content_filter'), frame('tool_calls'),
            frame('stop', '') + frame('stop', '') + b'data: [DONE]\n\n',
            frame('stop', '') + b'data: [DONE]\n\n' + frame(),
            frame('stop', '') + b'data: {"error":{"message":"failure"}}\n\n',
            b'data: {"choices":[{"index":0,"delta":{},"finish_reason":null,"finish_reason":"stop"}]}\n\n',
            frame('stop', '') + b'data: [DONE] \n\n',
            b'data: {"choices":', b'data: \xff\n\n',
        )
        for raw in cases:
            with self.subTest(raw=raw):
                verifier = SSEVerifier()
                released = []
                with self.assertRaises(TerminalInvalid):
                    released.extend(verifier.feed(raw))
                    released.extend(verifier.finish())
                self.assertFalse(verifier.verified)
                self.assertFalse(any(b'"stop"' in value or b'[DONE]' in value for value in released))

    def test_usage_is_bounded_and_duplicate_done_is_invalid(self):
        from trusted_transport import SSEVerifier, TerminalInvalid
        usage = b'data: {"choices":[],"usage":{"completion_tokens":1}}\n\n'
        verifier = SSEVerifier()
        verifier.feed(frame() + frame('stop', '') + usage + b'data: [DONE]\n\n')
        self.assertEqual(len(verifier.finish()), 3)
        for tail in (usage + usage + b'data: [DONE]\n\n', b'data: [DONE]\n\ndata: [DONE]\n\n'):
            with self.subTest(tail=tail), self.assertRaises(TerminalInvalid):
                invalid = SSEVerifier()
                invalid.feed(frame('stop', '') + tail)
                invalid.finish()


class PinnedNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_dns_is_resolved_once_then_actual_connect_receives_numeric_ip(self):
        from trusted_transport import PinnedBackend
        profile = endpoint(api_base='https://inference.example.com/v1', allowed_ips=['8.8.8.8'])
        backend = PinnedBackend(profile, lambda: None)
        backend._backend.connect_tcp = AsyncMock(return_value='socket')
        loop = asyncio.get_running_loop()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=records)) as resolve:
            result = await backend.connect_tcp('inference.example.com', 443, timeout=2)
        self.assertEqual(result, 'socket')
        self.assertEqual(resolve.await_count, 1)
        self.assertEqual(backend._backend.connect_tcp.await_args.args, ('8.8.8.8', 443))

    async def test_bad_dns_wrong_port_and_policy_revocation_never_connect(self):
        from trusted_transport import PinnedBackend, EgressDenied
        profile = endpoint(api_base='https://inference.example.com/v1', allowed_ips=['8.8.8.8'])
        for addresses in (['127.0.0.1'], ['169.254.169.254'], ['10.0.0.1'], ['8.8.8.8', '127.0.0.1'], ['::ffff:8.8.8.8']):
            backend = PinnedBackend(profile, lambda: None)
            backend._backend.connect_tcp = AsyncMock()
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)) for address in addresses]
            with self.subTest(addresses=addresses), patch.object(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=records)):
                with self.assertRaises(EgressDenied):
                    await backend.connect_tcp('inference.example.com', 443)
                self.assertEqual(backend._backend.connect_tcp.await_count, 0)
        backend = PinnedBackend(profile, lambda: None)
        with self.assertRaises(EgressDenied):
            await backend.connect_tcp('inference.example.com', 80)
        with self.assertRaises(EgressDenied):
            await backend.connect_tcp('other.example.com', 443)

    async def test_failed_connect_is_not_retried_with_another_address(self):
        from trusted_transport import PinnedBackend
        profile = endpoint(api_base='https://inference.example.com/v1', allowed_ips=['8.8.8.8', '8.8.4.4'])
        backend = PinnedBackend(profile, lambda: None)
        backend._backend.connect_tcp = AsyncMock(side_effect=OSError('synthetic failure'))
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)) for address in profile['allowed_ips']]
        with patch.object(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=records)):
            with self.assertRaises(OSError):
                await backend.connect_tcp('inference.example.com', 443)
        self.assertEqual(backend._backend.connect_tcp.await_count, 1)


class OneShotWireTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        records = self.requests
        self.producer_closed = closed = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                records.append({'path': self.path, 'body': body, 'auth': self.headers.get('Authorization'),
                                'accept_encoding': self.headers.get('Accept-Encoding')})
                if body['model'] == 'cancel':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    try:
                        for _ in range(300):
                            self.wfile.write(frame())
                            self.wfile.flush()
                            time.sleep(0.01)
                    except (BrokenPipeError, ConnectionResetError):
                        closed.set()
                    return
                if body['model'] == 'redirect':
                    self.send_response(307)
                    self.send_header('Location', '/v1/redirect-target')
                    self.end_headers()
                    return
                if body['model'] == 'truncated':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', '200')
                    self.end_headers()
                    self.wfile.write(b'{')
                    return
                if body.get('stream'):
                    wire = frame() + frame('stop', '')
                    if body['model'] != 'eof':
                        wire += b'data: [DONE]\n\n'
                    content_type = 'text/event-stream'
                else:
                    wire = json.dumps({'id': 'chatcmpl-synthetic', 'created': 1, 'object': 'chat.completion',
                                       'model': body['model'], 'choices': [{'index': 0,
                                       'message': {'role': 'assistant', 'content': 'synthetic'},
                                       'finish_reason': 'stop'}]}).encode()
                    if body['model'] == 'malformed':
                        wire = b'{"choices":[{"index":0,"message":{"content":"private-body-sentinel"},"finish_reason":"stop"}]}'
                    content_type = 'application/json'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                if body['model'] == 'compressed':
                    wire = gzip.compress(wire)
                    self.send_header('Content-Encoding', 'gzip')
                self.send_header('Content-Length', str(len(wire)))
                self.end_headers()
                self.wfile.write(wire)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.profile = endpoint(api_base=f'http://127.0.0.1:{self.server.server_port}/v1',
                                auth_modes=['api_key', 'none'])

    async def asyncTearDown(self):
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join(timeout=3)

    async def invoke(self, model='org/model:tag', key=None, stream=False, **changes):
        from trusted_transport import OneShotClient
        client = OneShotClient(self.profile, provider_key=key, model_id=model, check_current=lambda: None)
        response = await client.post(self.profile['api_base'] + '/chat/completions',
                                     data=json.dumps({'model': model, 'stream': stream, **changes}), stream=stream,
                                     headers={'Authorization': 'Bearer ambient-secret-must-not-be-forwarded'})
        return client, response

    async def test_none_and_key_use_exact_request_auth_and_preserve_model(self):
        for key in (None, 'synthetic-owner-key'):
            with patch.dict('os.environ', {'HTTP_PROXY': 'http://127.0.0.1:1', 'OPENAI_API_KEY': 'ambient-secret'}):
                client, response = await self.invoke(key=key)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(client.client.is_closed)
        self.assertEqual([request['auth'] for request in self.requests], [None, 'Bearer synthetic-owner-key'])
        self.assertEqual([request['body']['model'] for request in self.requests], ['org/model:tag', 'org/model:tag'])

    async def test_redirect_and_truncated_body_each_send_exactly_once(self):
        from trusted_transport import OneShotClient
        for model in ('redirect', 'truncated'):
            client = OneShotClient(self.profile, provider_key=None, model_id=model, check_current=lambda: None)
            with self.subTest(model=model), self.assertRaises(Exception):
                await client.post(self.profile['api_base'] + '/chat/completions',
                                  data=json.dumps({'model': model}), stream=False)
            self.assertTrue(client.client.is_closed)
        self.assertEqual([request['body']['model'] for request in self.requests], ['redirect', 'truncated'])

    async def test_complete_stream_has_proof_but_stop_without_done_never_releases_terminal(self):
        from trusted_transport import OneShotClient, TerminalInvalid
        client, response = await self.invoke(stream=True)
        wire = b''.join([chunk async for chunk in response.aiter_bytes()])
        self.assertTrue(client.terminal_verified and client.client.is_closed)
        self.assertIn(b'[DONE]', wire)
        failed = OneShotClient(self.profile, provider_key=None, model_id='eof', check_current=lambda: None)
        response = await failed.post(self.profile['api_base'] + '/chat/completions',
                                     data=json.dumps({'model': 'eof', 'stream': True}), stream=True)
        released = []
        with self.assertRaises(TerminalInvalid):
            async for chunk in response.aiter_bytes():
                released.append(chunk)
        self.assertFalse(failed.terminal_verified)
        self.assertTrue(failed.client.is_closed)
        self.assertNotIn(b'"stop"', b''.join(released))

    async def test_mismatch_and_revocation_are_denied_before_any_socket_send(self):
        from trusted_transport import OneShotClient, EgressDenied
        def revoked():
            raise EgressDenied()
        for url, model, check in (
            ('http://127.0.0.1:1/v1/chat/completions', 'model', lambda: None),
            (self.profile['api_base'] + '/chat/completions', 'other-model', lambda: None),
            (self.profile['api_base'] + '/chat/completions', 'model', revoked),
        ):
            client = OneShotClient(self.profile, provider_key=None, model_id='model', check_current=check)
            with self.subTest(url=url, model=model), self.assertRaises(EgressDenied):
                await client.post(url, data=json.dumps({'model': model}), stream=False)
            self.assertTrue(client.client.is_closed)
        self.assertEqual(self.requests, [])

    async def test_untrusted_compression_is_rejected_before_decompression(self):
        from trusted_transport import OneShotClient, TerminalInvalid
        for stream in (False, True):
            client = OneShotClient(self.profile, provider_key=None, model_id='compressed', check_current=lambda: None)
            with self.subTest(stream=stream), self.assertRaises(TerminalInvalid):
                await client.post(self.profile['api_base'] + '/chat/completions',
                                  data=json.dumps({'model': 'compressed', 'stream': stream}), stream=stream)
            self.assertTrue(client.client.is_closed)
        self.assertEqual([request['accept_encoding'] for request in self.requests], ['identity', 'identity'])

    async def test_cancel_closes_actual_producer_without_terminal(self):
        client, response = await self.invoke(model='cancel', stream=True)
        iterator = response.aiter_bytes()
        first = await anext(iterator)
        self.assertIn(b'hello', first)
        await response.aclose()
        await iterator.aclose()
        self.assertTrue(await asyncio.to_thread(self.producer_closed.wait, 2))
        self.assertTrue(client.client.is_closed)
        self.assertFalse(client.terminal_verified)
        self.assertEqual(len(self.requests), 1)

    async def test_deadline_closes_slow_producer_without_retry_or_terminal(self):
        client, response = await self.invoke(model='cancel', stream=True)
        client._deadline = asyncio.get_running_loop().time() + 0.03
        released = []
        with self.assertRaises(TimeoutError):
            async for chunk in response.aiter_bytes():
                released.append(chunk)
        self.assertTrue(await asyncio.to_thread(self.producer_closed.wait, 2))
        self.assertTrue(client.client.is_closed)
        self.assertFalse(client.terminal_verified)
        self.assertNotIn(b'[DONE]', b''.join(released))
        self.assertEqual(len(self.requests), 1)

    async def test_ip_pin_preserves_tls_trust_sni_and_hostname_verification(self):
        import httpx
        from trusted_transport import OneShotClient
        with tempfile.TemporaryDirectory() as directory:
            cert, key = (Path(directory) / name for name in ('cert.pem', 'key.pem'))
            generated = await asyncio.to_thread(subprocess.run, [
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-keyout', str(key), '-out', str(cert), '-subj', '/CN=trusted.example.test',
                '-addext', 'subjectAltName=DNS:trusted.example.test',
            ], capture_output=True)
            self.assertEqual(generated.returncode, 0)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            names = []
            context.set_servername_callback(lambda _socket, name, _context: names.append(name))
            await asyncio.to_thread(self.server.shutdown)
            self.thread.join(timeout=3)
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            port = self.server.server_port
            profile = self.profile | {'api_base': f'https://trusted.example.test:{port}/v1'}
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
            original_context = httpx.create_ssl_context
            with patch.object(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=records)):
                # The ordinary transport rejects the untrusted fixture CA.
                client = OneShotClient(profile, provider_key=None, model_id='model', check_current=lambda: None)
                with self.assertRaises(httpx.ConnectError):
                    await client.post(profile['api_base'] + '/chat/completions', data='{"model":"model"}')
                self.assertEqual(self.requests, [])
                def fixture_trust(**kwargs):
                    self.assertIs(kwargs['trust_env'], False)
                    return original_context(verify=ssl.create_default_context(cafile=str(cert)), trust_env=False)
                with patch('httpx.create_ssl_context', fixture_trust):
                    client = OneShotClient(profile, provider_key=None, model_id='model', check_current=lambda: None)
                    await client.post(profile['api_base'] + '/chat/completions', data='{"model":"model"}')
                    self.assertTrue(client.terminal_verified)
                    self.assertEqual(len(self.requests), 1)
                    mismatch = profile | {'api_base': f'https://other.example.test:{port}/v1'}
                    client = OneShotClient(mismatch, provider_key=None, model_id='model', check_current=lambda: None)
                    with self.assertRaises(httpx.ConnectError):
                        await client.post(mismatch['api_base'] + '/chat/completions', data='{"model":"model"}')
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(names, ['trusted.example.test', 'trusted.example.test', 'other.example.test'])
