from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import Category, News, Source
from api.services.article_fetcher import FetchError, FetchResult
from api.services.full_content_status import (
    classify_fetch_error,
    claim_fetch,
    mark_failed,
    mark_fetching,
    mark_success,
)


@pytest.fixture
def source(db):
    return Source.objects.create(name='ServiceStatusSource', url='https://example.com', language='en')


@pytest.fixture
def category(db):
    return Category.objects.create(name='服务状态测试', slug='service-status-test')


@pytest.fixture
def news(source, category):
    return News.objects.create(
        title='Service status test article',
        content='Short summary',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://example.com/service-status-test',
    )


@pytest.mark.django_db
def test_mark_fetching_records_attempt_and_clears_previous_error(news):
    news.full_content_fetch_status = 'failed'
    news.full_content_fetch_error = 'old error'
    news.full_content_fetch_provider = 'old_provider'
    news.save()

    mark_fetching(news)

    news.refresh_from_db()
    assert news.full_content_fetch_status == 'fetching'
    assert news.full_content_fetch_error == ''
    assert news.last_full_content_attempt is not None
    assert news.full_content_fetch_provider == 'old_provider'


@pytest.mark.django_db
def test_mark_success_records_provider_score_and_timestamp(news):
    result = FetchResult(
        ok=True,
        provider='scrapy_cli',
        url=news.url,
        title=news.title,
        markdown='REAL ARTICLE BODY',
        quality_score=0.88,
    )

    mark_success(news, result)

    news.refresh_from_db()
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_fetch_error == ''
    assert news.full_content_fetch_provider == 'scrapy_cli'
    assert news.full_content_quality_score == 0.88
    assert news.last_full_content_attempt is not None


@pytest.mark.django_db
def test_mark_success_clears_translation_only_when_the_original_body_changes(news):
    news.full_content = 'old body'
    news.full_content_zh = 'old translation'
    news.full_content_zh_fetched_at = timezone.now()
    news.save(update_fields=['full_content', 'full_content_zh', 'full_content_zh_fetched_at'])
    result = FetchResult(
        ok=True,
        provider='scrapy_cli',
        url=news.url,
        title=news.title,
        markdown='new body',
        quality_score=0.9,
    )

    mark_success(news, result, full_content='new body')

    news.refresh_from_db()
    assert news.full_content == 'new body'
    assert news.full_content_zh == ''
    assert news.full_content_zh_fetched_at is None


@pytest.mark.django_db
def test_mark_success_keeps_translation_when_the_original_body_is_unchanged(news):
    news.full_content = 'same body'
    news.full_content_zh = 'valid translation'
    fetched_at = timezone.now()
    news.full_content_zh_fetched_at = fetched_at
    news.save(update_fields=['full_content', 'full_content_zh', 'full_content_zh_fetched_at'])
    result = FetchResult(
        ok=True,
        provider='scrapy_cli',
        url=news.url,
        title=news.title,
        markdown='same body',
        quality_score=0.9,
    )

    mark_success(news, result, full_content='same body')

    news.refresh_from_db()
    assert news.full_content == 'same body'
    assert news.full_content_zh == 'valid translation'
    assert news.full_content_zh_fetched_at == fetched_at


@pytest.mark.django_db
def test_mark_failed_increments_retry_count_and_records_error(news):
    news.full_content_retry_count = 1
    news.save(update_fields=['full_content_retry_count'])

    mark_failed(news, RuntimeError('connection reset by peer'), status='network_error', provider='jina')

    news.refresh_from_db()
    assert news.full_content_fetch_status == 'network_error'
    assert news.full_content_fetch_error == 'connection reset by peer'
    assert news.full_content_fetch_provider == 'jina'
    assert news.full_content_retry_count == 2
    assert news.last_full_content_attempt is not None


@pytest.mark.django_db
def test_reclaimed_fetch_fences_out_late_success_and_failure(news):
    first_started = timezone.now() - timedelta(minutes=10)
    first_worker = News.objects.get(pk=news.pk)
    with patch('api.services.full_content_status.tz_now', return_value=first_started):
        assert claim_fetch(first_worker)

    second_worker = News.objects.get(pk=news.pk)
    second_started = first_started + timedelta(minutes=6)
    with patch('api.services.full_content_status.tz_now', return_value=second_started):
        assert claim_fetch(second_worker)

    stale_result = FetchResult(
        ok=True,
        provider='old_worker',
        url=news.url,
        markdown='STALE BODY MUST NOT BE SAVED',
        quality_score=0.5,
    )
    assert not mark_success(first_worker, stale_result, full_content=stale_result.markdown)
    assert not mark_failed(first_worker, RuntimeError('late failure'))

    news.refresh_from_db()
    assert news.full_content == ''
    assert news.full_content_fetch_status == 'fetching'
    assert news.full_content_retry_count == 0

    current_result = FetchResult(
        ok=True,
        provider='current_worker',
        url=news.url,
        markdown='CURRENT BODY',
        quality_score=0.9,
    )
    assert mark_success(second_worker, current_result, full_content=current_result.markdown)
    news.refresh_from_db()
    assert news.full_content == 'CURRENT BODY'
    assert news.full_content_fetch_status == 'success'
    assert news.full_content_fetch_provider == 'current_worker'


@pytest.mark.parametrize(
    'message',
    [
        'request timeout',
        'timed out waiting for response',
        'connection reset by peer',
        'DNS name resolution failed',
        'SSL handshake failed',
        'connection refused',
        'host unreachable',
        'temporarily unavailable',
    ],
)
def test_classify_fetch_error_network_errors(message):
    assert classify_fetch_error(FetchError(message)) == 'network_error'


@pytest.mark.parametrize(
    'message',
    [
        'validation_failed: short content',
        'too_short content from provider',
        'summary_sized content detected',
        'title_mismatch detected',
        'canonical_domain_mismatch detected',
        'too_much_page_chrome detected',
    ],
)
def test_classify_fetch_error_validation_failures(message):
    assert classify_fetch_error(FetchError(message)) == 'validation_failed'


def test_classify_fetch_error_uses_result_error_and_validation_reasons():
    result = FetchResult(
        ok=False,
        provider='jina',
        error='provider returned bad body',
        metadata={'validation_reasons': ['summary_sized']},
    )

    assert classify_fetch_error(result) == 'validation_failed'


def test_classify_fetch_error_defaults_to_failed():
    assert classify_fetch_error(RuntimeError('unexpected parser bug')) == 'failed'
