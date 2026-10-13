from datetime import datetime, timezone

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse

from news_crawler.spiders.anthropic_blog_spider import AnthropicBlogSpider
from news_crawler.spiders.meta_ai_blog_spider import MetaAiBlogSpider
from news_crawler.spiders.mistral_blog_spider import MistralBlogSpider


@pytest.fixture(params=[
    (AnthropicBlogSpider, 'https://www.anthropic.com/news', '/news/'),
    (MetaAiBlogSpider, 'https://ai.meta.com/blog/', '/blog/'),
    (MistralBlogSpider, 'https://mistral.ai/news/', '/news/'),
])
def source(request): return request.param


def html_response(url, body, request=None):
    return HtmlResponse(url, request=request or Request(url), body=body.encode(), encoding='utf-8')


def test_html_discovery_follows_bounded_genuine_links_only(source):
    cls, listing, prefix = source
    body = '<html><body>' + ''.join(f'<a href="{prefix}actual-{i}">Publisher link</a>' for i in range(40))
    body += '<a href="https://evil.example/blog/fake">Cross-host</a><a href="/search?q=fake">Search</a></body></html>'
    requests = list(cls().parse(html_response(listing, body)))
    assert len(requests) == 20
    assert all(request.meta['discovery_target_url'] == request.url for request in requests)
    assert all('actual-' in request.url for request in requests)


@pytest.mark.parametrize('stamp', [None, '2026-10-13T09:00:00+08:00'])
def test_html_article_dates_do_not_fabricate_now_or_drop_offsets(source, stamp):
    cls, listing, prefix = source
    target = listing.rstrip('/').rsplit('/', 1)[0] + prefix + 'actual-1'
    body = '<html><head>' + (f'<meta property="article:published_time" content="{stamp}">' if stamp else '')
    body += '</head><body><article><h1>Publisher title</h1><p>' + ('Article summary prose. ' * 80) + '</p></article></body></html>'
    item = list(cls().parse_article(html_response(target, body, Request(target, meta={'discovery_target_url': target}))))[0]
    assert len(item['content']) <= 1000 and 'body_candidate' not in item
    assert item['content_kind'] == 'article'
    assert item['publish_time_inferred'] is (stamp is None)
    assert item['publish_time'] == (datetime(2026, 10, 13, 1, tzinfo=timezone.utc) if stamp else None)


def test_html_redirect_to_different_article_does_not_change_identity(source):
    cls, listing, prefix = source
    target = listing.rstrip('/').rsplit('/', 1)[0] + prefix + 'actual-1'
    redirected = target.replace('actual-1', 'different-article')
    body = '<article><h1>Publisher title</h1><p>' + ('Article body. ' * 50) + '</p></article>'
    request = Request(redirected, meta={'discovery_target_url': target})
    assert list(cls().parse_article(html_response(redirected, body, request))) == []
