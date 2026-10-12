from __future__ import annotations

import io
import ipaddress
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request

import pytest
from django.test import override_settings

from api.services.article_fetcher import providers, safe_http


def _addrinfo(address: str, port: int):
    parsed = ipaddress.ip_address(address)
    if parsed.version == 4:
        return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (str(parsed), port))
    return (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (str(parsed), port, 0, 0))


class FakeStream:
    def __init__(self, data: bytes, *, body_read=None, max_read=None):
        self._stream = io.BytesIO(data)
        self._body_read = body_read
        self._max_read = max_read

    def readline(self, amount=-1):
        return self._stream.readline(amount)

    def read(self, amount=-1):
        return self._stream.read(amount)

    def read1(self, amount=-1):
        if self._max_read is not None:
            amount = self._max_read if amount < 0 else min(amount, self._max_read)
        if self._body_read:
            return self._body_read(amount, self._stream)
        return self._stream.read(amount)

    def tell(self):
        return self._stream.tell()

    def flush(self):
        return None

    def close(self):
        self._stream.close()


class FakeSocket:
    def __init__(self, response: bytes, *, peer_ip=None, body_read=None, max_read=None):
        self.response = response
        self.peer_ip = peer_ip
        self.body_read = body_read
        self.max_read = max_read
        self.address = None
        self.sent = bytearray()
        self.timeouts = []
        self.closed = False

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def connect(self, address):
        self.address = address

    def getpeername(self):
        peer_ip = self.peer_ip or self.address[0]
        return (peer_ip, self.address[1])

    def sendall(self, data):
        self.sent.extend(data)

    def makefile(self, mode):
        return FakeStream(self.response, body_read=self.body_read, max_read=self.max_read)

    def close(self):
        self.closed = True


class FakeNetwork:
    def __init__(self, monkeypatch, responses, *, answers=None, peer_ips=None, body_read=None, max_read=None):
        self.responses = list(responses)
        self.answers = answers or {}
        self.peer_ips = list(peer_ips or [])
        self.body_read = body_read
        self.max_read = max_read
        self.lookup_calls = []
        self.sockets = []

        def getaddrinfo(host, port, **kwargs):
            self.lookup_calls.append((host, port))
            answer = self.answers.get(host, ['93.184.216.34'])
            if isinstance(answer, BaseException):
                raise answer
            if not answer:
                return []
            return [_addrinfo(address, port) for address in answer]

        def create_socket(family, socktype, proto):
            response = self.responses.pop(0) if self.responses else b''
            peer_ip = self.peer_ips.pop(0) if self.peer_ips else None
            connection = FakeSocket(
                response,
                peer_ip=peer_ip,
                body_read=self.body_read,
                max_read=self.max_read,
            )
            self.sockets.append(connection)
            return connection

        monkeypatch.setattr(safe_http.socket, 'getaddrinfo', getaddrinfo)
        monkeypatch.setattr(safe_http.socket, 'socket', create_socket)


class FakeSSLContext:
    def __init__(self):
        self.server_names = []

    def wrap_socket(self, connection, *, server_hostname):
        self.server_names.append(server_hostname)
        return connection


def _response(status=200, headers='', body=b''):
    if isinstance(body, str):
        body = body.encode()
    return (
        f'HTTP/1.1 {status} Test\r\n'
        f'{headers}'
        '\r\n'
    ).encode() + body


def test_validate_public_url_returns_every_public_address_without_connecting(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [],
        answers={'articles.example': ['93.184.216.34', '2001:4860:4860::8888']},
    )

    target = safe_http.validate_public_url('https://articles.example/path?q=1')

    assert target.host == 'articles.example'
    assert target.port == 443
    assert target.path == '/path?q=1'
    assert len(target.addrinfos) == 2
    assert network.lookup_calls == [('articles.example', 443)]
    assert network.sockets == []


@pytest.mark.parametrize(
    'url',
    [
        'file:///etc/passwd',
        'ftp://example.test/file',
        'https://user:password@example.test/article',
        'https://example.test/\nheader',
        'https://example.test\\@attacker.test/article',
        'https://example.test:8443/article',
        'https://example.test:not-a-port/article',
        'https://example.test:/article',
        'http://localhost/article',
        'https://[fe80::1%25eth0]/article',
        'https://' + ('a' * 8_190) + '.test/',
        'http:///missing-host',
    ],
)
def test_validate_public_url_rejects_malformed_or_unsupported_urls_without_dns(monkeypatch, url):
    called = False

    def forbidden_lookup(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError('invalid URL must be rejected before DNS')

    monkeypatch.setattr(safe_http.socket, 'getaddrinfo', forbidden_lookup)

    with pytest.raises(safe_http.UnsafeURL):
        safe_http.validate_public_url(url)
    assert called is False


@pytest.mark.parametrize(
    'address',
    [
        '127.0.0.1',
        '::1',
        '169.254.1.10',
        '10.0.0.9',
        '172.16.0.3',
        '192.168.1.2',
        '0.1.2.3',
        '192.0.2.10',
        '224.0.0.1',
        '240.0.0.1',
        '::ffff:127.0.0.1',
    ],
)
def test_validate_public_url_rejects_non_global_ip_literals(monkeypatch, address):
    network = FakeNetwork(monkeypatch, [])

    with pytest.raises(safe_http.UnsafeURL, match='Private or local'):
        safe_http.validate_public_url(f'http://[{address}]/' if ':' in address else f'http://{address}/')
    assert network.lookup_calls == []
    assert network.sockets == []


@pytest.mark.parametrize('encoded', ['2130706433', '0177.0.0.1', '0x7f000001'])
def test_validate_public_url_rejects_legacy_numeric_loopback_after_resolution(monkeypatch, encoded):
    network = FakeNetwork(monkeypatch, [], answers={encoded: ['127.0.0.1']})

    with pytest.raises(safe_http.UnsafeURL, match='Private or local'):
        safe_http.validate_public_url(f'http://{encoded}/')
    assert network.lookup_calls == [(encoded, 80)]
    assert network.sockets == []


def test_validate_public_url_rejects_empty_and_mixed_public_private_dns(monkeypatch):
    empty = FakeNetwork(monkeypatch, [], answers={'empty.example': []})
    with pytest.raises(safe_http.UnsafeURL, match='resolve'):
        safe_http.safe_urlopen('https://empty.example/')

    mixed = FakeNetwork(
        monkeypatch,
        [],
        answers={'mixed.example': ['93.184.216.34', '10.1.2.3']},
    )
    with pytest.raises(safe_http.UnsafeURL, match='Private or local'):
        safe_http.safe_urlopen('https://mixed.example/')
    assert empty.sockets == mixed.sockets == []


def test_safe_urlopen_connects_to_validated_ip_uses_tls_sni_and_ignores_proxy(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [_response(headers='Content-Length: 5\r\n', body='hello')],
        answers={'articles.example': ['93.184.216.34', '2001:4860:4860::8888']},
    )
    context = FakeSSLContext()
    default_context = ssl.create_default_context()
    context.verify_mode = default_context.verify_mode
    context.check_hostname = default_context.check_hostname
    monkeypatch.setattr(safe_http.ssl, 'create_default_context', lambda: context)
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:8765')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:8765')
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:8765')

    response = safe_http.safe_urlopen(
        urllib.request.Request('https://articles.example/guide', headers={'X-Test': 'kept'}),
        timeout=30,
    )

    assert response.status == 200
    assert response.read() == b'hello'
    assert response.read() == b''
    assert network.lookup_calls == [('articles.example', 443)]
    assert network.sockets[0].address == ('93.184.216.34', 443)
    assert network.sockets[0].timeouts[0] <= safe_http.MAX_TOTAL_SECONDS
    assert context.server_names == ['articles.example']
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    request_bytes = bytes(network.sockets[0].sent)
    assert b'Host: articles.example\r\n' in request_bytes
    assert b'Accept-Encoding: identity\r\n' in request_bytes
    assert b'X-test: kept\r\n' in request_bytes
    assert network.sockets[0].closed is True


def test_safe_urlopen_pins_dns_result_when_dns_changes_after_validation(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [_response(headers='Content-Length: 2\r\n', body='ok')],
        answers={'rebind.example': ['93.184.216.34']},
    )
    original_lookup = safe_http.socket.getaddrinfo
    calls = 0

    def rebind_on_second_lookup(host, port, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            return [_addrinfo('127.0.0.1', port)]
        return original_lookup(host, port, **kwargs)

    monkeypatch.setattr(safe_http.socket, 'getaddrinfo', rebind_on_second_lookup)

    with safe_http.safe_urlopen('http://rebind.example/article') as response:
        assert response.read() == b'ok'

    assert calls == 1
    assert network.sockets[0].address == ('93.184.216.34', 80)


def test_safe_urlopen_rejects_a_peer_that_differs_from_the_selected_public_ip(monkeypatch):
    network = FakeNetwork(monkeypatch, [_response(body='unused')], peer_ips=['10.0.0.2'])

    with pytest.raises(safe_http.UnsafeURL, match='peer'):
        safe_http.safe_urlopen('http://peer.example/')

    assert network.sockets[0].sent == b''
    assert network.sockets[0].closed is True


def test_safe_urlopen_follows_relative_public_redirect_and_rechecks_each_host(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [
            _response(302, 'Location: /final\r\nContent-Length: 0\r\n'),
            _response(200, 'Content-Length: 4\r\n', 'done'),
        ],
        answers={'redirect.example': ['93.184.216.34']},
    )

    with safe_http.safe_urlopen('http://redirect.example/start') as response:
        assert response.status == 200
        assert response.geturl() == 'http://redirect.example/final'
        assert response.read() == b'done'

    assert network.lookup_calls == [('redirect.example', 80), ('redirect.example', 80)]
    assert len(network.sockets) == 2
    assert b'GET /start HTTP/1.1\r\n' in network.sockets[0].sent
    assert b'GET /final HTTP/1.1\r\n' in network.sockets[1].sent


def test_safe_urlopen_follows_absolute_public_redirect_and_drops_cross_host_credentials(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [
            _response(302, 'Location: http://final.example/article\r\nContent-Length: 0\r\n'),
            _response(200, 'Content-Length: 4\r\n', 'done'),
        ],
        answers={
            'redirect.example': ['93.184.216.34'],
            'final.example': ['8.8.8.8'],
        },
    )

    with safe_http.safe_urlopen(
        urllib.request.Request(
            'http://redirect.example/start',
            headers={'Authorization': 'Bearer test-secret', 'Cookie': 'session=test-secret'},
        ),
    ) as response:
        assert response.read() == b'done'

    assert network.lookup_calls == [('redirect.example', 80), ('final.example', 80)]
    assert [connection.address for connection in network.sockets] == [
        ('93.184.216.34', 80),
        ('8.8.8.8', 80),
    ]
    assert b'Authorization: Bearer test-secret' in network.sockets[0].sent
    assert b'Cookie: session=test-secret' in network.sockets[0].sent
    assert b'Authorization:' not in network.sockets[1].sent
    assert b'Cookie:' not in network.sockets[1].sent
    assert b'Host: final.example\r\n' in network.sockets[1].sent


def test_production_direct_providers_fetch_html_and_markdown_over_safe_transport(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [
            _response(headers='Content-Type: text/plain; charset=utf-8\r\nContent-Length: 14\r\n', body='# Readme\nBody.'),
            _response(headers='Content-Type: text/html; charset=utf-8\r\nContent-Length: 31\r\n', body='<article>Article body</article>'),
        ],
        answers={
            'raw.example': ['93.184.216.34'],
            'article.example': ['8.8.8.8'],
        },
    )
    context = FakeSSLContext()
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    monkeypatch.setattr(safe_http.ssl, 'create_default_context', lambda: context)

    with override_settings(DJANGO_ENV='production'):
        markdown = providers.GitHubReadmeProvider()._download('https://raw.example/README.md')
        html = providers.ScrapyHTTPProvider()._download('http://article.example/article')

    assert markdown == '# Readme\nBody.'
    assert html == '<article>Article body</article>'
    assert [connection.address[0] for connection in network.sockets] == ['93.184.216.34', '8.8.8.8']
    assert context.server_names == ['raw.example']


def test_safe_urlopen_rejects_private_redirect_before_connecting_to_next_hop(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [_response(302, 'Location: http://127.0.0.1/private\r\nContent-Length: 0\r\n')],
    )

    with pytest.raises(safe_http.UnsafeURL, match='Private or local'):
        safe_http.safe_urlopen('http://redirect.example/start')

    assert len(network.sockets) == 1
    assert network.sockets[0].address == ('93.184.216.34', 80)


def test_safe_urlopen_revalidates_a_second_redirect_before_connecting(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [
            _response(302, 'Location: /public-hop\r\nContent-Length: 0\r\n'),
            _response(302, 'Location: http://127.0.0.1/private\r\nContent-Length: 0\r\n'),
        ],
    )

    with pytest.raises(safe_http.UnsafeURL, match='Private or local'):
        safe_http.safe_urlopen('http://redirect.example/start')

    assert len(network.sockets) == 2
    assert [connection.address for connection in network.sockets] == [
        ('93.184.216.34', 80),
        ('93.184.216.34', 80),
    ]


def test_safe_urlopen_allows_three_redirects_and_rejects_a_fourth(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [
            _response(302, 'Location: /1\r\nContent-Length: 0\r\n'),
            _response(307, 'Location: /2\r\nContent-Length: 0\r\n'),
            _response(308, 'Location: /3\r\nContent-Length: 0\r\n'),
            _response(301, 'Location: /4\r\nContent-Length: 0\r\n'),
        ],
    )

    with pytest.raises(safe_http.UnsafeURL, match='redirect limit'):
        safe_http.safe_urlopen('http://redirect.example/start')

    assert len(network.sockets) == 4
    assert all(b'GET ' in connection.sent for connection in network.sockets)


def test_safe_urlopen_rejects_compressed_and_oversized_responses(monkeypatch):
    compressed = FakeNetwork(
        monkeypatch,
        [_response(headers='Content-Encoding: gzip\r\nContent-Length: 4\r\n', body='data')],
    )
    with pytest.raises(safe_http.UnsafeURL, match='Compressed'):
        safe_http.safe_urlopen('http://compressed.example/')

    oversized = FakeNetwork(
        monkeypatch,
        [_response(headers=f'Content-Length: {safe_http.MAX_RESPONSE_BYTES + 1}\r\n')],
    )
    with pytest.raises(safe_http.UnsafeURL, match='size limit'):
        safe_http.safe_urlopen('http://large.example/')

    streaming = FakeNetwork(
        monkeypatch,
        [_response(body=b'x' * (safe_http.MAX_RESPONSE_BYTES + 1))],
    )
    with pytest.raises(safe_http.UnsafeURL, match='size limit'):
        safe_http.safe_urlopen('http://streaming-large.example/')
    assert len(compressed.sockets) == len(oversized.sockets) == len(streaming.sockets) == 1


def test_safe_urlopen_sets_remaining_deadline_for_each_body_read(monkeypatch):
    clock = [0.0]
    response = _response(headers='Content-Length: 4\r\n', body='slow')
    header_end = response.find(b'\r\n\r\n') + 4

    def slow_read(amount, stream):
        offset = stream.tell()
        chunk = stream.read(min(amount, 1))
        if offset >= header_end:
            clock[0] += 1.1
        return chunk

    network = FakeNetwork(
        monkeypatch,
        [response],
        body_read=slow_read,
        max_read=1,
    )
    monkeypatch.setattr(safe_http, '_monotonic', lambda: clock[0])

    with pytest.raises(safe_http.UnsafeURL, match='deadline'):
        safe_http.safe_urlopen('http://slow.example/', timeout=2)

    timeouts = network.sockets[0].timeouts
    assert len(timeouts) >= 3
    assert timeouts[0] == pytest.approx(2)
    assert timeouts[-1] < timeouts[0]


def test_safe_urlopen_dns_timeout_returns_while_resolver_is_still_blocked(monkeypatch):
    network = FakeNetwork(monkeypatch, [_response(body='unused')])
    resolver_started = threading.Event()
    resolver_release = threading.Event()
    resolver_finished = threading.Event()
    caller_returned = threading.Event()
    result = {}

    def blocked_lookup(host, port, **kwargs):
        resolver_started.set()
        resolver_release.wait(timeout=0.5)
        resolver_finished.set()
        return [_addrinfo('93.184.216.34', port)]

    monkeypatch.setattr(safe_http.socket, 'getaddrinfo', blocked_lookup)

    def call_urlopen():
        try:
            safe_http.safe_urlopen('http://slow-dns.example/', timeout=0.01)
        except Exception as exc:
            result['error'] = exc
        finally:
            caller_returned.set()

    caller = threading.Thread(target=call_urlopen)
    caller.start()
    try:
        assert resolver_started.wait(timeout=0.5)
        assert caller_returned.wait(timeout=0.2), 'caller waited for the blocked resolver'
        assert isinstance(result.get('error'), safe_http.UnsafeURL)
        assert 'deadline' in str(result['error']).lower()
        assert not resolver_finished.is_set()
        assert network.sockets == []
    finally:
        resolver_release.set()
        caller.join(timeout=0.5)

    assert not caller.is_alive()
    assert resolver_finished.wait(timeout=0.5)
    assert safe_http._DNS_SLOTS.acquire(timeout=0.5)
    safe_http._DNS_SLOTS.release()


def test_safe_urlopen_dns_pool_rejects_third_pending_lookup_and_recovers(monkeypatch):
    network = FakeNetwork(monkeypatch, [_response(body='ok')])
    resolver_release = threading.Event()
    both_resolvers_started = threading.Event()
    resolver_lock = threading.Lock()
    resolver_count = 0
    callers = []
    caller_errors = []

    def blocked_lookup(host, port, **kwargs):
        nonlocal resolver_count
        with resolver_lock:
            resolver_count += 1
            if resolver_count == 2:
                both_resolvers_started.set()
        resolver_release.wait(timeout=0.8)
        return [_addrinfo('93.184.216.34', port)]

    monkeypatch.setattr(safe_http.socket, 'getaddrinfo', blocked_lookup)

    def invoke_first_two():
        try:
            safe_http.safe_urlopen('http://pending-dns.example/', timeout=0.04)
        except Exception as exc:
            caller_errors.append(exc)

    for _ in range(2):
        caller = threading.Thread(target=invoke_first_two)
        callers.append(caller)
        caller.start()

    try:
        assert both_resolvers_started.wait(timeout=0.5)
        for caller in callers:
            caller.join(timeout=0.5)
        assert all(not caller.is_alive() for caller in callers)
        assert len(caller_errors) == 2
        assert all('deadline' in str(exc).lower() for exc in caller_errors)

        started = time.monotonic()
        with pytest.raises(safe_http.UnsafeURL, match='resolver busy'):
            safe_http.safe_urlopen('http://third-dns.example/', timeout=0.5)
        assert time.monotonic() - started < 0.1

    finally:
        resolver_release.set()
        for caller in callers:
            caller.join(timeout=0.5)

    assert safe_http._DNS_SLOTS.acquire(timeout=0.5)
    assert safe_http._DNS_SLOTS.acquire(timeout=0.5)
    safe_http._DNS_SLOTS.release()
    safe_http._DNS_SLOTS.release()

    with safe_http.safe_urlopen('http://recovered-dns.example/', timeout=0.5) as response:
        assert response.read() == b'ok'
    assert len(network.sockets) == 1


def test_safe_urlopen_deadline_covers_slow_status_and_headers(monkeypatch):
    clock = [0.0]
    response = _response(headers='X-Slow: abcdef\r\nContent-Length: 2\r\n', body='ok')
    header_end = response.find(b'\r\n\r\n') + 4
    header_offsets = []

    def slow_header_read(amount, stream):
        offset = stream.tell()
        chunk = stream.read(min(amount, 1))
        if offset < header_end:
            header_offsets.append(offset)
            clock[0] += 0.02
        return chunk

    network = FakeNetwork(
        monkeypatch,
        [response],
        body_read=slow_header_read,
        max_read=1,
    )
    monkeypatch.setattr(safe_http, '_monotonic', lambda: clock[0])

    with pytest.raises(safe_http.UnsafeURL, match='deadline'):
        safe_http.safe_urlopen('http://slow-headers.example/', timeout=0.25)

    assert header_offsets
    assert max(header_offsets) < header_end
    assert network.sockets[0].closed is True


def test_safe_urlopen_wire_budget_counts_redirect_hops(monkeypatch):
    first_response = _response(302, 'Location: /next\r\nContent-Length: 1\r\n', 'x')
    second_response = _response(200, 'Content-Length: 1\r\n', 'y')
    monkeypatch.setattr(safe_http, 'MAX_WIRE_BYTES', len(first_response))
    network = FakeNetwork(monkeypatch, [first_response, second_response])

    with pytest.raises(safe_http.UnsafeURL, match='size limit'):
        safe_http.safe_urlopen('http://wire-budget.example/')

    assert len(network.sockets) == 2
    assert all(connection.closed for connection in network.sockets)


@pytest.mark.parametrize(
    'fetch_request',
    [
        urllib.request.Request('http://method.example/', method='POST'),
        urllib.request.Request('http://method.example/', method='PUT'),
        urllib.request.Request('http://method.example/', data=b'payload'),
        urllib.request.Request('http://method.example/', data=b'payload', method='GET'),
    ],
)
def test_safe_urlopen_rejects_non_get_or_body_before_dns(monkeypatch, fetch_request):
    network = FakeNetwork(monkeypatch, [])

    with pytest.raises(safe_http.UnsafeURL, match='Only GET'):
        safe_http.safe_urlopen(fetch_request)

    assert network.lookup_calls == []
    assert network.sockets == []


def test_safe_urlopen_http_error_remains_urllib_compatible_without_echoing_query(monkeypatch):
    network = FakeNetwork(
        monkeypatch,
        [_response(404, 'Content-Length: 3\r\n', 'bad')],
    )

    with pytest.raises(urllib.error.HTTPError) as raised:
        safe_http.safe_urlopen('http://error.example/path?api_key=secret')

    assert raised.value.code == 404
    assert str(raised.value) == 'HTTP 404'
    assert 'secret' not in str(raised.value)
    assert raised.value.read() == b'bad'
    assert network.sockets[0].address == ('93.184.216.34', 80)
