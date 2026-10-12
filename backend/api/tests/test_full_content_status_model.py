import pytest
from django.utils import timezone

from api.models import Category, News, Source
from api.serializers import NewsDetailSerializer, NewsListSerializer


@pytest.fixture
def source(db):
    return Source.objects.create(name='StatusSource', url='https://example.com', language='en')


@pytest.fixture
def category(db):
    return Category.objects.create(name='状态测试', slug='status-test')


@pytest.fixture
def news(source, category):
    return News.objects.create(
        title='Status test article',
        content='Short summary',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://example.com/status-test',
    )


@pytest.mark.django_db
def test_news_has_full_content_fetch_status_defaults(news):
    assert news.full_content_fetch_status == 'pending'
    assert news.full_content_fetch_error == ''
    assert news.full_content_fetch_provider == ''
    assert news.full_content_quality_score is None
    assert news.full_content_retry_count == 0
    assert news.last_full_content_attempt is None


@pytest.mark.django_db
def test_full_content_fetch_status_choices_include_expected_values(news):
    choices = dict(News.FULL_CONTENT_STATUS_CHOICES)
    assert set(choices) == {
        'pending',
        'fetching',
        'success',
        'failed',
        'network_error',
        'validation_failed',
        'queued', 'rate_limited', 'blocked', 'unsupported',
    }

    for status in choices:
        news.full_content_fetch_status = status
        news.full_clean(exclude=['url'])


@pytest.mark.django_db
def test_news_serializers_expose_full_content_fetch_status_fields(news):
    news.full_content_fetch_status = 'success'
    news.full_content_fetch_error = ''
    news.full_content_fetch_provider = 'scrapy_http'
    news.full_content_quality_score = 0.91
    news.full_content_retry_count = 2
    news.last_full_content_attempt = timezone.now()
    news.save()

    expected_fields = {
        'full_content_fetch_status',
        'full_content_fetch_error',
        'full_content_fetch_provider',
        'full_content_quality_score',
        'full_content_retry_count',
        'last_full_content_attempt',
    }

    list_data = NewsListSerializer(news).data
    detail_data = NewsDetailSerializer(news).data

    assert expected_fields.issubset(list_data.keys())
    assert expected_fields.issubset(detail_data.keys())
    assert list_data['full_content_fetch_status'] == 'success'
    assert list_data['full_content_fetch_provider'] == 'scrapy_http'
    assert list_data['full_content_quality_score'] == 0.91
    assert list_data['full_content_retry_count'] == 2


@pytest.mark.django_db
def test_ingestion_schema_defaults_and_read_only_serializers(news):
    assert news.content_kind == 'unknown'
    assert news.full_content_state == 'missing'
    assert news.full_content_revision == 0
    assert news.full_content_provenance == {}
    assert news.full_content_next_attempt_at is None
    assert news.full_content_priority == 0
    assert news.full_content_error_code == ''
    for serializer in (NewsListSerializer, NewsDetailSerializer):
        data = serializer(news).data
        assert data['full_content_state'] == 'missing'
        assert data['full_content_revision'] == 0
        assert data['content_kind'] == 'unknown'
        assert 'full_content_provenance' not in data
        assert serializer().fields['full_content_state'].read_only
    assert 'full_content' not in NewsListSerializer(news).data


@pytest.mark.django_db
def test_availability_matches_database_and_survives_refresh_failure(news):
    from api.services.full_content_status import has_full_content, filter_readable_full_content
    for state, body, status, expected in [
        ('missing', 'Quarantined text', 'success', False),
        ('legacy', ' \t\n\r\v\f ', 'success', False),
        ('complete', '', 'success', False),
        ('legacy', 'Readable', 'rate_limited', True),
        ('complete', 'Readable', 'network_error', True),
    ]:
        News.objects.filter(pk=news.pk).update(
            full_content_state=state, full_content=body, full_content_fetch_status=status,
        )
        news.refresh_from_db()
        assert has_full_content(news) is expected
        assert filter_readable_full_content(News.objects.filter(pk=news.pk)).exists() is expected
