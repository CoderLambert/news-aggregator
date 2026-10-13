"""Thin shared-budget wrapper around Scrapy's maintained HTTP/1.1 handler."""
import asyncio
import inspect
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from django.utils import timezone
from scrapy import signals
from scrapy.exceptions import StopDownload
from scrapy.core.downloader.handlers.http11 import HTTP11DownloadHandler
from scrapy.utils.defer import maybe_deferred_to_future
from twisted.internet.defer import Deferred

from news_crawler.django_support import initialize_django

initialize_django()

from api.services.request_budget import (
    BudgetDeferred, claim_budget, confirm_permit, record_response, release_budget, scope_intervals,
)
from api.services.source_policy import POLICIES


async def _db(function, *args, **kwargs):
    def call():
        close_old_connections()
        try:
            return function(*args, **kwargs)
        finally:
            close_old_connections()
    return await sync_to_async(call, thread_sensitive=False)()


async def _await_inner(value):
    if isinstance(value, Deferred):
        return await maybe_deferred_to_future(value)
    if inspect.isawaitable(value):
        return await value
    return value



def _received_headers(headers, body_length, request, **kwargs):
    if headers.get('Content-Range') is not None:
        request.meta['_budget_body_stopped'] = 'body_partial'
        raise StopDownload(fail=False)
    if headers.get('Retry-After') is not None:
        request.meta['_budget_body_stopped'] = 'retry_after'
        raise StopDownload(fail=False)
    if isinstance(body_length, int) and body_length > request.meta.get('download_maxsize', 8 * 1024 * 1024):
        request.meta['_budget_body_stopped'] = 'oversize'
        raise StopDownload(fail=False)


def _received_bytes(data, request, **kwargs):
    size = request.meta.get('_budget_received_bytes', 0) + len(data)
    request.meta['_budget_received_bytes'] = size
    if size > request.meta.get('download_maxsize', 8 * 1024 * 1024):
        request.meta['_budget_body_stopped'] = 'oversize'
        raise StopDownload(fail=False)


class BudgetedHTTPDownloadHandler:
    lazy = False

    def __init__(self, crawler):
        self.crawler = crawler
        crawler.signals.connect(_received_headers, signal=signals.headers_received)
        crawler.signals.connect(_received_bytes, signal=signals.bytes_received)
        self.inner = (HTTP11DownloadHandler.from_crawler(crawler) if hasattr(HTTP11DownloadHandler, 'from_crawler')
                      else HTTP11DownloadHandler(crawler.settings, crawler))

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def _allowed(self, request):
        parsed = urlsplit(request.url)
        policy = POLICIES.get(self.crawler.spider.name)
        hosts = set(policy.domains) if policy else set()
        if policy and policy.feed_url:
            hosts.add(urlsplit(policy.feed_url).hostname)
        hosts.update({'hackernews': ('hacker-news.firebaseio.com',),
                      'github': ('raw.githubusercontent.com',),
                      'infoq': ('feed.infoq.com',),
                      'deepmind': ('blog.google',)}.get(self.crawler.spider.name, ()))
        return (policy is not None and not policy.unsupported_reason and parsed.scheme in {'http', 'https'} and
                parsed.hostname in hosts and parsed.port in {None, 80, 443} and parsed.username is None and parsed.password is None)

    async def download_request(self, request, spider=None):
        if not self._allowed(request):
            raise ValueError('unapproved_discovery_host')
        request.meta['_budget_received_bytes'] = 0
        request.meta['_budget_body_stopped'] = ''
        request.meta['download_timeout'] = min(15, request.meta.get('download_timeout', 15))
        request.meta['download_maxsize'] = min(8 * 1024 * 1024, request.meta.get('download_maxsize', 8 * 1024 * 1024))
        scopes = scope_intervals(request.url)
        permit = None
        wait_deadline = asyncio.get_running_loop().time() + 3.1
        try:
            while True:
                acquisition = asyncio.create_task(_db(claim_budget, scopes))
                try:
                    permit = await asyncio.shield(acquisition)
                    break
                except asyncio.CancelledError:
                    # The ORM thread is not cancellable. Obtain its result and
                    # release it, rather than leaving an unobserved permit.
                    try:
                        permit = await acquisition
                    except BudgetDeferred:
                        pass
                    raise
                except BudgetDeferred as error:
                    delay = max(0.01, (error.retry_after_at - timezone.now()).total_seconds())
                    if asyncio.get_running_loop().time() + delay > wait_deadline:
                        self.crawler.stats.inc_value('budget/deferred')
                        self.crawler.stats.set_value('next_attempt_at', error.retry_after_at.isoformat())
                        raise
                    await asyncio.sleep(delay)
            await _db(confirm_permit, permit)
            self.crawler.stats.inc_value('budget/physical_requests')
            method = self.inner.download_request
            args = (request, self.crawler.spider) if 'spider' in inspect.signature(method).parameters else (request,)
            response = await asyncio.wait_for(_await_inner(method(*args)), timeout=15)
            headers = {key.decode('latin1'): response.headers.get(key).decode('latin1') for key in response.headers.keys()}
            retry_at = await _db(record_response, permit, response.status, headers, host=urlsplit(request.url).hostname)
            self.crawler.stats.inc_value(f'budget/http_status_count/{response.status}')
            if retry_at is not None:
                self.crawler.stats.inc_value('budget/rate_limited')
                self.crawler.stats.set_value('next_attempt_at', retry_at.isoformat())
                error = BudgetDeferred(retry_at, scopes)
                error.error_code = 'rate_limited'
                error.http_status = response.status
                raise error
            if response.status >= 400:
                return response
            if response.status == 206 or response.headers.get('Content-Range') is not None:
                raise ValueError('body_partial')
            if request.meta.get('_budget_body_stopped') or 'download_stopped' in response.flags:
                raise ValueError(request.meta.get('_budget_body_stopped') or 'body_partial')
            return response
        finally:
            if permit is not None:
                await asyncio.shield(_db(release_budget, permit))

    async def close(self):
        await _await_inner(self.inner.close())
