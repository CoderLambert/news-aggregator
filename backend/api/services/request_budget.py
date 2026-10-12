"""Database-backed HTTP admission shared by every news fetching process."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as utc_timezone
from email.utils import parsedate_to_datetime
import hashlib
import random
import time
from urllib.parse import urlsplit
import uuid

from django.db import connection, OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone

from api.models import RequestBudget

LEASE_SECONDS = 30
DOWNLOAD_SECONDS = 15
GLOBAL_KEYS = ('global:0', 'global:1')


class BudgetDeferred(Exception):
    error_code = 'budget_deferred'
    http_status = None
    retryable = True

    def __init__(self, retry_after_at, scope_keys=()):
        super().__init__(self.error_code)
        self.retry_after_at = retry_after_at
        self.scope_keys = tuple(scope_keys)


@dataclass(frozen=True)
class RequestPermit:
    token: str
    scope_keys: tuple[str, ...]
    intervals: tuple[tuple[str, float], ...]
    acquired_at: datetime
    expires_at: datetime


def scope_intervals(url, *, logical_url=None, authorization=None):
    scopes = {}
    for value in (url, logical_url):
        if not value:
            continue
        try:
            host = (urlsplit(value).hostname or '').encode('idna').decode('ascii').lower().rstrip('.')
        except UnicodeError:
            raise ValueError('invalid_budget_host') from None
        if not host or len(host) > 140:
            raise ValueError('invalid_budget_host')
        interval = 1.0 if host == 'dev.to' else 0.5 if host in {'hacker-news.firebaseio.com', 'news.ycombinator.com'} else 3.0
        scopes[f'host:{host}'] = interval
        if host in {'arxiv.org', 'export.arxiv.org', 'rss.arxiv.org'}:
            scopes['group:arxiv'] = 3.0
        if host in {'github.com', 'raw.githubusercontent.com', 'api.github.com'}:
            scopes['group:github'] = 3.0
        if host in {'hacker-news.firebaseio.com', 'news.ycombinator.com'}:
            scopes['group:hackernews'] = 0.5
    if (urlsplit(url).hostname or '').lower() == 'r.jina.ai' and authorization:
        scopes['credential:jina:' + hashlib.sha256(authorization.encode()).hexdigest()[:32]] = 3.0
    return scopes


@contextmanager
def _short_busy_wait():
    # Keep the application's path/WAL/default timeout intact. Only this short
    # admission operation has a bounded busy wait on its own ORM connection.
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA busy_timeout')
        original = cursor.fetchone()[0]
        cursor.execute('PRAGMA busy_timeout=100')
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'PRAGMA busy_timeout={int(original)}')


def _available(now):
    return ((Q(cooldown_until__isnull=True) | Q(cooldown_until__lte=now)) &
            (Q(next_allowed_at__isnull=True) | Q(next_allowed_at__lte=now)) &
            (Q(lease_token='') | Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)))


def next_available_at(scope_keys):
    now = timezone.now()
    deadlines = [now]
    for row in RequestBudget.objects.filter(pk__in=scope_keys):
        deadlines.extend(value for value in (row.cooldown_until, row.next_allowed_at) if value)
        if row.lease_token and row.lease_expires_at:
            deadlines.append(row.lease_expires_at)
    return max(deadlines)


def claim_budget(scopes, *, download_seconds=DOWNLOAD_SECONDS):
    """Acquire a global slot and every scope, or roll back the entire permit."""
    scopes = dict(scopes)
    if not scopes or any(not key.startswith(('host:', 'group:', 'credential:')) or len(key) > 160 or not 0 <= interval <= 3600 for key, interval in scopes.items()):
        raise ValueError('invalid_budget_scopes')
    if not 0 < download_seconds <= DOWNLOAD_SECONDS:
        raise ValueError('invalid_download_deadline')
    keys = tuple(sorted(scopes))
    for attempt in range(3):
        try:
            with _short_busy_wait():
                RequestBudget.objects.bulk_create(
                    [RequestBudget(key=key) for key in (*GLOBAL_KEYS, *keys)], ignore_conflicts=True,
                )
                token = uuid.uuid4().hex
                for global_key in GLOBAL_KEYS:
                    with transaction.atomic():
                        # First statement is a conditional write, not a read or
                        # select_for_update. SQLite must obtain the writer lock.
                        before_lock = timezone.now()
                        claimed = RequestBudget.objects.filter(_available(before_lock), pk=global_key).update(
                            lease_token=token, lease_expires_at=before_lock + timedelta(seconds=LEASE_SECONDS),
                        )
                        if not claimed:
                            continue
                        # The clock is refreshed AFTER that write succeeds, even
                        # when obtaining the write reservation waited for a lock.
                        now = timezone.now()
                        expires = now + timedelta(seconds=LEASE_SECONDS)
                        for key in keys:
                            if not RequestBudget.objects.filter(_available(now), pk=key).update(
                                lease_token=token, lease_expires_at=expires,
                            ):
                                raise BudgetDeferred(next_available_at(keys), keys)
                        owned = (*keys, global_key)
                        RequestBudget.objects.filter(pk__in=owned, lease_token=token).update(lease_expires_at=expires)
                    return RequestPermit(token, tuple(owned), tuple(sorted(scopes.items())), now, expires)
                ready = min(next_available_at((key,)) for key in GLOBAL_KEYS)
                raise BudgetDeferred(max(next_available_at(keys), ready), keys)
        except OperationalError as error:
            if not any(word in str(error).lower() for word in ('busy', 'locked')):
                raise
            if attempt == 2:
                raise BudgetDeferred(timezone.now() + timedelta(seconds=1), keys) from None
            time.sleep(0.01 * (attempt + 1))
    raise AssertionError('unreachable')


def confirm_permit(permit, *, download_seconds=DOWNLOAD_SECONDS):
    """Never send using an expired or replaced token after an ORM/queue delay."""
    now = timezone.now()
    deadline = now + timedelta(seconds=download_seconds + 1)
    try:
        with _short_busy_wait():
            count = RequestBudget.objects.filter(Q(cooldown_until__isnull=True) | Q(cooldown_until__lte=now), pk__in=permit.scope_keys, lease_token=permit.token,
                                                 lease_expires_at__gte=deadline).count()
    except OperationalError as error:
        if not any(word in str(error).lower() for word in ('busy', 'locked')):
            raise
        raise BudgetDeferred(timezone.now() + timedelta(seconds=1), permit.scope_keys) from None
    if count != len(permit.scope_keys):
        raise BudgetDeferred(now + timedelta(seconds=1), permit.scope_keys)


def retry_after_deadline(value, *, now=None, failures=0):
    now = now or timezone.now()
    deadline = None
    if value:
        try:
            if str(value).strip().isdigit():
                try:
                    deadline = now + timedelta(seconds=int(str(value).strip()))
                except OverflowError:
                    deadline = datetime.max.replace(tzinfo=utc_timezone.utc)
            else:
                deadline = parsedate_to_datetime(str(value))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=utc_timezone.utc)
        except (ValueError, TypeError, OverflowError):
            deadline = None
    if deadline is None or deadline < now:
        deadline = now + timedelta(seconds=min(3600, 60 * 2 ** min(failures, 6)))
    # Positive jitter can never retry earlier than the publisher's deadline.
    try:
        return deadline + timedelta(seconds=random.uniform(0, 5))
    except OverflowError:
        return deadline


def record_response(permit, status, headers, *, host=''):
    """Persist cooling before returning control to retry/redirect middleware."""
    headers = {str(key).lower(): value for key, value in headers.items()}
    retry_after = headers.get('retry-after')
    limited = status == 429 or (status == 503 and retry_after is not None)
    if host == 'api.github.com' and status == 403 and headers.get('x-ratelimit-remaining') == '0':
        try:
            reset = datetime.fromtimestamp(int(headers.get('x-ratelimit-reset')), tz=utc_timezone.utc)
            retry_after = reset.strftime('%a, %d %b %Y %H:%M:%S GMT')
            limited = True
        except (TypeError, ValueError, OverflowError):
            pass
    if not limited:
        if 200 <= status < 400:
            with _short_busy_wait():
                RequestBudget.objects.filter(pk__in=permit.scope_keys, lease_token=permit.token, consecutive_failures__gt=0).update(consecutive_failures=0)
        return None
    scopes = tuple(key for key in permit.scope_keys if not key.startswith('global:'))
    with _short_busy_wait(), transaction.atomic():
        # Late 429 responses may extend cooldown but cannot release a newer token.
        RequestBudget.objects.filter(pk__in=scopes).update(consecutive_failures=F('consecutive_failures') + 1)
        failures = max(RequestBudget.objects.filter(pk__in=scopes).values_list('consecutive_failures', flat=True), default=1)
        deadline = retry_after_deadline(retry_after, failures=failures - 1)
        RequestBudget.objects.filter(Q(cooldown_until__isnull=True) | Q(cooldown_until__lt=deadline), pk__in=scopes).update(cooldown_until=deadline)
        return max(RequestBudget.objects.filter(pk__in=scopes).values_list('cooldown_until', flat=True))


def release_budget(permit):
    """Only the owner can release; success cannot shorten a server cooldown."""
    with _short_busy_wait(), transaction.atomic():
        for key, interval in permit.intervals:
            now = timezone.now()
            RequestBudget.objects.filter(pk=key, lease_token=permit.token).update(
                lease_token='', lease_expires_at=None, next_allowed_at=now + timedelta(seconds=interval),
            )
        RequestBudget.objects.filter(pk__in=GLOBAL_KEYS, lease_token=permit.token).update(lease_token='', lease_expires_at=None)
