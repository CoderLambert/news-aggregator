"""Header admission must preserve complete HTTP 200 feed responses.

These are pure header-signal tests: no publisher requests or database writes.
"""
import pytest
from scrapy import Request
from scrapy.exceptions import StopDownload
from scrapy.http import Headers

from news_crawler.download_handlers import _received_headers, _received_bytes


def test_retry_after_alone_does_not_interrupt_a_valid_feed_body():
    request = Request('https://webkit.org/feed/')
    request.meta['_budget_body_stopped'] = ''
    _received_headers(Headers({b'Retry-After': b'120'}), 1024, request)
    assert request.meta['_budget_body_stopped'] == ''
    _received_bytes(b'<rss><channel><item>real entry</item></channel></rss>', request)
    assert request.meta['_budget_received_bytes'] > 0


def test_content_range_and_oversized_body_still_stop_at_header_boundary():
    partial = Request('https://webkit.org/feed/')
    with pytest.raises(StopDownload):
        _received_headers(Headers({b'Content-Range': b'bytes 0-99/200'}), 100, partial)
    assert partial.meta['_budget_body_stopped'] == 'body_partial'

    too_large = Request('https://webkit.org/feed/', meta={'download_maxsize': 10})
    with pytest.raises(StopDownload):
        _received_headers(Headers({b'Retry-After': b'60'}), 11, too_large)
    assert too_large.meta['_budget_body_stopped'] == 'oversize'


def test_bytes_limit_remains_enforced_after_header_acceptance():
    request = Request('https://webkit.org/feed/', meta={'download_maxsize': 4})
    _received_headers(Headers({b'Retry-After': b'30'}), 4, request)
    with pytest.raises(StopDownload):
        _received_bytes(b'12345', request)
    assert request.meta['_budget_body_stopped'] == 'oversize'
