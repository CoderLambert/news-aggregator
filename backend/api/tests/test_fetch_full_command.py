from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from api.models import Category, News, Source
from api.services.article_fetcher import FetchResult


@pytest.fixture
def src(db):
    return Source.objects.create(name='BatchSource', url='https://example.com', language='en')


@pytest.fixture
def cat(db):
    return Category.objects.create(name='科技', slug='tech-batch')


def _news(src, cat, **overrides):
    defaults = dict(
        title='Batch Article',
        content='Short list summary only.',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/batch-article',
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


def _ok_result(news, provider='scrapy_http'):
    return FetchResult(
        ok=True,
        provider=provider,
        url=news.url,
        title=news.title,
        markdown='REAL FULL ARTICLE BODY ' * 30,
        quality_score=0.91,
    )


@pytest.mark.django_db
def test_fetch_full_content_command_updates_missing_full_content(src, cat):
    news = _news(src, cat)
    result = _ok_result(news)

    with patch('api.management.commands.fetch_full_content.fetch_article_markdown', return_value=result):
        call_command('fetch_full_content', '--limit', '1')

    news.refresh_from_db()
    assert news.full_content.startswith('REAL FULL ARTICLE BODY')
    assert news.full_content_fetched_at is not None
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_fetch_provider == 'scrapy_http'


@pytest.mark.django_db
def test_fetch_full_content_command_dry_run_does_not_persist(src, cat):
    news = _news(src, cat)

    with patch('api.management.commands.fetch_full_content.fetch_article_markdown') as fetch:
        call_command('fetch_full_content', '--limit', '1', '--dry-run')

    fetch.assert_not_called()
    news.refresh_from_db()
    assert news.full_content == ''


@pytest.mark.django_db
def test_fetch_full_content_command_status_filter_only_processes_requested_status(src, cat):
    network = _news(src, cat, url='https://example.com/network', full_content_fetch_status='network_error')
    failed = _news(src, cat, url='https://example.com/failed', full_content_fetch_status='failed')

    def fake_fetch(url, **kwargs):
        assert url == network.url
        return _ok_result(network, provider='jina')

    with patch('api.management.commands.fetch_full_content.fetch_article_markdown', side_effect=fake_fetch) as fetch:
        call_command('fetch_full_content', '--status', 'network_error', '--limit', '10')

    assert fetch.call_count == 1
    network.refresh_from_db()
    failed.refresh_from_db()
    assert network.full_content_fetch_status == 'success'
    assert failed.full_content_fetch_status == 'failed'
    assert failed.full_content == ''


@pytest.mark.django_db
def test_fetch_full_content_command_max_retries_skips_retry_limit(src, cat):
    _news(src, cat, full_content_fetch_status='failed', full_content_retry_count=3)

    with patch('api.management.commands.fetch_full_content.fetch_article_markdown') as fetch:
        call_command('fetch_full_content', '--max-retries', '3', '--limit', '10')

    fetch.assert_not_called()


@pytest.mark.django_db
def test_fetch_full_content_command_failure_increments_retry_count(src, cat):
    news = _news(src, cat, full_content_fetch_status='failed', full_content_retry_count=1)

    with patch('api.management.commands.fetch_full_content.fetch_article_markdown', side_effect=RuntimeError('timeout')):
        call_command('fetch_full_content', '--limit', '1')

    news.refresh_from_db()
    assert news.full_content == ''
    assert news.full_content_retry_count == 2
    assert news.full_content_fetch_status == 'network_error'
    assert 'timeout' in news.full_content_fetch_error
