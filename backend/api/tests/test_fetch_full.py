from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Category, News, Source
from api.services.article_fetcher import FetchError, FetchResult


@pytest.fixture
def src(db):
    return Source.objects.create(name='TestSource', url='https://example.com', language='en')


@pytest.fixture
def cat(db):
    return Category.objects.create(name='科技', slug='tech')


def _news(src, cat, **overrides):
    defaults = dict(
        title='测试文章标题',
        content='这是一段已有摘要内容，但不能冒充原文。',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/article',
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


@pytest.mark.django_db
class TestNewsFetchFullView:
    def test_fetch_full_uses_article_fetcher_and_persists_real_content(self, client, src, cat):
        news = _news(src, cat)
        result = FetchResult(
            ok=True,
            provider='scrapy_http',
            url=news.url,
            title=news.title,
            markdown='FETCHED FULL BODY',
            quality_score=0.88,
        )

        with patch('api.views.fetch_article_markdown', return_value=result) as fetch:
            resp = client.post(f'/api/news/{news.pk}/fetch-full/')

        assert resp.status_code == 200
        fetch.assert_called_once_with(
            news.url,
            expected_title=news.title,
            summary=news.content,
        )
        news.refresh_from_db()
        assert news.full_content == 'FETCHED FULL BODY'
        assert news.full_content_fetched_at is not None
        assert news.full_content_fetch_status == 'success'
        assert news.full_content_fetch_error == ''
        assert news.full_content_fetch_provider == 'scrapy_http'
        assert news.full_content_quality_score == 0.88
        assert news.last_full_content_attempt is not None

    def test_fetch_full_does_not_persist_summary_as_full_content_when_fetchers_fail(self, client, src, cat):
        """Summary/fallback text must not masquerade as fetched original content."""
        news = _news(src, cat, title='LLMs Are Closer to Religion Than They Appear')

        with patch('api.views.fetch_article_markdown', side_effect=FetchError('全部真实原文抓取方式失败')):
            resp = client.post(f'/api/news/{news.pk}/fetch-full/')

        assert resp.status_code == 502
        data = resp.json()
        assert '原文抓取失败' in data['error']
        assert '可稍后重试' in data['error']

        news.refresh_from_db()
        assert news.full_content == ''
        assert news.full_content_fetched_at is None
        assert news.full_content_fetch_status == 'failed'
        assert news.full_content_fetch_error == '全部真实原文抓取方式失败'
        assert news.full_content_retry_count == 1

    def test_fetch_full_records_network_error_without_persisting_content(self, client, src, cat):
        news = _news(src, cat, title='Network failure article')

        with patch('api.views.fetch_article_markdown', side_effect=FetchError('connection reset by peer')):
            resp = client.post(f'/api/news/{news.pk}/fetch-full/')

        assert resp.status_code == 502
        news.refresh_from_db()
        assert news.full_content == ''
        assert news.full_content_fetched_at is None
        assert news.full_content_fetch_status == 'network_error'
        assert news.full_content_fetch_error == 'connection reset by peer'
        assert news.full_content_retry_count == 1
