import asyncio
from types import SimpleNamespace

import pytest
from scrapy.http import Request, Response

from news_crawler import download_handlers as handler


@pytest.fixture(autouse=True)
def synthetic_dns(monkeypatch):
    # These unit downloads never use a socket. The DNS rejection test below
    # installs its own rejecting validator; the actual HTTP test is subprocess-isolated.
    from api.services.article_fetcher import safe_http
    monkeypatch.setattr(safe_http, 'validate_public_url', lambda url, timeout: None)
    from api.rss import legacy_fencing
    monkeypatch.setattr(legacy_fencing, 'capture_source_token', lambda key: object())
    monkeypatch.setattr(legacy_fencing, 'validate_source_token', lambda token: None)


class Stats:
    def __init__(self):
        self.values = {}
    def set_value(self, key, value):
        self.values[key] = value
    def inc_value(self, key):
        self.values[key] = self.values.get(key, 0) + 1


def instance(inner):
    value = handler.BudgetedHTTPDownloadHandler.__new__(handler.BudgetedHTTPDownloadHandler)
    value.crawler = SimpleNamespace(spider=SimpleNamespace(name='devto'), stats=Stats())
    value.inner = inner
    return value


def test_cancel_closes_underlying_download_and_releases_own_token(monkeypatch):
    started = asyncio.Event()
    closed = []
    released = []
    permit = object()
    class Inner:
        async def download_request(self, request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.append(True)
    monkeypatch.setattr(handler, 'claim_budget', lambda *args, **kwargs: permit)
    monkeypatch.setattr(handler, 'confirm_permit', lambda *args, **kwargs: None)
    monkeypatch.setattr(handler, 'release_budget', lambda value: released.append(value))
    async def db(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(handler, '_db', db)
    async def scenario():
        value = instance(Inner())
        pending = asyncio.create_task(value.download_request(Request('https://dev.to/api/articles')))
        await asyncio.wait_for(started.wait(), timeout=5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert value.crawler.stats.values['budget/physical_requests'] == 1
    asyncio.run(scenario())
    assert closed == [True] and released == [permit]


def test_429_records_cooldown_before_raising_and_never_returns_success(monkeypatch):
    calls = []
    permit = object()
    class Inner:
        async def download_request(self, request):
            calls.append('http')
            return Response(request.url, status=429, headers={'Retry-After': '120'})
    monkeypatch.setattr(handler, 'claim_budget', lambda *args, **kwargs: permit)
    monkeypatch.setattr(handler, 'confirm_permit', lambda *args, **kwargs: None)
    def record(value, status, headers, **kwargs):
        assert value is permit and status == 429 and headers['Retry-After'] == '120'
        calls.append('cooldown')
        return handler.timezone.now()
    monkeypatch.setattr(handler, 'record_response', record)
    monkeypatch.setattr(handler, 'release_budget', lambda value: calls.append('release'))
    async def db(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(handler, '_db', db)
    async def scenario():
        with pytest.raises(handler.BudgetDeferred) as error:
            await instance(Inner()).download_request(Request('https://dev.to/api/articles'))
        assert error.value.error_code == 'rate_limited' and error.value.http_status == 429
    asyncio.run(scenario())
    assert calls == ['http', 'cooldown', 'release']


def test_unapproved_feed_hrefs_never_reach_http_or_budget(monkeypatch):
    class Inner:
        async def download_request(self, request):
            raise AssertionError('unapproved URL was downloaded')
    monkeypatch.setattr(handler, 'claim_budget', lambda *args, **kwargs: pytest.fail('unapproved URL took budget'))
    async def scenario():
        for url in ('http://127.0.0.1/private', 'https://unknown.example/article', 'https://user:secret@dev.to/article'):
            with pytest.raises(ValueError, match='unapproved_discovery_host'):
                await instance(Inner()).download_request(Request(url))
    asyncio.run(scenario())


def test_approved_host_is_dns_revalidated_at_physical_download_boundary(monkeypatch):
    from api.services.article_fetcher import safe_http
    class Inner:
        async def download_request(self, request):
            raise AssertionError('unsafe DNS answer reached the network handler')
    calls = []
    def reject(url, timeout):
        calls.append((url, timeout))
        raise safe_http.UnsafeURL('Private or local URLs are not allowed')
    monkeypatch.setattr(safe_http, 'validate_public_url', reject)
    monkeypatch.setattr(handler, 'claim_budget', lambda *args, **kwargs: pytest.fail('unsafe DNS answer took budget'))
    async def scenario():
        with pytest.raises(safe_http.UnsafeURL, match='Private or local'):
            await instance(Inner()).download_request(Request('https://dev.to/api/articles'))
    asyncio.run(scenario())
    assert calls == [('https://dev.to/api/articles', 3.0)]


def test_actual_http11_drip_download_hard_deadline_closes_socket_and_releases_permit(tmp_path):
    """A controlled local server keeps idle timeout alive; total deadline must win."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[3]
    script = tmp_path / 'local_handler_probe.py'
    script.write_text(r'''
import django, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from django.core.management import call_command
from django.db import connection

django.setup()
call_command('migrate', verbosity=0)
from scrapy import Spider, Request
from scrapy.crawler import CrawlerProcess
from news_crawler.download_handlers import BudgetedHTTPDownloadHandler
from api.models import RequestBudget
closed = threading.Event()
class Server(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/limited':
            self.send_response(429)
            self.send_header('Retry-After', '120')
            self.send_header('Content-Length', '99999999')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Length', '3000')
        self.end_headers()
        try:
            for _ in range(3000):
                self.wfile.write(b'x')
                self.wfile.flush()
                time.sleep(.02)
        except (BrokenPipeError, ConnectionResetError):
            closed.set()
server = ThreadingHTTPServer(('127.0.0.1', 0), Server)
threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True).start()
class LocalHandler(BudgetedHTTPDownloadHandler):
    def _allowed(self, request):
        # Test-only route. Production continues to reject local/private URLs.
        return request.url in {f'http://127.0.0.1:{server.server_port}/drip', f'http://127.0.0.1:{server.server_port}/limited'}
class Probe(Spider):
    name = 'devto'
    async def start(self):
        yield Request(f'http://127.0.0.1:{server.server_port}/drip', errback=self.failure,
                      meta={'download_timeout': 999, 'dont_retry': True})
    def failure(self, failure):
        if failure.request.url.endswith('/drip'):
            self.failed = True
            return Request(f'http://127.0.0.1:{server.server_port}/limited', errback=self.failure, meta={'dont_retry': True})
        assert failure.value.error_code == 'rate_limited' and failure.value.http_status == 429
        self.limited = True
    def parse(self, response):
        raise AssertionError('drip response should never finish within total deadline')
process = CrawlerProcess({
    'DOWNLOAD_HANDLERS': {'http': '__main__.LocalHandler', 'https': '__main__.LocalHandler'},
    'TWISTED_REACTOR': 'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
    'LOG_ENABLED': False, 'ROBOTSTXT_OBEY': False, 'TELNETCONSOLE_ENABLED': False,
    'REMOTE_CONTROL_ENABLED': False,
})
crawler = process.create_crawler(Probe)
process.crawl(crawler)
started = time.monotonic()
process.start()
elapsed = time.monotonic() - started
assert 14 <= elapsed < 22, elapsed
assert closed.wait(2), 'cancelled download left the streaming connection open'
assert getattr(crawler.spider, 'failed', False)
assert crawler.stats.get_value('budget/physical_requests') == 2
assert getattr(crawler.spider, 'limited', False)
from django.utils import timezone
from datetime import timedelta
assert RequestBudget.objects.get(pk='host:127.0.0.1').cooldown_until >= timezone.now() + timedelta(seconds=119)
assert not RequestBudget.objects.exclude(lease_token='').exists()
with connection.cursor() as cursor:
    cursor.execute('PRAGMA journal_mode')
    assert cursor.fetchone()[0] == 'wal'
server.shutdown()
print(json.dumps({'hard_deadline':True,'socket_closed':True,'permit_released':True}))
''', encoding='utf-8')
    result = subprocess.run([sys.executable, str(script)], cwd=root, env={
        **os.environ, 'PYTHONPATH': f'{root / "backend"}:{root / "crawler"}',
        'DJANGO_ENV': 'development', 'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'RUN_MAIN': 'true', 'DJANGO_DB_PATH': str(tmp_path / 'handler.sqlite3'),
    }, capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"socket_closed": true' in result.stdout


def test_retry_after_header_does_not_override_oversize_guard():
    from scrapy.http import Headers
    from scrapy.exceptions import StopDownload
    request = Request('https://dev.to/api/articles', meta={'download_maxsize': 10})
    with pytest.raises(StopDownload) as stopped:
        handler._received_headers(Headers({'Retry-After': '120'}), 999, request)
    assert stopped.value.fail is False
    # Retry-After alone is not an error; the header says 999 bytes but the
    # per-request maximum is 10, so the correct early stop is oversize.
    assert request.meta['_budget_body_stopped'] == 'oversize'
    request.meta['_budget_body_stopped'] = ''
    handler._received_bytes(b'12345', request)
    with pytest.raises(StopDownload) as stopped:
        handler._received_bytes(b'123456', request)
    assert stopped.value.fail is False
    assert request.meta['_budget_body_stopped'] == 'oversize'


def test_unknown_chunked_body_length_is_handled_by_byte_limit():
    from scrapy.http import Headers
    from twisted.web.iweb import UNKNOWN_LENGTH
    request = Request('https://dev.to/api/articles')
    handler._received_headers(Headers(), UNKNOWN_LENGTH, request)
    assert not request.meta.get('_budget_body_stopped')



@pytest.mark.parametrize(('status', 'headers'), [(206, {}), (200, {'Content-Range': 'bytes 0-9/100'})])
def test_partial_download_never_reaches_feed_parser(monkeypatch, status, headers):
    released = []
    permit = object()
    class Inner:
        async def download_request(self, request):
            return Response(request.url, status=status, headers=headers, body=b'valid-looking partial feed')
    monkeypatch.setattr(handler, 'claim_budget', lambda *args, **kwargs: permit)
    monkeypatch.setattr(handler, 'confirm_permit', lambda *args, **kwargs: None)
    monkeypatch.setattr(handler, 'record_response', lambda *args, **kwargs: None)
    monkeypatch.setattr(handler, 'release_budget', lambda value: released.append(value))
    async def db(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(handler, '_db', db)
    async def scenario():
        value = instance(Inner())
        with pytest.raises(ValueError, match='body_partial'):
            await value.download_request(Request('https://dev.to/api/articles'))
        assert value.crawler.stats.values[f'budget/http_status_count/{status}'] == 1
    asyncio.run(scenario())
    assert released == [permit]
