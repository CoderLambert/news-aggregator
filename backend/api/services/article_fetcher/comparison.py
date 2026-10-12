from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from uuid import UUID

from django.db.models import Avg

from api.models import News, ProviderComparison

from .providers import default_providers
from .safe_http import validate_public_url
from .site_rules import SITE_RULES, get_site_rule
from .types import ArticleProvider, FetchResult


def get_provider_chain(provider_names: list[str] | tuple[str, ...] | None = None) -> list[ArticleProvider]:
    """Return default providers, optionally filtered by provider name.

    Kept as a separate function so tests and management/API entry points can
    mock it and avoid real network access.
    """
    providers = list(default_providers())
    if not provider_names:
        return providers
    wanted = set(provider_names)
    available = {provider.name for provider in providers}
    unknown = wanted - available
    if unknown:
        raise ValueError(f'Unknown provider(s): {", ".join(sorted(unknown))}')
    return [provider for provider in providers if provider.name in wanted]


def adapted_sites() -> list[dict]:
    """Serialize Scrapy/site-rule coverage for frontend display."""
    return [
        {
            'name': rule.name,
            'domains': list(rule.domains),
            'selectors': list(rule.selectors),
            'remove_selectors': list(rule.remove_selectors),
            'title_selectors': list(rule.title_selectors),
            'min_length': rule.min_length,
        }
        for rule in SITE_RULES
    ]


def compare_providers(
    *,
    news: News | None = None,
    news_id: int | None = None,
    url: str | None = None,
    expected_title: str | None = None,
    summary: str | None = None,
    providers: Iterable[ArticleProvider] | None = None,
    provider_names: list[str] | tuple[str, ...] | None = None,
) -> tuple[UUID, list[ProviderComparison]]:
    """Run each provider independently and persist comparison rows.

    Only provider.fetch's actual markdown is stored. On failure we store an empty
    markdown unless the failing provider returned diagnostic markdown itself; no
    fallback from News.content/summary is ever synthesized. News.full_content is
    never written here.
    """
    if news_id is not None and news is None:
        news = News.objects.get(pk=news_id)

    if news is not None:
        url = url or news.url
        expected_title = expected_title if expected_title is not None else news.title
        summary = summary if summary is not None else news.content

    if not url:
        raise ValueError('news_id or url is required')

    validate_comparison_url(url, require_adapted_site=news is None)

    chain = list(providers) if providers is not None else get_provider_chain(provider_names)
    if not chain:
        if provider_names:
            raise ValueError(f'Unknown provider(s): {", ".join(provider_names)}')
        raise ValueError('No providers available')
    run_uuid = uuid.uuid4()
    comparisons: list[ProviderComparison] = []

    for provider in chain:
        started = time.monotonic()
        try:
            try:
                result = provider.fetch(url, expected_title=expected_title, summary=summary)
            except TypeError:
                result = provider.fetch(url, expected_title=expected_title)
        except Exception as exc:
            result = FetchResult(
                ok=False,
                provider=getattr(provider, 'name', provider.__class__.__name__),
                url=url,
                error=str(exc),
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        comparisons.append(_persist_result(
            run_id=run_uuid,
            news=news,
            request_url=url,
            expected_title=expected_title or '',
            summary=summary or '',
            result=result,
            elapsed_ms=elapsed_ms,
        ))

    return run_uuid, comparisons


def retest_comparison(comparison: ProviderComparison) -> tuple[UUID, list[ProviderComparison]]:
    return compare_providers(
        news=comparison.news,
        url=comparison.url,
        expected_title=comparison.expected_title,
        summary=comparison.summary,
        provider_names=[str(comparison.provider)],
    )


def validate_comparison_url(url: str, *, require_adapted_site: bool = True) -> str:
    """Validate user-supplied comparison URLs before any provider network call."""
    validate_public_url(url)

    if require_adapted_site and get_site_rule(url) is None:
        raise ValueError('URL must match an adapted Scrapy provider site')

    return url


def comparison_metrics(queryset=None) -> dict:
    qs = queryset if queryset is not None else ProviderComparison.objects.all()
    total = qs.count()
    success = qs.filter(ok=True).count()
    failure = total - success
    averages = qs.aggregate(
        avg_quality_score=Avg('quality_score'),
        avg_duration_ms=Avg('elapsed_ms'),
    )
    return {
        'total': total,
        'success': success,
        'failure': failure,
        'success_rate': (success / total) if total else 0,
        'avg_quality_score': averages['avg_quality_score'] or 0,
        'avg_duration_ms': averages['avg_duration_ms'] or 0,
    }


def _persist_result(
    *,
    run_id: UUID,
    news: News | None,
    request_url: str,
    expected_title: str,
    summary: str,
    result: FetchResult,
    elapsed_ms: int,
) -> ProviderComparison:
    metadata = result.metadata or {}
    if not isinstance(metadata, dict):
        metadata = {'value': metadata}

    markdown = result.markdown or ''
    content_length = result.content_length or len(markdown)

    return ProviderComparison.objects.create(
        run_id=run_id,
        news=news,
        url=result.url or request_url,
        expected_title=expected_title,
        summary=summary,
        provider=result.provider,
        ok=bool(result.ok),
        title=result.title or '',
        canonical_url=result.canonical_url or '',
        markdown=markdown,
        quality_score=result.quality_score,
        error=result.error or '',
        validation_reasons=list(result.validation_reasons or []),
        content_length=content_length,
        extractor=result.extractor or result.provider,
        metadata=metadata,
        elapsed_ms=elapsed_ms,
    )


__all__ = [
    'adapted_sites',
    'compare_providers',
    'comparison_metrics',
    'get_provider_chain',
    'retest_comparison',
    'validate_comparison_url',
]
