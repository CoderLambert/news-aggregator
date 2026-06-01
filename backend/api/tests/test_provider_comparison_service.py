from django.utils import timezone
import pytest
import uuid

from api.models import Category, News, ProviderComparison, Source
from api.services.article_fetcher.comparison import compare_providers, comparison_metrics, retest_comparison, validate_comparison_url
from api.services.article_fetcher.types import FetchResult


@pytest.fixture
def news(db):
    category = Category.objects.create(name='Provider Test', slug='provider-test')
    source = Source.objects.create(name='Provider Source', url='https://example.com')
    return News.objects.create(
        title='Expected Provider Title',
        content='This summary must never be stored as fallback markdown.',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://example.com/provider-article',
        full_content='ORIGINAL FULL CONTENT MUST STAY',
    )


class SuccessfulProvider:
    name = 'success_provider'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title='Fetched title',
            canonical_url='https://example.com/canonical',
            markdown='REAL MARKDOWN FROM PROVIDER',
            quality_score=0.91,
            content_length=len('REAL MARKDOWN FROM PROVIDER'),
            extractor='mock_extractor',
            metadata={'note': 'ok'},
        )


class FailingProvider:
    name = 'failing_provider'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=False,
            provider=self.name,
            url=url,
            title='Failure title',
            markdown='',
            quality_score=0.1,
            error='network down',
            validation_reasons=['network'],
        )


class LegacyProvider:
    name = 'legacy_provider'

    def fetch(self, url, expected_title=None):
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title=expected_title or '',
            markdown='LEGACY PROVIDER MARKDOWN',
            quality_score=0.7,
        )


def test_compare_providers_persists_real_provider_results_without_touching_news(news):
    run_id, comparisons = compare_providers(news=news, providers=[SuccessfulProvider(), FailingProvider()])

    assert run_id
    assert len(comparisons) == 2
    assert ProviderComparison.objects.count() == 2

    success = ProviderComparison.objects.get(provider='success_provider')
    assert success.run_id == run_id
    assert success.news == news
    assert success.url == news.url
    assert success.expected_title == news.title
    assert success.summary == news.content
    assert success.ok is True
    assert success.title == 'Fetched title'
    assert success.canonical_url == 'https://example.com/canonical'
    assert success.markdown == 'REAL MARKDOWN FROM PROVIDER'
    assert success.quality_score == 0.91
    assert success.content_length == len('REAL MARKDOWN FROM PROVIDER')
    assert success.extractor == 'mock_extractor'
    assert success.metadata == {'note': 'ok'}

    failure = ProviderComparison.objects.get(provider='failing_provider')
    assert failure.ok is False
    assert failure.markdown == ''
    assert failure.error == 'network down'
    assert failure.validation_reasons == ['network']

    news.refresh_from_db()
    assert news.full_content == 'ORIGINAL FULL CONTENT MUST STAY'


def test_compare_providers_supports_url_only_and_legacy_provider_signature(db):
    run_id, comparisons = compare_providers(
        url='https://github.com/example/standalone',
        expected_title='Standalone Title',
        summary='Standalone summary',
        providers=[LegacyProvider()],
    )

    assert run_id
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.news is None
    assert comparison.url == 'https://github.com/example/standalone'
    assert comparison.provider == 'legacy_provider'
    assert comparison.markdown == 'LEGACY PROVIDER MARKDOWN'
    assert comparison.ok is True


def test_compare_providers_rejects_url_only_private_and_unadapted_urls(db):
    with pytest.raises(ValueError, match='Private or local'):
        compare_providers(url='http://127.0.0.1:8000/internal', providers=[LegacyProvider()])

    with pytest.raises(ValueError, match='adapted'):
        compare_providers(url='https://example.com/standalone', providers=[LegacyProvider()])

    assert ProviderComparison.objects.count() == 0


def test_validate_comparison_url_rejects_domains_resolving_to_private_ips(monkeypatch, db):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.socket.getaddrinfo',
        lambda *args, **kwargs: [(None, None, None, '', ('127.0.0.1', 443))],
    )

    with pytest.raises(ValueError, match='Private or local'):
        validate_comparison_url('https://github.com/example/rebound')


def test_retest_comparison_revalidates_standalone_url(db):
    comparison = ProviderComparison.objects.create(
        run_id=uuid.uuid4(),
        url='http://127.0.0.1:8000/internal',
        provider='legacy_provider',
        ok=False,
        error='legacy bad row',
    )

    with pytest.raises(ValueError, match='Private or local'):
        retest_comparison(comparison)


def test_compare_providers_rejects_partially_unknown_provider_names(monkeypatch, news):
    monkeypatch.setattr(
        'api.services.article_fetcher.comparison.default_providers',
        lambda: [SuccessfulProvider(), FailingProvider()],
    )

    with pytest.raises(ValueError, match='Unknown provider'):
        compare_providers(news=news, provider_names=['success_provider', 'typo_provider'])

    assert ProviderComparison.objects.count() == 0


def test_comparison_metrics_include_quality_and_duration_averages(db):
    ProviderComparison.objects.create(
        run_id=uuid.uuid4(),
        url='https://example.com/ok',
        provider='ok',
        ok=True,
        markdown='ok markdown',
        quality_score=0.9,
        content_length=11,
        elapsed_ms=100,
    )
    ProviderComparison.objects.create(
        run_id=uuid.uuid4(),
        url='https://example.com/fail',
        provider='fail',
        ok=False,
        quality_score=0.3,
        error='boom',
        elapsed_ms=300,
    )

    metrics = comparison_metrics()

    assert metrics == {
        'total': 2,
        'success': 1,
        'failure': 1,
        'success_rate': 0.5,
        'avg_quality_score': 0.6,
        'avg_duration_ms': 200.0,
    }
