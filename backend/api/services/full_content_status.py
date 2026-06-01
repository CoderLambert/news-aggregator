"""Full-content fetch status tracking service.

Keeps all status-related mutations in one place so views and management
commands don't have to hand-write the same save(update_fields=[...]) calls.

Every function uses save(update_fields=[...]) to avoid clobbering unrelated
fields (e.g. translation status, suggested questions).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils.timezone import now as tz_now

if TYPE_CHECKING:
    from api.models import News
    from api.services.article_fetcher.types import FetchResult

# Error keywords that signal network-level failures
_NETWORK_ERROR_KEYWORDS = (
    'timeout',
    'timed out',
    'reset',
    'connection',
    'dns',
    'name resolution',
    'network',
    'ssl',
    'refused',
    'unreachable',
    'temporarily unavailable',
)

# Validation failure indicators
_VALIDATION_KEYWORDS = (
    'validation_failed',
    '短内容',
    'too_short',
    'summary_sized',
    'title_mismatch',
    'canonical_domain_mismatch',
    'too_much_page_chrome',
)

logger = logging.getLogger(__name__)


def mark_fetching(news: News) -> None:
    """Mark that a full-content fetch attempt has started."""
    news.full_content_fetch_status = 'fetching'
    news.full_content_fetch_error = ''
    news.last_full_content_attempt = tz_now()
    news.save(
        update_fields=[
            'full_content_fetch_status',
            'full_content_fetch_error',
            'last_full_content_attempt',
        ],
    )


def mark_success(news: News, result: FetchResult) -> None:
    """Record a successful full-content fetch with provider and quality info."""
    news.full_content_fetch_status = 'success'
    news.full_content_fetch_error = ''
    news.full_content_fetch_provider = result.provider
    news.full_content_quality_score = (
        result.quality_score if result.quality_score > 0 else None
    )
    news.last_full_content_attempt = tz_now()
    news.save(
        update_fields=[
            'full_content_fetch_status',
            'full_content_fetch_error',
            'full_content_fetch_provider',
            'full_content_quality_score',
            'last_full_content_attempt',
        ],
    )


def mark_failed(
    news: News,
    error: Exception | str,
    status: str | None = None,
    provider: str = '',
) -> None:
    """Record a failed full-content fetch attempt.

    Increments retry_count.  Uses the classified status if provided,
    otherwise defaults to 'failed'.
    """
    error_text = str(error) if isinstance(error, Exception) else str(error)

    if status is None:
        status = classify_fetch_error(error)

    news.full_content_fetch_status = status
    news.full_content_fetch_error = error_text
    if provider:
        news.full_content_fetch_provider = provider
    news.full_content_retry_count = news.full_content_retry_count + 1
    news.last_full_content_attempt = tz_now()
    news.save(
        update_fields=[
            'full_content_fetch_status',
            'full_content_fetch_error',
            'full_content_fetch_provider',
            'full_content_retry_count',
            'last_full_content_attempt',
        ],
    )


def classify_fetch_error(error_or_result) -> str:
    """Classify a FetchError or Exception into a status string.

    Returns one of: 'network_error', 'validation_failed', 'failed'.
    """
    # Extract error text from FetchError or Exception
    if hasattr(error_or_result, 'message'):
        error_text = str(error_or_result.message)
    else:
        error_text = str(error_or_result)

    # Also check metadata for validation reasons
    validation_reasons = []
    if hasattr(error_or_result, 'metadata'):
        validation_reasons = error_or_result.metadata.get('validation_reasons', [])
    if hasattr(error_or_result, 'error'):
        error_text = error_or_result.error or error_text

    text = (error_text + ' ' + ' '.join(validation_reasons)).lower()

    for keyword in _VALIDATION_KEYWORDS:
        if keyword.lower() in text:
            return 'validation_failed'

    for keyword in _NETWORK_ERROR_KEYWORDS:
        if keyword.lower() in text:
            return 'network_error'

    return 'failed'
