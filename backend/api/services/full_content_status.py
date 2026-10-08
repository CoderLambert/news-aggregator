"""Full-content fetch status tracking service.

Keeps status mutations in one place and uses targeted database updates so
unrelated fields (e.g. translation status and suggested questions) stay intact.
When a successful fetch changes the original body, its cached generic
translation is cleared in the same write.
Fetches claimed by :func:`claim_fetch` also fence completion writes by their
claim timestamp, preventing a worker with an expired lease from saving late.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.db.models import F, Q, TextField, Value
from django.db.models.functions import Coalesce, Replace, Trim
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

FETCH_IN_PROGRESS_TTL = timedelta(minutes=5)


def trimmed_text_expression(field_name: str):
    """Return a database expression matching Python's common whitespace trim."""
    expression = F(field_name)
    for character in ('\t', '\n', '\r', '\v', '\f'):
        expression = Replace(
            expression,
            Value(character),
            Value(''),
            output_field=TextField(),
        )
    return Coalesce(Trim(expression), Value(''), output_field=TextField())


def claim_fetch(news: News, *, force: bool = False) -> bool:
    """Atomically claim one full-content fetch for this article.

    A fresh ``fetching`` timestamp acts as a short lease. Concurrent callers
    attach to that task instead of issuing another outbound fetch; stale leases
    can be reclaimed after a worker exits unexpectedly.
    """
    now = tz_now()
    stale_before = now - FETCH_IN_PROGRESS_TTL
    query = news.__class__.objects.filter(pk=news.pk).annotate(
        _trimmed_body=trimmed_text_expression('full_content'),
    )
    if not force:
        query = query.filter(_trimmed_body='')
    active_lease = Q(full_content_fetch_status='fetching') & Q(
        last_full_content_attempt__gte=stale_before,
    )
    claimed = query.exclude(active_lease).update(
        full_content_fetch_status='fetching',
        full_content_fetch_error='',
        last_full_content_attempt=now,
    ) == 1
    # Keep the claimed timestamp on this in-memory instance as a fencing token.
    # Completion writes must still own this exact lease after the network call.
    news._full_content_fetch_claimed = True
    news._full_content_fetch_lease = now if claimed else None
    return claimed


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


def mark_success(
    news: News,
    result: FetchResult,
    *,
    full_content: str | None = None,
    full_content_fetched_at: datetime | None = None,
    full_content_backfill_source: str | None = None,
    full_content_backfill_at: datetime | None = None,
) -> bool:
    """Record a successful fetch and optionally store its body in the same write.

    When ``news`` came from :func:`claim_fetch`, the update is fenced by the
    lease timestamp. A worker whose lease expired while it was fetching cannot
    overwrite a newer worker's body or success metadata. If the stored body
    changes, its generic Chinese translation is invalidated atomically.
    """
    completed_at = tz_now()
    updates = {
        'full_content_fetch_status': 'success',
        'full_content_fetch_error': '',
        'full_content_fetch_provider': result.provider,
        'full_content_quality_score': (
            result.quality_score if result.quality_score > 0 else None
        ),
        'last_full_content_attempt': completed_at,
    }
    body_changed = full_content is not None and full_content != news.full_content
    if full_content is not None:
        updates['full_content'] = full_content
        updates['full_content_fetched_at'] = full_content_fetched_at or completed_at
        if body_changed:
            # A translation is valid only for the source body it was made from.
            # Keep it on fetch failures and unchanged refreshes; invalidate it
            # atomically with a successful body change.
            updates['full_content_zh'] = ''
            updates['full_content_zh_fetched_at'] = None
    if full_content_backfill_source is not None:
        updates['full_content_backfill_source'] = full_content_backfill_source
    if full_content_backfill_at is not None:
        updates['full_content_backfill_at'] = full_content_backfill_at

    lease = getattr(news, '_full_content_fetch_lease', None)
    if getattr(news, '_full_content_fetch_claimed', False):
        if lease is None:
            return False
        saved = news.__class__.objects.filter(
            pk=news.pk,
            full_content_fetch_status='fetching',
            last_full_content_attempt=lease,
        ).update(**updates) == 1
        news._full_content_fetch_lease = None
        if not saved:
            news.refresh_from_db()
            return False
        for field, value in updates.items():
            setattr(news, field, value)
        return True

    for field, value in updates.items():
        setattr(news, field, value)
    news.save(update_fields=list(updates))
    return True


def mark_failed(
    news: News,
    error: Exception | str,
    status: str | None = None,
    provider: str = '',
) -> bool:
    """Record a failed full-content fetch attempt.

    Increments retry_count.  Uses the classified status if provided,
    otherwise defaults to 'failed'.
    """
    error_text = str(error) if isinstance(error, Exception) else str(error)

    if status is None:
        status = classify_fetch_error(error)

    updates = {
        'full_content_fetch_status': status,
        'full_content_fetch_error': error_text,
        'full_content_retry_count': F('full_content_retry_count') + 1,
        'last_full_content_attempt': tz_now(),
    }
    if provider:
        updates['full_content_fetch_provider'] = provider

    lease = getattr(news, '_full_content_fetch_lease', None)
    if getattr(news, '_full_content_fetch_claimed', False):
        if lease is None:
            return False
        saved = news.__class__.objects.filter(
            pk=news.pk,
            full_content_fetch_status='fetching',
            last_full_content_attempt=lease,
        ).update(**updates) == 1
        news._full_content_fetch_lease = None
        if not saved:
            news.refresh_from_db()
            return False
        news.refresh_from_db()
        return True

    news.full_content_fetch_status = status
    news.full_content_fetch_error = error_text
    if provider:
        news.full_content_fetch_provider = provider
    news.full_content_retry_count = news.full_content_retry_count + 1
    news.last_full_content_attempt = updates['last_full_content_attempt']
    news.save(update_fields=[
        'full_content_fetch_status',
        'full_content_fetch_error',
        'full_content_fetch_provider',
        'full_content_retry_count',
        'last_full_content_attempt',
    ])
    return True


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
