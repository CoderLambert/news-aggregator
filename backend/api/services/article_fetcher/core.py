from __future__ import annotations

from .providers import default_providers
from .site_rules import get_site_rule
from .types import ArticleProvider, FetchError, FetchResult
from .validators import validate_markdown


def fetch_article_markdown(
    url: str,
    expected_title: str | None = None,
    summary: str | None = None,
    providers: list[ArticleProvider] | None = None,
) -> FetchResult:
    """Fetch real article Markdown via provider chain.

    Only returns when a provider produced content that passes validation.
    Raises FetchError with provider failures otherwise. The caller decides
    whether to persist; never create generated fallback content here.
    """
    chain = providers or default_providers()
    failures: list[FetchResult] = []

    for provider in chain:
        try:
            try:
                result = provider.fetch(url, expected_title=expected_title, summary=summary)
            except TypeError:
                # Backward-compatible for tests/simple custom providers.
                result = provider.fetch(url, expected_title=expected_title)
        except Exception as exc:
            failures.append(FetchResult(ok=False, provider=provider.name, url=url, error=str(exc)))
            continue

        if not result.ok:
            if result.provider == 'hackernews_api' and result.error == 'external_hn_story':
                external_url = (result.metadata or {}).get('external_url')
                if external_url and external_url != url:
                    url = external_url
                    failures.append(result)
                    continue
            failures.append(result)
            continue

        validation = validate_markdown(
            result.markdown,
            expected_title=expected_title,
            extracted_title=result.title,
            url=url,
            canonical_url=result.canonical_url,
            summary=summary,
            min_chars=_min_chars_for_url(url),
        )
        if not validation.ok:
            # Task 7: include quality report fields in validation failure
            failures.append(FetchResult(
                ok=False,
                provider=result.provider,
                url=result.url or url,
                title=result.title,
                canonical_url=result.canonical_url,
                markdown=result.markdown,
                quality_score=validation.score,
                error='validation_failed:' + ','.join(validation.reasons),
                validation_reasons=list(validation.reasons),
                content_length=len(result.markdown),
                extractor=getattr(result, 'extractor', ''),
            ))
            continue

        # Task 7: enrich success result with content_length and extractor
        result.quality_score = max(result.quality_score, validation.score)
        result.content_length = len(result.markdown)
        if not result.extractor:
            result.extractor = result.provider
        return result

    raise FetchError('全部真实原文抓取方式失败，未写入 full_content。', failures=failures)


def _min_chars_for_url(url: str) -> int:
    rule = get_site_rule(url)
    return rule.min_length if rule else 300


__all__ = ['FetchError', 'FetchResult', 'fetch_article_markdown']
