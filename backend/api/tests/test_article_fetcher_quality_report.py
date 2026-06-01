import pytest

from api.services.article_fetcher import FetchError, FetchResult, fetch_article_markdown


class _ShortProvider:
    name = 'shorty'

    def fetch(self, url, expected_title=None, summary=None):
        return FetchResult(
            ok=True,
            provider=self.name,
            url=url,
            title=expected_title or '',
            markdown='Short summary only.',
            extractor='unit-rule',
        )


class _WorkingProvider:
    name = 'quality-provider'

    def fetch(self, url, expected_title=None, summary=None):
        markdown = (expected_title or 'Example') + '\n\n' + ('Real paragraph with enough words. ' * 60)
        return FetchResult(ok=True, provider=self.name, url=url, title=expected_title or '', markdown=markdown)


def test_fetch_result_quality_fields_have_backward_compatible_defaults():
    result = FetchResult(ok=True, provider='legacy')

    assert result.validation_reasons == []
    assert result.content_length == 0
    assert result.extractor == ''


def test_fetch_result_keeps_validation_reasons_and_content_length_on_failure():
    with pytest.raises(FetchError) as raised:
        fetch_article_markdown(
            'https://example.com/short',
            expected_title='Short Article',
            summary='Short summary only.',
            providers=[_ShortProvider()],
        )

    failure = raised.value.failures[0]
    assert failure.provider == 'shorty'
    assert failure.validation_reasons
    assert 'too_short' in failure.validation_reasons
    assert failure.content_length == len('Short summary only.')
    assert failure.extractor == 'unit-rule'


def test_fetch_article_markdown_records_content_length_and_extractor_on_success():
    result = fetch_article_markdown(
        'https://example.com/full',
        expected_title='Example Article',
        providers=[_WorkingProvider()],
    )

    assert result.ok is True
    assert result.content_length == len(result.markdown)
    assert result.extractor == 'quality-provider'
