from __future__ import annotations

from django.conf import settings

from .providers import ScrapySubprocessProvider, _research_fetch_guard, default_providers
from .safe_http import UnsafeURL, validate_public_url
from .site_rules import get_site_rule
from .types import ArticleProvider, FetchError, FetchResult
from .validators import validate_markdown


def fetch_article_markdown(
    url: str,
    expected_title: str | None = None,
    summary: str | None = None,
    providers: list[ArticleProvider] | None = None,
    execution_guard=None,
) -> FetchResult:
    """Fetch real article Markdown via provider chain.

    Only returns when a provider produced content that passes validation.
    Raises FetchError with provider failures otherwise. The caller decides
    whether to persist; never create generated fallback content here.
    """
    chain = providers or default_providers()
    if settings.DJANGO_ENV == 'production':
        try:
            validate_public_url(url)
        except UnsafeURL as exc:
            raise FetchError(
                '全部真实原文抓取方式失败，未写入 full_content。',
                failures=[FetchResult(ok=False, provider='safe_http', url=url, error=str(exc))],
            ) from None

    failures: list[FetchResult] = []

    for provider in chain:
        if execution_guard is not None:
            execution_guard()
            # A detached subprocess cannot receive this worker's cancellation
            # fence. Keep it available to ordinary fetches, but not research.
            if isinstance(provider, ScrapySubprocessProvider):
                continue
        token = _research_fetch_guard.set(execution_guard)
        try:
            try:
                try:
                    result = provider.fetch(url, expected_title=expected_title, summary=summary)
                except TypeError:
                    # Backward-compatible for tests/simple custom providers.
                    result = provider.fetch(url, expected_title=expected_title)
            except Exception as exc:
                if execution_guard is not None:
                    execution_guard()
                failures.append(FetchResult(ok=False, provider=provider.name, url=url, error=str(exc)))
                continue
        finally:
            _research_fetch_guard.reset(token)
        if execution_guard is not None:
            execution_guard()

        if not result.ok:
            if result.provider == 'hackernews_api' and result.error == 'external_hn_story':
                external_url = (result.metadata or {}).get('external_url')
                if external_url and external_url != url:
                    if settings.DJANGO_ENV == 'production':
                        try:
                            validate_public_url(external_url)
                        except UnsafeURL as exc:
                            failures.append(FetchResult(
                                ok=False,
                                provider='safe_http',
                                url=url,
                                error=str(exc),
                            ))
                            break
                    url = external_url
                    failures.append(result)
                    continue
            failures.append(result)
            continue

        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        is_trusted_feed_body = (
            result.provider == 'leiphone_feed'
            and metadata.get('trusted_full_article_source') == 'rss_description'
        )
        validation_summary = None if is_trusted_feed_body else summary
        validation = validate_markdown(
            result.markdown,
            expected_title=expected_title,
            extracted_title=result.title,
            url=url,
            canonical_url=result.canonical_url,
            summary=validation_summary,
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
