from __future__ import annotations

import time
import inspect
from dataclasses import replace

from api.services.request_budget import BudgetDeferred
from .execution import execution_scope, current_execution, ExecutionStopped

from django.conf import settings

from .providers import ScrapySubprocessProvider, _research_fetch_guard, default_providers
from .safe_http import UnsafeURL, validate_public_url
from .site_rules import get_site_rule
from .types import ArticleProvider, FetchError, FetchResult, transport_failure
from .validators import validate_markdown, validate_candidate


def _fetch_article_markdown(
    url: str,
    expected_title: str | None = None,
    summary: str | None = None,
    providers: list[ArticleProvider] | None = None,
    execution_guard=None,
    news=None,
) -> FetchResult:
    """Fetch real article Markdown via provider chain.

    Only returns when a provider produced content that passes validation.
    Raises FetchError with provider failures otherwise. The caller decides
    whether to persist; never create generated fallback content here.
    """
    from api.services.source_policy import retired_policy_for_url
    if retired_policy_for_url(url):
        raise FetchError('该来源已停止采集。', failures=[FetchResult(
            False, 'source_policy', url=url, error='unsupported', error_code='unsupported', retryable=False,
        )])
    from api.services.source_policy import policy_for_url
    from api.services.channel_articles import summary_only
    policy = policy_for_url(url)
    if ((policy and policy.reading_policy != 'standard') or
            (news is not None and summary_only(news))):
        raise FetchError('该频道仅使用 RSS 公开内容。', failures=[FetchResult(
            False, 'source_policy', url=url, error='rss_only', error_code='unsupported', retryable=False,
        )])
    chain = providers or default_providers(url)
    started_at = time.monotonic()
    news_id = getattr(news, 'pk', None)
    execution = current_execution.get()
    starting_requests = execution.physical_requests
    starting_statuses = len(execution.http_statuses)

    def record(result: FetchResult | None, failures: list[FetchResult]) -> None:
        if news_id is None:
            return
        from api.services.article_fetch_monitor import record_fetch_event
        execution.fetch_event_id = record_fetch_event(
            url=url,
            news_id=news_id,
            result=result,
            failures=failures,
            elapsed_ms=round((time.monotonic() - started_at) * 1000),
            physical_requests=execution.physical_requests - starting_requests,
            http_statuses=execution.http_statuses[starting_statuses:],
        )

    if settings.DJANGO_ENV == 'production':
        try:
            validate_public_url(url)
        except UnsafeURL as exc:
            if exc.error_code == 'budget_deferred':
                raise BudgetDeferred(exc.retry_after_at) from None
            failure = transport_failure(exc, provider='safe_http', url=url)
            failure.error = str(exc)  # UnsafeURL messages are fixed, non-sensitive diagnostics.
            failures = [failure]
            record(None, failures)
            raise FetchError(
                '全部真实原文抓取方式失败，未写入 full_content。',
                failures=failures,
            ) from None

    failures: list[FetchResult] = []

    for provider in chain:
        execution = current_execution.get()
        execution.check()
        if execution.requests_remaining <= 0:
            failures.append(FetchResult(False, 'execution', error='request_limit', error_code='request_limit', retryable=False))
            break
        if execution_guard is not None:
            execution_guard()
            # A detached subprocess cannot receive this worker's cancellation
            # fence. Keep it available to ordinary fetches, but not research.
            if isinstance(provider, ScrapySubprocessProvider):
                continue
        token = _research_fetch_guard.set(execution_guard)
        try:
            try:
                signature = inspect.signature(provider.fetch)
                supports_summary = 'summary' in signature.parameters or any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
                kwargs = {'summary': summary} if supports_summary else {}
                if 'news' in signature.parameters:
                    kwargs['news'] = news
                result = provider.fetch(url, expected_title=expected_title, **kwargs)
            except (BudgetDeferred, ExecutionStopped):
                raise
            except Exception as exc:
                if execution_guard is not None:
                    execution_guard()
                if getattr(exc, 'error_code', '') or getattr(exc, 'http_status', None) or getattr(exc, 'code', None):
                    result = transport_failure(exc, provider=provider.name, url=url)
                else:
                    failures.append(FetchResult(ok=False, provider=provider.name, url=url, error=str(exc)))
                    continue
        finally:
            _research_fetch_guard.reset(token)
        if execution_guard is not None:
            execution_guard()

        if not result.ok:
            if result.error_code in {'rate_limited', 'auth_required', 'access_blocked', 'not_found', 'budget_deferred', 'network_timeout', 'network_error', 'upstream_5xx', 'invalid_identity'}:
                failures.append(result)
                break
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

        if result.candidate is not None:
            expected_revision = getattr(current_execution.get(), 'expected_revision', None)
            result.candidate = replace(result.candidate, expected_revision=expected_revision)
            validation = validate_candidate(result.candidate, expected_url=url, expected_title=expected_title or '', summary=summary)
            if validation.ok:
                result.markdown = validation.markdown
            else:
                result.error_code = validation.error_code
            validation_reasons = [validation.error_code] if not validation.ok else []
        else:
            # Read-only compatibility diagnostics; mark_success requires a typed
            # candidate and can never store this unbound legacy result.
            validation = validate_markdown(
                result.markdown, expected_title=expected_title, extracted_title=result.title,
                url=url, canonical_url=result.canonical_url, summary=summary, min_chars=_min_chars_for_url(url),
            )
            validation_reasons = validation.reasons
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
                error='validation_failed:' + ','.join(validation_reasons),
                validation_reasons=list(validation_reasons),
                content_length=len(result.markdown),
                error_code=result.error_code or 'body_partial',
                extractor=getattr(result, 'extractor', ''),
            ))
            continue

        # Task 7: enrich success result with content_length and extractor
        result.quality_score = max(result.quality_score, validation.score)
        result.content_length = len(result.markdown)
        if not result.extractor:
            result.extractor = result.provider
        record(result, failures)
        result.fetch_event_id = execution.fetch_event_id
        return result

    record(None, failures)
    raise FetchError('全部真实原文抓取方式失败，未写入 full_content。', failures=failures)


def _min_chars_for_url(url: str) -> int:
    rule = get_site_rule(url)
    return rule.min_length if rule else 300


__all__ = ['FetchError', 'FetchResult', 'fetch_article_markdown']



def fetch_article_markdown(url, expected_title=None, summary=None, providers=None, execution_guard=None, news=None):
    def guard():
        if execution_guard:
            execution_guard()
        if news is not None and getattr(news, '_full_content_snapshot', None):
            from api.services.full_content_status import owns_fetch
            if not owns_fetch(news):
                raise ExecutionStopped('superseded')
    with execution_scope(guard) as execution:
        if execution.logical_url is None:
            execution.logical_url = url
            execution.expected_revision = news.full_content_revision if news is not None else None
        execution.fetch_event_id = None
        started = time.monotonic()
        starting_requests, starting_statuses = execution.physical_requests, len(execution.http_statuses)
        try:
            return _fetch_article_markdown(url, expected_title, summary, providers, guard, news)
        except Exception as error:
            if news is not None and execution.fetch_event_id is None:
                from api.services.article_fetch_monitor import record_fetch_event
                failure = transport_failure(error, provider='execution', url=url)
                execution.fetch_event_id = record_fetch_event(
                    url=url, news_id=news.pk, result=None, failures=[failure],
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    physical_requests=execution.physical_requests - starting_requests,
                    http_statuses=execution.http_statuses[starting_statuses:],
                    retry_after_at=getattr(error, 'retry_after_at', None),
                    logical_outcome=getattr(error, 'error_code', '') or 'failed')
            error.fetch_event_id = execution.fetch_event_id
            raise
