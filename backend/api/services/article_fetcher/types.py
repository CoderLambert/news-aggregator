from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Protocol


MAX_FETCH_DIAGNOSTIC_LENGTH = 1000
_SAFE_NAME = re.compile(r'[^a-z0-9_.-]+')
_SAFE_REASON = re.compile(r'^[a-z0-9_:-]{1,80}$')
_HTTP_STATUS = re.compile(r'\bHTTP\s+(\d{3})\b', re.IGNORECASE)


@dataclass(frozen=True)
class FullContentCandidate:
    source_key: str
    source_item_id: str
    target_url: str
    retrieved_from_url: str
    declared_canonical_url: str | None
    title: str
    content_kind: str
    body_field: str
    content_format: str
    declared_completeness: str
    raw_content: str
    source_modified_at: datetime | None
    source_version: str | None
    request_started_at: datetime
    expected_revision: int | None = None
    request_chain: tuple[str, ...] = ()


@dataclass
class FetchResult:
    ok: bool
    provider: str
    url: str = ''
    title: str = ''
    canonical_url: str = ''
    markdown: str = ''
    quality_score: float = 0.0
    error: str = ''
    metadata: dict = field(default_factory=dict)
    # Task 7: quality report fields (backward compatible defaults)
    validation_reasons: list[str] = field(default_factory=list)
    content_length: int = 0
    extractor: str = ''
    candidate: FullContentCandidate | None = None
    error_code: str = ''
    http_status: int | None = None
    retry_after_at: datetime | None = None
    retryable: bool = False
    scope_keys: tuple[str, ...] = ()
    fetch_event_id: int | None = None


class ArticleProvider(Protocol):
    name: str

    def fetch(self, url: str, expected_title: str | None = None, summary: str | None = None) -> FetchResult:
        ...


class FetchError(Exception):
    def __init__(self, message: str, failures: list[FetchResult] | None = None):
        super().__init__(message)
        self.failures = failures or []
        terminal = {'rate_limited', 'budget_deferred', 'auth_required', 'access_blocked', 'not_found'}
        control = next((f for f in self.failures if f.error_code in terminal), None)
        if control is None:
            # Disabled/not-applicable readers do not erase an earlier real
            # extractor's content-quality or network failure.
            control = next((f for f in reversed(self.failures) if f.error_code != 'not_applicable'), None)
        if control is None:
            control = self.failures[-1] if self.failures else None
        self.error_code = control.error_code if control else ''
        self.http_status = control.http_status if control else None
        self.retry_after_at = control.retry_after_at if control else None
        self.retryable = control.retryable if control else False
        self.scope_keys = control.scope_keys if control else ()

    def __str__(self) -> str:
        message = super().__str__()
        if not self.failures:
            return message
        return f'{message} {fetch_error_diagnostic(self)}'


def _safe_name(value: str, fallback: str) -> str:
    cleaned = _SAFE_NAME.sub('_', (value or '').strip().lower()).strip('_.-')
    return (cleaned or fallback)[:64]


def fetch_failure_code(failure: FetchResult | Exception | str) -> str:
    """Return a bounded, non-sensitive reason code for one provider failure."""
    code = getattr(failure, 'error_code', '')
    if isinstance(code, str) and _SAFE_REASON.fullmatch(code):
        return code
    error = getattr(failure, 'error', '') or str(failure)
    lowered = str(error).strip().lower()
    status_match = _HTTP_STATUS.search(lowered)
    if status_match:
        return f'http_{status_match.group(1)}'

    stable_transport_codes = {
        'safe http request failed': 'transport_error',
        'safe http response read failed': 'response_read_error',
        'unable to connect to validated public address': 'connection_failed',
    }
    if lowered in stable_transport_codes:
        return stable_transport_codes[lowered]

    reasons = getattr(failure, 'validation_reasons', None) or []
    if lowered.startswith('validation_failed') or reasons:
        safe_reasons = [
            reason.lower()
            for reason in reasons
            if isinstance(reason, str) and _SAFE_REASON.fullmatch(reason.lower())
        ][:6]
        if not safe_reasons and ':' in lowered:
            safe_reasons = [
                reason
                for reason in lowered.split(':', 1)[1].split(',')
                if _SAFE_REASON.fullmatch(reason)
            ][:6]
        suffix = ':'.join(safe_reasons)
        return f'validation_failed:{suffix}' if suffix else 'validation_failed'

    exact_codes = {
        'external_hn_story',
        'empty_feed_description',
        'empty_hn_self_post',
        'feed_item_not_found',
        'invalid_hn_item',
        'jina_policy_disabled',
        'jina returned empty content',
        'not_github_repo',
        'not_hackernews_item',
        'not_leiphone_article',
        'not_venturebeat_article',
        'unsafe_transport_disabled',
        'unsupported_trusted_news_url',
        'unsupported_venturebeat_url',
    }
    if lowered in exact_codes:
        return lowered.replace(' ', '_')
    if 'timed out' in lowered or 'timeout' in lowered or 'deadline exceeded' in lowered:
        return 'timeout'
    if 'dns' in lowered or 'resolve' in lowered or 'name resolution' in lowered:
        return 'dns_error'
    if 'ssl' in lowered or 'certificate' in lowered or 'tls' in lowered:
        return 'tls_error'
    if 'connection reset' in lowered:
        return 'connection_reset'
    if 'connection refused' in lowered:
        return 'connection_refused'
    if 'unreachable' in lowered:
        return 'host_unreachable'
    if 'private or local' in lowered or 'url credentials' in lowered or 'only http' in lowered:
        return 'unsafe_url'
    return 'provider_error'


def fetch_error_diagnostic(error: Exception | str) -> str:
    """Format provider failures without persisting URLs, bodies, or credentials."""
    failures = getattr(error, 'failures', None) or []
    if failures:
        entries = [
            f'{_safe_name(getattr(failure, "provider", ""), "provider")}:{fetch_failure_code(failure)}'
            for failure in failures
        ]
        return ('provider_failures[' + ','.join(entries) + ']')[:MAX_FETCH_DIAGNOSTIC_LENGTH]

    error_class = _safe_name(type(error).__name__ if isinstance(error, Exception) else 'error', 'error')
    return f'{error_class}:{fetch_failure_code(error)}'[:MAX_FETCH_DIAGNOSTIC_LENGTH]


def fetch_error_provider(error: Exception | str) -> str:
    failures = getattr(error, 'failures', None) or []
    if not failures:
        return ''
    return _safe_name(getattr(failures[-1], 'provider', ''), 'provider')



def transport_failure(error, *, provider, url=''):
    status = getattr(error, 'http_status', None) or getattr(error, 'code', None)
    code = getattr(error, 'error_code', '')
    if not code:
        code = ('rate_limited' if status == 429 else 'auth_required' if status == 401 else
                'access_blocked' if status == 403 else 'not_found' if status in {404, 410} else
                'upstream_5xx' if status and status >= 500 else
                'network_timeout' if fetch_failure_code(error) == 'timeout' else 'network_error')
    return FetchResult(ok=False, provider=provider, url=url, error=fetch_error_diagnostic(error),
                       error_code=code, http_status=status,
                       retry_after_at=getattr(error, 'retry_after_at', None),
                       retryable=code in {'rate_limited', 'upstream_5xx', 'network_timeout', 'network_error'},
                       scope_keys=tuple(getattr(error, 'scope_keys', ())))
