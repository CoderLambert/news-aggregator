"""Identity safeguards exercised with synthetic publisher responses only."""
from importlib import import_module
from unittest.mock import patch

import pytest
from django.utils import timezone
from scrapy import signals
from scrapy.crawler import Crawler
from scrapy.statscollectors import MemoryStatsCollector
from scrapy.http import TextResponse


@pytest.mark.parametrize('module,class_name', [
    ('reuters', 'ReutersSpider'),
    ('jiqizhixin', 'JiqizhixinSpider'),
    ('sanliu_kr', 'SanliuKrSpider'),
])
def test_unverified_sources_neither_request_nor_accept_articles(module, class_name):
    cls = getattr(import_module(f'news_crawler.spiders.{module}_spider'), class_name)
    crawler = Crawler(cls)
    crawler.stats = MemoryStatsCollector(crawler)
    spider = cls.from_crawler(crawler)
    crawler.signals.send_catch_log(signal=signals.spider_opened, spider=spider)
    assert spider.start_urls == []
    assert list(spider.parse(TextResponse(
        url='https://example.test/feed',
        body=b'<rss><channel><item><title>Same title</title>'
             b'<link>https://example.test/article</link></item></channel></rss>',
        encoding='utf-8',
    ))) == []
    assert crawler.stats.get_value('outcome') == 'unsupported'
    assert len(crawler.stats.get_value('policy_skips_by_reason')) == 1


def item(url):
    return {
        'title': 'Same publisher title', 'content': 'A summary.',
        'url': url, 'author': '', 'cover_image': '',
        'publish_time': timezone.now(), 'source_name': 'WebKit',
        'category_name': 'identity-test',
    }


@pytest.mark.django_db
def test_same_title_different_urls_are_distinct(monkeypatch):
    from news_crawler import pipelines
    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')
    with patch.object(pipelines, 'close_old_connections'):
        first = pipelines._save_item_sync(item('https://webkit.org/blog/1/first'))
        second = pipelines._save_item_sync(item('https://webkit.org/blog/2/second'))
    assert first.pk != second.pk
    first.refresh_from_db()
    assert first.url == 'https://webkit.org/blog/1/first'


@pytest.mark.django_db
def test_metadata_update_preserves_concurrent_full_content(monkeypatch):
    from api.models import News
    from django.db.models.query import QuerySet
    from news_crawler import pipelines
    monkeypatch.setenv('NEWS_CRAWL_ONLY', '1')
    with patch.object(pipelines, 'close_old_connections'):
        data = item('https://webkit.org/blog/1/concurrency')
        news = pipelines._save_item_sync(data)
        original_time = news.publish_time
        original_update = QuerySet.update
        interleaved = False

        def interleave(query, **updates):
            nonlocal interleaved
            if query.model is News and 'content' in updates and not interleaved:
                interleaved = True
                original_update(News.objects.filter(pk=news.pk),
                    full_content='Concurrent body', full_content_zh='并发译文',
                    full_content_fetch_status='success',
                    suggested_questions=['Concurrent question'],
                )
            return original_update(query, **updates)

        data['content'] = 'Short'
        data['publish_time'] = None
        with patch.object(QuerySet, 'update', interleave):
            pipelines._save_item_sync(data)
        assert interleaved
    news.refresh_from_db()
    assert news.content == 'Short'
    assert news.publish_time == original_time
    assert news.full_content == 'Concurrent body'
    assert news.full_content_zh == '并发译文'
    assert news.full_content_fetch_status == 'success'
    assert news.suggested_questions == ['Concurrent question']


@pytest.mark.django_db
def test_source_sync_preserves_existing_switches():
    from api.models import CrawlerTarget
    from api.services.crawler_control import sync_crawler_targets
    leiphone = CrawlerTarget.objects.create(spider_name='leiphone', enabled=False)
    reuters = CrawlerTarget.objects.create(spider_name='reuters', enabled=True)
    sync_crawler_targets()
    leiphone.refresh_from_db()
    reuters.refresh_from_db()
    assert leiphone.display_name == '雷峰网'
    assert not leiphone.enabled
    assert reuters.enabled  # Runtime remains quarantined even if a target is enabled.
    assert not CrawlerTarget.objects.get(spider_name='jiqizhixin').enabled
