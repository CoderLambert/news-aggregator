from __future__ import annotations

import http.client
import ipaddress
import io
import math
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from email.message import Message
from typing import Any
from urllib.parse import urljoin, urlsplit

MAX_URL_LENGTH = 8_192
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_WIRE_BYTES = MAX_RESPONSE_BYTES + MAX_HEADER_BYTES
MAX_REDIRECTS = 3
MAX_TOTAL_SECONDS = 15.0
_READ_CHUNK_BYTES = 64 * 1024
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix='safe-http-dns')
_DNS_SLOTS = threading.BoundedSemaphore(2)

AddrInfo = tuple[int, int, int, str, tuple[Any, ...]]


class UnsafeURL(ValueError):
    """A URL or resolved address did not meet the public-fetch policy."""


class SafeHTTPStatusError(urllib.error.HTTPError):
    """HTTPError-compatible status failure without reflecting request secrets."""

    def __init__(self, code: int, headers: Message, body: bytes):
        super().__init__('[redacted]', code, 'HTTP error', headers, io.BytesIO(body))

    def __str__(self) -> str:
        return f'HTTP {self.code}'


@dataclass(frozen=True)
class PublicURL:
    url: str
    scheme: str
    host: str
    port: int
    path: str
    host_header: str
    addrinfos: tuple[AddrInfo, ...]


class CachedResponse:
    """Small urllib-shaped response whose body was already read safely."""

    def __init__(self, url: str, status: int, headers: Message, body: bytes):
        self.url = url
        self.status = status
        self.code = status
        self.headers = headers
        self._body = body
        self._offset = 0
        self._closed = False

    def read(self, amount: int | None = None) -> bytes:
        if self._closed:
            return b''
        if amount is None or amount < 0:
            amount = len(self._body) - self._offset
        end = min(len(self._body), self._offset + amount)
        result = self._body[self._offset:end]
        self._offset = end
        return result

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def info(self) -> Message:
        return self.headers

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> CachedResponse:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False


def _failure(message: str) -> UnsafeURL:
    return UnsafeURL(message)


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    normalized = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    checked = normalized or address
    return checked.is_global and not checked.is_multicast


def _monotonic() -> float:
    return time.monotonic()


def _resolve_addrinfos(host: str, port: int, timeout: float) -> list[AddrInfo]:
    if not math.isfinite(timeout) or timeout <= 0:
        raise _failure('Safe HTTP request deadline exceeded')
    if not _DNS_SLOTS.acquire(blocking=False):
        raise _failure('Public DNS resolver busy')
    try:
        future = _DNS_EXECUTOR.submit(
            socket.getaddrinfo,
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except RuntimeError:
        _DNS_SLOTS.release()
        raise _failure('Public DNS resolver busy') from None

    future.add_done_callback(lambda _completed: _DNS_SLOTS.release())
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        raise _failure('Public DNS resolution deadline exceeded') from None
    except Exception:
        raise _failure('Unable to resolve public URL host') from None


def validate_public_url(url: str, timeout: float = MAX_TOTAL_SECONDS) -> PublicURL:
    """Parse a public HTTP(S) target and validate every resolver result.

    This function performs DNS resolution only. It never opens a connection or
    issues an HTTP request; callers must connect using the returned addrinfos.
    """
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise _failure('Invalid URL')
    if any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in url):
        raise _failure('Invalid URL')
    if '\\' in url:
        raise _failure('Invalid URL')

    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in {'http', 'https'}:
            raise _failure('Only http/https URLs are supported')
        if not parsed.netloc or '@' in parsed.netloc:
            raise _failure('URL credentials are not allowed')
        if parsed.netloc.endswith(':'):
            raise _failure('Invalid URL port')
        host = parsed.hostname
        port = parsed.port
    except UnsafeURL:
        raise
    except ValueError:
        raise _failure('Invalid URL') from None

    if not host or '%' in host:
        raise _failure('Invalid URL host')
    if host.lower().rstrip('.') == 'localhost':
        raise _failure('Private or local URLs are not allowed')
    effective_port = port if port is not None else (443 if scheme == 'https' else 80)

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _is_public_ip(literal):
        raise _failure('Private or local URLs are not allowed')

    if effective_port not in {80, 443}:
        raise _failure('Only ports 80 and 443 are supported')

    raw_addrinfos = _resolve_addrinfos(host, effective_port, timeout)
    if not raw_addrinfos:
        raise _failure('Unable to resolve public URL host')

    validated_addrinfos: list[AddrInfo] = []
    for raw_info in raw_addrinfos:
        try:
            family, socktype, proto, canonname, sockaddr = raw_info
            if family not in {socket.AF_INET, socket.AF_INET6} or socktype != socket.SOCK_STREAM:
                raise ValueError
            if not sockaddr or len(sockaddr) < 2 or sockaddr[1] != effective_port:
                raise ValueError
            if family == socket.AF_INET6 and len(sockaddr) >= 4 and sockaddr[3] != 0:
                raise ValueError
            resolved_ip = ipaddress.ip_address(sockaddr[0])
        except (TypeError, ValueError, IndexError):
            raise _failure('Unable to validate resolved URL address') from None
        if not _is_public_ip(resolved_ip):
            raise _failure('Private or local URLs are not allowed')
        validated_addrinfos.append((family, socktype, proto, canonname, tuple(sockaddr)))

    if not validated_addrinfos:
        raise _failure('Unable to resolve public URL host')

    path = parsed.path or '/'
    if parsed.query:
        path = f'{path}?{parsed.query}'
    return PublicURL(
        url=url,
        scheme=scheme,
        host=host,
        port=effective_port,
        path=path,
        host_header=parsed.netloc,
        addrinfos=tuple(validated_addrinfos),
    )


def _remaining(deadline: float) -> float:
    remaining = deadline - _monotonic()
    if remaining <= 0:
        raise _failure('Safe HTTP request deadline exceeded')
    return remaining


def _deadline(timeout: float | None) -> float:
    if timeout is None:
        limit = MAX_TOTAL_SECONDS
    else:
        try:
            requested = float(timeout)
        except (TypeError, ValueError, OverflowError):
            raise _failure('Invalid HTTP timeout') from None
        if not math.isfinite(requested) or requested <= 0:
            raise _failure('Invalid HTTP timeout')
        limit = min(requested, MAX_TOTAL_SECONDS)
    return _monotonic() + limit


def _connect_pinned(target: PublicURL, deadline: float) -> socket.socket:
    for family, socktype, proto, _canonname, sockaddr in target.addrinfos:
        connection: socket.socket | None = None
        try:
            connection = socket.socket(family, socktype, proto)
            connection.settimeout(_remaining(deadline))
            connection.connect(sockaddr)
            peer = connection.getpeername()
            peer_ip = ipaddress.ip_address(peer[0])
            selected_ip = ipaddress.ip_address(sockaddr[0])
            if peer_ip != selected_ip:
                connection.close()
                raise _failure('Connected peer did not match validated address')
            return connection
        except UnsafeURL:
            raise
        except (OSError, ValueError, IndexError):
            if connection is not None:
                connection.close()
    raise _failure('Unable to connect to validated public address')


class _WireBudget:
    def __init__(self) -> None:
        self.consumed = 0

    @property
    def remaining(self) -> int:
        return MAX_WIRE_BYTES - self.consumed

    def consume(self, amount: int) -> None:
        self.consumed += amount
        if self.consumed > MAX_WIRE_BYTES:
            raise _failure('HTTP response exceeds size limit')


class _DeadlineFile:
    """Buffered-reader adapter that rechecks the total deadline on every read."""

    def __init__(self, source: Any, connection: Any, deadline: float, budget: _WireBudget):
        self._source = source
        self._connection = connection
        self._deadline = deadline
        self._budget = budget
        self._buffer = bytearray()
        self._eof = False
        self._closed = False

    def _read_source(self) -> bytes:
        if self._eof:
            return b''
        if self._budget.remaining <= 0:
            raise _failure('HTTP response exceeds size limit')
        self._connection.settimeout(_remaining(self._deadline))
        chunk = self._source.read1(min(_READ_CHUNK_BYTES, self._budget.remaining))
        _remaining(self._deadline)
        if not chunk:
            self._eof = True
            return b''
        self._budget.consume(len(chunk))
        return bytes(chunk)

    def _fill(self, amount: int) -> None:
        while len(self._buffer) < amount and not self._eof:
            chunk = self._read_source()
            if not chunk:
                break
            self._buffer.extend(chunk)

    def _take(self, amount: int) -> bytes:
        result = bytes(self._buffer[:amount])
        del self._buffer[:amount]
        _remaining(self._deadline)
        return result

    def readable(self) -> bool:
        return not self._closed

    @property
    def closed(self) -> bool:
        return self._closed

    def read1(self, amount: int = -1) -> bytes:
        if self._closed:
            raise ValueError('I/O operation on closed response')
        _remaining(self._deadline)
        if amount == 0:
            return b''
        if not self._buffer and not self._eof:
            self._buffer.extend(self._read_source())
        count = len(self._buffer) if amount is None or amount < 0 else min(amount, len(self._buffer))
        return self._take(count)

    def read(self, amount: int = -1) -> bytes:
        if self._closed:
            raise ValueError('I/O operation on closed response')
        _remaining(self._deadline)
        if amount is None or amount < 0:
            while not self._eof:
                chunk = self._read_source()
                if chunk:
                    self._buffer.extend(chunk)
            return self._take(len(self._buffer))
        if amount == 0:
            return b''
        self._fill(amount)
        return self._take(min(amount, len(self._buffer)))

    def readline(self, amount: int = -1) -> bytes:
        if self._closed:
            raise ValueError('I/O operation on closed response')
        _remaining(self._deadline)
        if amount == 0:
            return b''
        while True:
            newline = self._buffer.find(b'\n')
            if newline >= 0 and (amount is None or amount < 0 or newline + 1 <= amount):
                return self._take(newline + 1)
            if amount is not None and amount >= 0 and len(self._buffer) >= amount:
                return self._take(amount)
            if self._eof:
                return self._take(len(self._buffer))
            chunk = self._read_source()
            if chunk:
                self._buffer.extend(chunk)

    def flush(self) -> None:
        flush = getattr(self._source, 'flush', None)
        if flush is not None:
            flush()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._source.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._source, name)


class _SocketFacade:
    """Socket adapter that gives HTTPResponse a deadline-aware file object."""

    def __init__(self, connection: Any, deadline: float, budget: _WireBudget):
        self._connection = connection
        self._deadline = deadline
        self._budget = budget
        self._closed = False

    def settimeout(self, _timeout: float | None) -> None:
        self._connection.settimeout(_remaining(self._deadline))

    def sendall(self, data: bytes) -> None:
        self._connection.settimeout(_remaining(self._deadline))
        self._connection.sendall(data)
        _remaining(self._deadline)

    def makefile(self, mode: str = 'rb') -> _DeadlineFile:
        if 'r' not in mode or 'b' not in mode:
            raise ValueError('Safe HTTP only supports binary response reads')
        return _DeadlineFile(
            self._connection.makefile(mode),
            self,
            self._deadline,
            self._budget,
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _request_headers(request: urllib.request.Request, target: PublicURL) -> dict[str, str]:
    items = list(request.header_items())
    unredirected = getattr(request, 'unredirected_hdrs', {})
    items.extend(unredirected.items())
    headers: dict[str, str] = {}
    blocked = {
        'accept-encoding',
        'connection',
        'content-length',
        'host',
        'proxy-authorization',
        'proxy-connection',
        'transfer-encoding',
    }
    for name, value in items:
        lower_name = str(name).lower()
        if lower_name in blocked:
            continue
        headers[str(name)] = str(value)
    headers['Host'] = target.host_header
    headers['Accept-Encoding'] = 'identity'
    headers['Connection'] = 'close'
    return headers


def _read_body(response: http.client.HTTPResponse, connection: Any, deadline: float) -> bytes:
    headers = response.headers
    encodings = headers.get_all('Content-Encoding', [])
    if any(token.strip().lower() not in {'', 'identity'} for value in encodings for token in value.split(',')):
        raise _failure('Compressed HTTP responses are not supported')

    lengths = headers.get_all('Content-Length', [])
    for raw_length in lengths:
        try:
            length = int(raw_length.strip())
        except (TypeError, ValueError):
            raise _failure('Invalid HTTP response length') from None
        if length < 0 or length > MAX_RESPONSE_BYTES:
            raise _failure('HTTP response exceeds size limit')

    body = bytearray()
    read_chunk = getattr(response, 'read1', response.read)
    while True:
        remaining_capacity = MAX_RESPONSE_BYTES + 1 - len(body)
        if remaining_capacity <= 0:
            raise _failure('HTTP response exceeds size limit')
        connection.settimeout(_remaining(deadline))
        try:
            chunk = read_chunk(min(64 * 1024, remaining_capacity))
        except (OSError, http.client.HTTPException):
            raise _failure('Safe HTTP response read failed') from None
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise _failure('HTTP response exceeds size limit')
    return bytes(body)


def _fetch_one(
    request: urllib.request.Request,
    target: PublicURL,
    deadline: float,
    drop_credentials: bool,
    wire_budget: _WireBudget,
) -> tuple[int, Message, bytes]:
    connection = _connect_pinned(target, deadline)
    transport: _SocketFacade | None = None
    try:
        if target.scheme == 'https':
            connection.settimeout(_remaining(deadline))
            try:
                connection = ssl.create_default_context().wrap_socket(connection, server_hostname=target.host)
            except (OSError, ssl.SSLError):
                raise _failure('Safe HTTPS connection failed') from None

        transport = _SocketFacade(connection, deadline, wire_budget)
        http_connection = http.client.HTTPConnection(target.host, target.port, timeout=_remaining(deadline))
        http_connection.sock = transport
        http_connection.putrequest(request.get_method(), target.path, skip_host=True, skip_accept_encoding=True)
        headers = _request_headers(request, target)
        if drop_credentials:
            headers = {
                name: value
                for name, value in headers.items()
                if name.lower() not in {'authorization', 'cookie', 'www-authenticate'}
            }
            headers['Host'] = target.host_header
            headers['Accept-Encoding'] = 'identity'
            headers['Connection'] = 'close'
        for name, value in headers.items():
            http_connection.putheader(name, value)
        request_body = request.data
        if request_body is not None and not isinstance(request_body, bytes):
            request_body = bytes(request_body)
        transport.settimeout(_remaining(deadline))
        http_connection.endheaders(request_body)
        transport.settimeout(_remaining(deadline))
        response = http_connection.getresponse()
        try:
            response_body = _read_body(response, transport, deadline)
            return response.status, response.headers, response_body
        finally:
            response.close()
    except UnsafeURL:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError, TypeError):
        raise _failure('Safe HTTP request failed') from None
    finally:
        if transport is not None:
            transport.close()
        else:
            connection.close()


def safe_urlopen(
    request: urllib.request.Request | str,
    timeout: float | None = None,
) -> CachedResponse:
    """Open a bounded HTTP(S) request without proxy or post-validation DNS."""
    if isinstance(request, str):
        request = urllib.request.Request(request)
    if not isinstance(request, urllib.request.Request):
        raise _failure('Invalid HTTP request')
    if request.get_method() != 'GET' or request.data is not None:
        raise _failure('Only GET requests without a body are supported')

    deadline = _deadline(timeout)
    current_url = request.full_url
    current_request = request
    redirect_count = 0
    original_origin: tuple[str, str, int] | None = None
    wire_budget = _WireBudget()

    while True:
        target = validate_public_url(current_url, timeout=_remaining(deadline))
        _remaining(deadline)
        origin = (target.scheme, target.host.lower(), target.port)
        if original_origin is None:
            original_origin = origin
        status, headers, response_body = _fetch_one(
            current_request,
            target,
            deadline,
            drop_credentials=origin != original_origin,
            wire_budget=wire_budget,
        )
        if status in _REDIRECT_STATUSES:
            location = headers.get('Location')
            if not location:
                raise _failure('HTTP redirect is missing Location')
            if any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in location) or '\\' in location:
                raise _failure('Invalid HTTP redirect target')
            if redirect_count >= MAX_REDIRECTS:
                raise _failure('HTTP redirect limit exceeded')
            try:
                next_url = urljoin(current_url, location)
            except ValueError:
                raise _failure('Invalid HTTP redirect target') from None
            _remaining(deadline)
            redirect_count += 1
            if status == 303 or (status in {301, 302} and current_request.get_method().upper() == 'POST'):
                current_request = urllib.request.Request(
                    next_url,
                    headers=dict(current_request.header_items()),
                    method='GET',
                )
            current_url = next_url
            continue
        if status >= 400:
            raise SafeHTTPStatusError(status, headers, response_body)
        return CachedResponse(current_url, status, headers, response_body)
