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
import hashlib
from dataclasses import dataclass

from api.models import News
from datetime import datetime, timedelta, timezone as utc_timezone
from typing import TYPE_CHECKING

from django.db.models import F, Q, TextField, Value, Func
from django.db.models.functions import Coalesce
from django.utils.timezone import now as tz_now

from api.services.article_fetcher.types import (
    fetch_error_diagnostic,
    fetch_error_provider,
    fetch_failure_code,
)

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
    'transport_error',
    'response_read_error',
    'ssl',
    'refused',
    'unreachable',
    'temporarily unavailable',
    'http_401',
    'http_403',
    'http_408',
    'http_425',
    'http_429',
    'http_5',
    'dns_error',
    'tls_error',
    'connection_reset',
    'connection_refused',
    'host_unreachable',
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
    whitespace = ' \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000'
    return Coalesce(Func(F(field_name), Value(whitespace), function='TRIM', output_field=TextField()),
                    Value(''), output_field=TextField())


@dataclass(frozen=True)
class FetchLease:
    news_id: int
    claimed_at: datetime
    expected_url: str
    expected_revision: int


@dataclass(frozen=True)
class ContentCommit:
    outcome: str
    reason: str = ''
    changed: bool = False

    @property
    def saved(self):
        return self.outcome in {'committed', 'noop'}


def _owned_query(news):
    lease = getattr(news, '_full_content_snapshot', None)
    if not lease:
        return news.__class__.objects.none()
    return news.__class__.objects.filter(
        pk=lease.news_id, url=lease.expected_url,
        full_content_revision=lease.expected_revision,
        full_content_fetch_status='fetching', last_full_content_attempt=lease.claimed_at,
    )


def enqueue_fetch(news, *, force=False, priority=0):
    """Persist one task intent; duplicates and force preserve leases/cooldowns."""
    from api.services.source_policy import policy_for_url
    from api.services.article_fetcher.site_rules import get_site_rule
    from api.services.article_identity import InvalidIdentity, normalize_article_url
    try:
        normalize_article_url(news.url)
    except InvalidIdentity:
        return 'rejected'
    policy = policy_for_url(news.url)
    if ((policy and (policy.unsupported_reason or not policy.html_allowed)) or
            (not policy and not get_site_rule(news.url))):
        return 'rejected'
    if has_full_content(news) and not force:
        return 'cached'
    now = tz_now()
    query = news.__class__.objects.filter(pk=news.pk, url=news.url, full_content_revision=news.full_content_revision)
    # Already scheduled tasks, terminal policy blocks and valid leases are not
    # reset by repeated user requests. Source fixes need an explicit new cycle.
    if news.full_content_fetch_status in {'blocked', 'unsupported'}:
        return 'rejected'
    if news.full_content_next_attempt_at is not None or news.full_content_fetch_status == 'fetching':
        return 'reused'
    updated = query.filter(full_content_next_attempt_at__isnull=True).exclude(full_content_fetch_status='fetching').update(
        full_content_fetch_status='queued', full_content_next_attempt_at=now,
        full_content_priority=max(-10, min(10, priority)), full_content_retry_count=0,
        full_content_error_code='', full_content_fetch_error='',
    )
    news.refresh_from_db()
    return 'queued' if updated else 'reused'


def claim_fetch(news: News, *, force: bool = False) -> FetchLease | None:
    """Claim only scheduled, due work, fenced by its request-before snapshot."""
    from api.services.source_policy import policy_for_url
    from api.services.article_fetcher.site_rules import get_site_rule
    from api.services.article_identity import InvalidIdentity, normalize_article_url
    try:
        normalize_article_url(news.url)
    except InvalidIdentity:
        return None
    policy = policy_for_url(news.url)
    if (policy and (policy.unsupported_reason or not policy.html_allowed)) or (not policy and not get_site_rule(news.url)):
        return None
    now = tz_now()
    stale_before = now - FETCH_IN_PROGRESS_TTL
    due = Q(full_content_next_attempt_at__lte=now) & Q(full_content_fetch_status__in=['queued', 'rate_limited', 'network_error', 'failed'])
    stale = Q(full_content_fetch_status='fetching') & (Q(last_full_content_attempt__lt=stale_before) | Q(last_full_content_attempt__isnull=True))
    claimed = news.__class__.objects.filter(
        Q(due) | Q(stale), pk=news.pk, url=news.url,
        full_content_revision=news.full_content_revision, full_content_retry_count__lt=5,
    ).update(
        full_content_fetch_status='fetching', full_content_fetch_error='',
        full_content_error_code='', last_full_content_attempt=now,
    ) == 1
    snapshot = FetchLease(news.pk, now, news.url, news.full_content_revision) if claimed else None
    news._full_content_snapshot = snapshot
    news._full_content_fetch_claimed = True
    news._full_content_fetch_lease = now if claimed else None
    return snapshot


def owns_fetch(news) -> bool:
    return _owned_query(news).exists()


def release_fetch_claim(news: News, *, next_attempt_at=None) -> bool:
    """Cancellation preserves the durable task; never releases someone else's lease."""
    when = max(tz_now(), next_attempt_at or tz_now(), news.full_content_next_attempt_at or tz_now())
    released = _owned_query(news).update(
        full_content_fetch_status='queued', full_content_next_attempt_at=when,
    ) == 1
    news._full_content_snapshot = None
    news._full_content_fetch_lease = None
    news.refresh_from_db()
    return released


def recover_stale_fetches():
    now = tz_now()
    stale = Q(last_full_content_attempt__lt=now - FETCH_IN_PROGRESS_TTL) | Q(last_full_content_attempt__isnull=True)
    # Preserve an existing future retry time; recovering a process is not a retry.
    query = News.objects.filter(stale, full_content_fetch_status='fetching')
    immediate = query.filter(Q(full_content_next_attempt_at__isnull=True) | Q(full_content_next_attempt_at__lte=now)).update(
        full_content_fetch_status='queued', full_content_next_attempt_at=now,
    )
    return immediate + query.filter(full_content_next_attempt_at__gt=now).update(full_content_fetch_status='queued')


def mark_fetching(news: News):
    # Compatibility name, not an unfenced write path.
    return claim_fetch(news)


def _stable_provenance(provenance):
    keys = ('provider', 'source_key', 'source_item_id', 'target_url', 'body_field',
            'source_version', 'source_modified_at', 'body_sha256', 'validator_version', 'declared_canonical_url', 'content_kind')
    return {key: provenance.get(key) for key in keys}


def commit_candidate(news, candidate, *, provider='', lease: FetchLease | None = None, summary=None, quality_score=1.0, backfill_source=None, backfill_at=None):
    """The only body write: validate, compare upstream evidence, URL/revision/lease CAS."""
    from api.services.article_fetcher.validators import validate_candidate, VALIDATOR_VERSION
    from api.services.article_fetcher.types import FullContentCandidate
    if not isinstance(candidate, FullContentCandidate):
        return ContentCommit('rejected', 'invalid_identity')
    expected_url = lease.expected_url if lease else news.url
    expected_revision = lease.expected_revision if lease else news.full_content_revision
    if candidate.expected_revision is not None and candidate.expected_revision != expected_revision:
        return ContentCommit('conflict', 'persistence_conflict')
    query = news.__class__.objects.filter(pk=news.pk, url=expected_url, full_content_revision=expected_revision)
    if lease:
        query = query.filter(full_content_fetch_status='fetching', last_full_content_attempt=lease.claimed_at)
    current = query.first()
    if current is None:
        return ContentCommit('conflict', 'persistence_conflict')
    identities = current.source_items.filter(source_key=candidate.source_key)
    # The reviewed CMS response resolves its numeric post ID from the exact
    # permalink. Feed GUIDs remain separate upstream identities of that article.
    cms_permalink_binding = candidate.source_key == 'techcrunch' and candidate.body_field == 'content.rendered'
    if identities.exists() and not identities.filter(upstream_id=candidate.source_item_id).exists() and not cms_permalink_binding:
        return ContentCommit('rejected', 'body_mismatch')
    from api.services.source_policy import POLICIES
    candidate_policy = POLICIES.get(candidate.source_key)
    structural_binding = identities.filter(upstream_id=candidate.source_item_id).exists()
    title = current.title
    if candidate_policy and current.source.name != candidate_policy.name and structural_binding:
        # HN may edit the publisher's headline. Exact official ID/URL binding
        # takes precedence over an aggregator's auxiliary title.
        title = ''
    validation = validate_candidate(candidate, expected_url=expected_url, expected_title=title, summary=summary)
    if not validation.ok:
        return ContentCommit('rejected', validation.error_code)
    body = validation.markdown
    body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    from api.services.article_identity import normalize_article_url
    canonical = normalize_article_url(candidate.declared_canonical_url, max_length=2048, require_article=False) if candidate.declared_canonical_url else None
    modified = candidate.source_modified_at.astimezone(utc_timezone.utc).isoformat() if candidate.source_modified_at else None
    provenance = {
        'provider': provider or candidate.source_key,
        'source_key': candidate.source_key, 'source_item_id': candidate.source_item_id,
        'target_url': expected_url, 'retrieved_from_url': candidate.retrieved_from_url, 'body_field': candidate.body_field,
        'source_version': candidate.source_version, 'source_modified_at': modified,
        'body_sha256': body_hash, 'validator_version': VALIDATOR_VERSION,
        'declared_canonical_url': canonical, 'content_kind': candidate.content_kind,
    }
    old = current.full_content_provenance or {}
    same_body = body == current.full_content
    comparable = False
    newer = False
    if old.get('source_key') == candidate.source_key and old.get('source_item_id') == candidate.source_item_id:
        previous_modified = old.get('source_modified_at')
        if previous_modified and modified:
            previous = datetime.fromisoformat(previous_modified)
            comparable = True
            newer = candidate.source_modified_at > previous
            if candidate.source_modified_at < previous or (candidate.source_modified_at == previous and not same_body):
                return ContentCommit('rejected', 'source_version_conflict')
        # Opaque version tokens establish equality only, never ordering.
        if old.get('source_version') and candidate.source_version == old['source_version'] and not same_body:
            return ContentCommit('rejected', 'source_version_conflict')
    if has_full_content(current) and not same_body and not lease and not (comparable and newer):
        return ContentCommit('rejected', 'source_version_conflict')
    changed = not same_body or current.full_content_state != 'complete' or _stable_provenance(old) != _stable_provenance(provenance)
    completed = tz_now()
    updates = {}
    if changed:
        provenance['accepted_at'] = completed.isoformat()
        updates.update(
            full_content=body, full_content_state='complete',
            full_content_revision=F('full_content_revision') + 1,
            full_content_provenance=provenance, full_content_quality_score=quality_score,
            full_content_fetched_at=completed,
        )
        if current.content_kind == 'unknown':
            updates['content_kind'] = candidate.content_kind
        if not same_body:
            updates.update(full_content_zh='', full_content_zh_fetched_at=None,
                           suggested_questions=[], suggested_questions_generated_at=None)
    if changed or lease:
        updates.update(
            full_content_fetch_status='success', full_content_fetch_error='',
            full_content_error_code='', full_content_next_attempt_at=None,
            full_content_retry_count=0, full_content_fetch_provider=provider or candidate.source_key,
        )
        if lease:
            updates['last_full_content_attempt'] = completed
        if backfill_source is not None:
            updates['full_content_backfill_source'] = backfill_source
        if backfill_at is not None:
            updates['full_content_backfill_at'] = backfill_at
        saved = query.update(**updates) == 1
    else:
        # The existence check is also fenced; a no-op cannot acknowledge stale data.
        saved = query.exists()
    news.refresh_from_db()
    return ContentCommit('committed' if changed and saved else 'noop' if saved else 'conflict',
                         '' if saved else 'persistence_conflict', changed and saved)


def mark_success(news: News, result: FetchResult, *, full_content=None, full_content_fetched_at=None,
                 full_content_backfill_source=None, full_content_backfill_at=None) -> bool:
    lease = getattr(news, '_full_content_snapshot', None)
    if not lease or not result.ok or result.candidate is None:
        return False
    if full_content is not None and full_content != result.markdown:
        return False
    committed = commit_candidate(
        news, result.candidate, provider=result.provider, lease=lease,
        quality_score=result.quality_score or 1.0,
        backfill_source=full_content_backfill_source, backfill_at=full_content_backfill_at,
    )
    if committed.saved:
        news._full_content_snapshot = None
        news._full_content_fetch_lease = None
    return committed.saved


def mark_failed(news: News, error, status=None, provider='') -> bool:
    if getattr(error, 'error_code', '') == 'budget_deferred':
        return release_fetch_claim(news, next_attempt_at=error.retry_after_at)
    if getattr(error, 'error_code', '') == 'superseded':
        return False
    status = status or classify_fetch_error(error)
    provider = provider or fetch_error_provider(error)
    code = getattr(error, 'error_code', '') or fetch_failure_code(error)
    retry_at = getattr(error, 'retry_after_at', None)
    failures = news.full_content_retry_count + 1
    typed_retryable = not getattr(error, 'error_code', '') or getattr(error, 'retryable', False)
    retryable = status in {'network_error', 'failed', 'rate_limited'} and failures < 5 and typed_retryable
    updates = {
        'full_content_fetch_status': status, 'full_content_fetch_error': fetch_error_diagnostic(error),
        'full_content_error_code': code, 'full_content_retry_count': F('full_content_retry_count') + 1,
        'last_full_content_attempt': tz_now(),
        'full_content_next_attempt_at': (retry_at or tz_now() + timedelta(seconds=min(3600, 60 * 2 ** (failures - 1)))) if retryable else None,
    }
    if provider:
        updates['full_content_fetch_provider'] = provider
    saved = _owned_query(news).update(**updates) == 1
    news._full_content_snapshot = None
    news._full_content_fetch_lease = None
    news.refresh_from_db()
    return saved


def save_suggested_questions(news, questions, *, expected_revision):
    return news.__class__.objects.filter(pk=news.pk, url=news.url, full_content_revision=expected_revision).update(
        suggested_questions=questions, suggested_questions_generated_at=tz_now(),
    ) == 1


def classify_fetch_error(error_or_result) -> str:
    """Classify a FetchError or Exception into a status string.

    Returns one of: 'network_error', 'validation_failed', 'failed'.
    """
    code = getattr(error_or_result, 'error_code', '')
    if code == 'rate_limited':
        return 'rate_limited'
    if code in {'auth_required', 'access_blocked'}:
        return 'blocked'
    if code in {'not_found', 'unsupported', 'invalid_identity'}:
        return 'unsupported'
    if code in {'body_partial', 'body_mismatch', 'body_empty', 'source_version_conflict'}:
        return 'validation_failed'
    if code in {'network_timeout', 'upstream_5xx', 'network_error'}:
        return 'network_error'
    failures = getattr(error_or_result, 'failures', None) or []
    candidates = failures or [error_or_result]
    diagnostic_codes = [fetch_failure_code(candidate) for candidate in candidates]
    raw_text = ' '.join(
        str(getattr(candidate, 'error', '') or candidate)
        for candidate in candidates
    )
    validation_reasons = []
    for candidate in candidates:
        validation_reasons.extend(getattr(candidate, 'validation_reasons', None) or [])
        metadata = getattr(candidate, 'metadata', None)
        if isinstance(metadata, dict):
            validation_reasons.extend(metadata.get('validation_reasons', []) or [])

    text = ' '.join([raw_text, *diagnostic_codes, *validation_reasons]).lower()

    for keyword in _VALIDATION_KEYWORDS:
        if keyword.lower() in text:
            return 'validation_failed'

    for keyword in _NETWORK_ERROR_KEYWORDS:
        if keyword.lower() in text:
            return 'network_error'

    return 'failed'


def has_full_content(news: News) -> bool:
    """Availability is independent of the latest refresh attempt's status."""
    return news.full_content_state in {'legacy', 'complete'} and bool((news.full_content or '').strip())


def get_readable_full_content(news: News) -> str:
    return news.full_content if has_full_content(news) else ''


def filter_readable_full_content(queryset):
    return queryset.annotate(
        _readable_body=trimmed_text_expression('full_content'),
    ).filter(full_content_state__in=['legacy', 'complete']).exclude(_readable_body='')


def correct_article_identity(news, new_url, *, expected_url, expected_revision):
    """Quarantine old text and fence every old worker when identity changes."""
    from api.services.article_identity import normalize_article_url
    new_url = normalize_article_url(new_url)
    if new_url == expected_url:
        return True
    saved = news.__class__.objects.filter(pk=news.pk, url=expected_url, full_content_revision=expected_revision).update(
        url=new_url, full_content_revision=F('full_content_revision') + 1,
        full_content_state='missing', full_content_fetch_status='pending',
        full_content_next_attempt_at=None, full_content_error_code='identity_changed',
        suggested_questions=[], suggested_questions_generated_at=None,
    ) == 1
    news.refresh_from_db()
    return saved
