"""Persistent, fail-closed rate limits and one-use signup invitations."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import BaseUserManager
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from api.models import AuthRateBucket, AuthSecurityLock, SignupInvite


MAX_SQLITE_BUSY_ATTEMPTS = 3
SQLITE_BUSY_RETRY_SECONDS = (0.02, 0.04)


class InvalidClientAddress(ValueError):
    """REMOTE_ADDR was absent or did not contain one valid IP address."""


class AuthSecurityBusy(RuntimeError):
    """The persistent security lock stayed busy after bounded retries."""


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__('auth_rate_limited')
        self.retry_after = retry_after


class SignupInviteRequired(RuntimeError):
    pass


class RegistrationUnavailable(RuntimeError):
    pass


def normalize_email(email: str) -> str:
    return BaseUserManager.normalize_email(email)


def normalize_remote_addr(remote_addr: object) -> str:
    if not isinstance(remote_addr, str) or not remote_addr.strip():
        raise InvalidClientAddress('invalid_client_address')
    try:
        return str(ipaddress.ip_address(remote_addr.strip()))
    except ValueError as error:
        raise InvalidClientAddress('invalid_client_address') from error


def _bucket_key(kind: str, identity: str) -> str:
    message = f'{kind}\0{identity}'.encode('utf-8')
    secret = settings.SECRET_KEY.encode('utf-8')
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _window_start(now: datetime, seconds: int) -> tuple[datetime, int]:
    timestamp = now.timestamp()
    start_timestamp = math.floor(timestamp / seconds) * seconds
    start = datetime.fromtimestamp(start_timestamp, tz=datetime_timezone.utc)
    retry_after = max(1, math.ceil(start_timestamp + seconds - timestamp))
    return start, retry_after


def _is_sqlite_busy(error: OperationalError) -> bool:
    if connection.vendor != 'sqlite':
        return False
    code = getattr(error, 'sqlite_errorcode', None)
    if isinstance(code, int) and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in ('database is locked', 'database table is locked', 'database is busy')
    )


def _write_security_lock() -> None:
    # This UPDATE is deliberately the first SQL write in each security
    # transaction. SQLite serializes competing writers at this statement.
    updated = AuthSecurityLock.objects.filter(pk=1).update(revision=F('revision') + 1)
    if updated:
        return

    # The row is created lazily. The preceding no-match UPDATE is still the
    # first write and obtains SQLite's write reservation before this insert.
    try:
        with transaction.atomic():
            AuthSecurityLock.objects.create(pk=1, revision=1)
    except IntegrityError:
        # Another database implementation may race to create the singleton;
        # retry the F() update while retaining the outer transaction.
        updated = AuthSecurityLock.objects.filter(pk=1).update(revision=F('revision') + 1)
        if not updated:
            raise


def run_with_security_lock(operation):
    """Run a database operation after the singleton write fence, fail closed."""
    for attempt in range(1, MAX_SQLITE_BUSY_ATTEMPTS + 1):
        try:
            with transaction.atomic():
                _write_security_lock()
                return operation()
        except OperationalError as error:
            if not _is_sqlite_busy(error):
                raise
            if attempt == MAX_SQLITE_BUSY_ATTEMPTS:
                raise AuthSecurityBusy('auth_security_busy') from error
            time.sleep(SQLITE_BUSY_RETRY_SECONDS[attempt - 1])
    raise AuthSecurityBusy('auth_security_busy')


def _reserve_buckets(specifications, now: datetime | None = None) -> None:
    now = now or timezone.now()
    buckets = []
    for kind, identity, limit, window_seconds in specifications:
        window_start, retry_after = _window_start(now, window_seconds)
        buckets.append({
            'key': _bucket_key(kind, identity),
            'kind': kind,
            'limit': limit,
            'window_start': window_start,
            'retry_after': retry_after,
        })

    def reserve():
        current = []
        blocked_after = []
        for specification in buckets:
            bucket = AuthRateBucket.objects.filter(
                key=specification['key'],
                window_start=specification['window_start'],
            ).first()
            count = bucket.count if bucket else 0
            if count >= specification['limit']:
                blocked_after.append(specification['retry_after'])
            current.append((specification, bucket))

        if blocked_after:
            raise RateLimitExceeded(max(blocked_after))

        for specification, bucket in current:
            if bucket:
                AuthRateBucket.objects.filter(pk=bucket.pk).update(count=F('count') + 1)
            else:
                AuthRateBucket.objects.create(
                    key=specification['key'],
                    kind=specification['kind'],
                    window_start=specification['window_start'],
                    count=1,
                )

    run_with_security_lock(reserve)


def reserve_login_attempts(remote_addr: object, username: object, *, now: datetime | None = None) -> None:
    client_ip = normalize_remote_addr(remote_addr)
    folded_username = username.casefold() if isinstance(username, str) else ''
    _reserve_buckets(
        [
            ('login_ip', client_ip, 20, 600),
            ('login_ip_username', f'{client_ip}\0{folded_username}', 5, 600),
        ],
        now=now,
    )


def reserve_registration_attempts(remote_addr: object, *, now: datetime | None = None) -> None:
    client_ip = normalize_remote_addr(remote_addr)
    _reserve_buckets(
        [
            ('register_ip', client_ip, 5, 3600),
            ('register_global', 'global', 100, 3600),
        ],
        now=now,
    )


def issue_signup_invite(email: str, expires_hours: int, *, now: datetime | None = None) -> str:
    now = now or timezone.now()
    token = secrets.token_urlsafe(32)
    SignupInvite.objects.create(
        token_digest=hashlib.sha256(token.encode('utf-8')).hexdigest(),
        email=normalize_email(email),
        expires_at=now + timedelta(hours=expires_hours),
    )
    return token


def _find_valid_invite(token: object, email: str, now: datetime) -> SignupInvite | None:
    if not isinstance(token, str) or not token or len(token) > 256:
        return None
    token_digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    return SignupInvite.objects.filter(
        token_digest=token_digest,
        email=email,
        consumed_at__isnull=True,
        expires_at__gt=now,
    ).first()


def create_registered_user(
    *,
    username: str,
    email: str,
    password: str,
    invite_token: object = None,
    require_invite: bool,
    on_created=None,
    now: datetime | None = None,
):
    """Create a user and consume any required invite under one write fence."""
    User = get_user_model()

    def create_account():
        registration_time = now or timezone.now()
        invite = None
        if require_invite:
            invite = _find_valid_invite(invite_token, email, registration_time)
            if invite is None:
                raise SignupInviteRequired('invite_required')

        if User.objects.filter(username=username).exists():
            raise RegistrationUnavailable('registration_unavailable')

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                )
        except IntegrityError as error:
            raise RegistrationUnavailable('registration_unavailable') from error

        if invite:
            consumed = SignupInvite.objects.filter(
                pk=invite.pk,
                consumed_at__isnull=True,
                expires_at__gt=registration_time,
                email=email,
            ).update(consumed_at=registration_time, consumed_by=user)
            if not consumed:
                raise SignupInviteRequired('invite_required')

        if on_created is not None:
            on_created(user)
        return user

    return run_with_security_lock(create_account)
