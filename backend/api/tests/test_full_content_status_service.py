import pytest
from django.utils import timezone

from api.models import Category, News, Source
from api.services.article_fetcher import FetchError, FetchResult
from api.services.full_content_status import (
    classify_fetch_error,
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
