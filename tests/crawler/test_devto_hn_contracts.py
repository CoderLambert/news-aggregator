import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone
from scrapy import Request
from scrapy.http import TextResponse

from api.models import News, NewsSourceItem
from api.services.news_ingestion import ingest_item
from api.services.article_fetcher.validators import validate_candidate
from news_crawler.spiders.devto_spider import DevToSpider
from news_crawler.spiders.hackernews_spider import HackerNewsSpider


def article(identity=1, **extra):
    return dict(id=identity, title=f'Article {identity}', url=f'https://dev.to/person/article-{identity}',
                published_at=timezone.now().isoformat(), description='A metadata excerpt.', **extra)


def response(payload, url, meta=None, status=200):
    request = Request(url, meta=meta or {})
    return TextResponse(url, request=request, body=json.dumps(payload).encode(), encoding='utf-8', status=status)


def spider(cls, *, capture=True):
    value = cls()
    value.crawler = Mock()
    if capture:
        from api.rss.legacy_fencing import capture_source_token
        value._legacy_source_token = capture_source_token(value.name)
    return value


async def collect(generator):
    return [item async for item in generator]


@pytest.mark.django_db(transaction=True)
def test_dev_discovery_deduplicates_ids_caps_details_and_keeps_durable_overflow(settings):
    settings.STRUCTURED_BODY_INGEST_ENABLED = True
    settings.STRUCTURED_BODY_SOURCE_KEYS = {'devto'}
    settings.FULL_CONTENT_AUTO_ENQUEUE_ENABLED = True
    settings.FULL_CONTENT_AUTO_SOURCE_KEYS = {'devto'}
    value = spider(DevToSpider)
    entries = [article(i) for i in range(1, 24)]
    first = asyncio.run(collect(value.parse(response(entries, value.start_urls[0]))))
    second = asyncio.run(collect(value.parse(response(entries, value.start_urls[1]))))
    assert len([item for item in first if isinstance(item, Request)]) == 20
    assert len([item for item in first if not isinstance(item, Request)]) == 23
    assert second == []
    assert News.objects.count() == NewsSourceItem.objects.count() == 23
    assert News.objects.filter(full_content_fetch_status='queued', full_content_next_attempt_at__isnull=False).count() == 23
    assert all(item.meta['expected_revision'] == 0 for item in first if isinstance(item, Request))


@pytest.mark.django_db(transaction=True)
def test_dev_disabled_or_unreliable_old_publication_never_frontloads_detail(settings):
    settings.STRUCTURED_BODY_INGEST_ENABLED = False
    settings.STRUCTURED_BODY_SOURCE_KEYS = {'devto'}
    value = spider(DevToSpider)
    items = asyncio.run(collect(value.parse(response([article()], value.start_urls[0]))))
    assert len(items) == 1 and not isinstance(items[0], Request)
    settings.STRUCTURED_BODY_INGEST_ENABLED = True
    old = article(2)
    old['published_at'] = (timezone.now() - timedelta(days=8)).isoformat()
    missing = article(3)
    missing['published_at'] = None
    items = asyncio.run(collect(value.parse(response([old, missing], value.start_urls[0]))))
    assert not any(isinstance(item, Request) for item in items)


@pytest.mark.django_db(transaction=True)
def test_dev_new_detail_preserves_markdown_but_cannot_capture_token_after_discovery(settings):
    settings.STRUCTURED_BODY_INGEST_ENABLED = True
    settings.STRUCTURED_BODY_SOURCE_KEYS = {'devto'}
    value = spider(DevToSpider)
    emitted = asyncio.run(collect(value.parse(response([article()], value.start_urls[0]))))
    request = next(item for item in emitted if isinstance(item, Request))
    payload = article(body_markdown='Full content.\n\n' * 700, edited_at=timezone.now().isoformat())
    item = list(value.parse_article(response(payload, request.url, request.meta)))[0]
    assert len(item['body_candidate'].raw_content) > 5000
    assert item['content'] == payload['description']
    result = ingest_item(item)
    assert not result.body_committed and result.reason == 'not_body_owner'
    news = News.objects.get(pk=result.news_id)
    assert news.full_content == '' and news.full_content_revision == 0
    assert ingest_item(item).receipt_outcome == 'committed'
    assert News.objects.get(pk=news.pk).full_content_revision == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('fault', ['id', 'url', 'status', 'invalid_json'])
def test_dev_failed_details_preserve_discovery_and_queue(settings, fault):
    settings.STRUCTURED_BODY_INGEST_ENABLED = True
    settings.STRUCTURED_BODY_SOURCE_KEYS = {'devto'}
    settings.FULL_CONTENT_AUTO_ENQUEUE_ENABLED = True
    settings.FULL_CONTENT_AUTO_SOURCE_KEYS = {'devto'}
    value = spider(DevToSpider)
    emitted = asyncio.run(collect(value.parse(response([article()], value.start_urls[0]))))
    request = next(item for item in emitted if isinstance(item, Request))
    payload = article(body_markdown='Full short body.')
    if fault == 'id': payload['id'] = 2
    if fault == 'url': payload['url'] = 'https://dev.to/person/different-article'
    detail = response(payload, request.url, request.meta, status=429 if fault == 'status' else 200)
    if fault == 'invalid_json': detail = detail.replace(body=b'{')
    item = list(value.parse_article(detail))[0]
    assert 'body_candidate' not in item
    assert ingest_item(item).receipt_outcome == 'committed'
    news = News.objects.get()
    assert news.url == article()['url'] and news.full_content == ''
    assert news.full_content_fetch_status == 'queued'


@pytest.mark.django_db
@pytest.mark.parametrize('external', [False, True])
def test_hn_self_post_and_external_story_have_separate_body_contracts(settings, external):
    settings.STRUCTURED_BODY_INGEST_ENABLED = True
    settings.STRUCTURED_BODY_SOURCE_KEYS = {'hackernews'}
    value = spider(HackerNewsSpider)
    payload = dict(id=12, type='story', title='Practical question', time=1720000000,
                   text='<p>A complete short self-post question?</p>', score=42, descendants=17)
    if external: payload['url'] = 'https://webkit.org/blog/12/original/'
    item = list(value.parse_item(response(payload,
        'https://hacker-news.firebaseio.com/v0/item/12.json', {'hn_id': '12', 'request_started_at': timezone.now()})))[0]
    assert item['publish_time'].utcoffset().total_seconds() == 0
    assert item['discovery_url'] == 'https://news.ycombinator.com/item?id=12'
    assert item['content_kind'] == ('article' if external else 'discussion')
    assert 'Score' not in item['content'] and 'Comments' not in item['content']
    if external:
        assert item['url'] == payload['url'] and 'body_candidate' not in item
    else:
        assert validate_candidate(item['body_candidate'], expected_url=item['url']).ok
    result = ingest_item(item, legacy_token=value._legacy_source_token)
    assert result.body_committed is not external


def test_hn_mismatched_api_id_cannot_create_discovery():
    value = spider(HackerNewsSpider, capture=False)
    assert list(value.parse_item(response(dict(id=99, type='story', title='Other'),
        'https://hacker-news.firebaseio.com/v0/item/12.json', {'hn_id': '12'}))) == []
