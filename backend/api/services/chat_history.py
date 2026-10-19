"""Concurrency-safe ownership and lifecycle operations for news chat history."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone

from api.models import ArticleChatTurn, ChatSession


MAX_CAS_ATTEMPTS = 5


class ChatConflict(RuntimeError):
    """The caller's chat state changed before its compare-and-swap could commit."""


@dataclass(frozen=True)
class ChatSnapshot:
    session_id: int
    generation: int
    messages: list


def _is_sqlite_busy(error: OperationalError) -> bool:
    if connection.vendor != 'sqlite':
        return False
    driver_error = error.__cause__ or error
    code = getattr(driver_error, 'sqlite_errorcode', None)
    if isinstance(code, int):
        return (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    message = str(driver_error).lower()
    return any(text in message for text in ('database is locked', 'database table is locked', 'database is busy'))


def _pause_before_retry(attempt: int) -> None:
    time.sleep(0.005 * attempt)


def _append_message(*, user_id: int, news_id: int, message: dict, session_id: int | None = None,
                    generation: int | None = None, create: bool) -> ChatSnapshot:
    last_busy_error: OperationalError | None = None

    for attempt in range(1, MAX_CAS_ATTEMPTS + 1):
        try:
            if session_id is None:
                session = ChatSession.objects.filter(user_id=user_id, news_id=news_id).first()
                if session is None:
                    if not create:
                        raise ChatConflict('chat_conflict')
                    try:
                        with transaction.atomic():
                            session = ChatSession.objects.create(
                                user_id=user_id,
                                news_id=news_id,
                                messages=[],
                            )
                    except IntegrityError:
                        # A concurrent insert won the unique (user, news) race.
                        continue
            else:
                session = ChatSession.objects.filter(
                    pk=session_id,
                    user_id=user_id,
                    news_id=news_id,
                ).first()
                if session is None or session.generation != generation:
                    raise ChatConflict('chat_conflict')

            if not isinstance(session.messages, list):
                raise ChatConflict('chat_conflict')

            updated_messages = [*session.messages, message]
            updated = ChatSession.objects.filter(
                pk=session.pk,
                user_id=user_id,
                news_id=news_id,
                revision=session.revision,
                generation=session.generation,
            ).update(
                messages=updated_messages,
                revision=session.revision + 1,
                updated_at=timezone.now(),
            )
        except OperationalError as error:
            if not _is_sqlite_busy(error):
                raise
            # A failed write may mark an enclosing transaction rollback-only.
            # Its owner must unwind and retry the whole unit, not this query.
            if connection.in_atomic_block:
                raise
            last_busy_error = error
            if attempt < MAX_CAS_ATTEMPTS:
                _pause_before_retry(attempt)
            continue

        if updated:
            return ChatSnapshot(
                session_id=session.pk,
                generation=session.generation,
                messages=updated_messages,
            )

        if attempt < MAX_CAS_ATTEMPTS:
            _pause_before_retry(attempt)

    raise ChatConflict('chat_conflict') from last_busy_error


def append_user_message(*, user_id: int, news_id: int, content: str) -> ChatSnapshot:
    return _append_message(
        user_id=user_id,
        news_id=news_id,
        message={'role': 'user', 'content': content},
        create=True,
    )


CHAT_TURN_STATUSES = frozenset({'complete', 'failed', 'interrupted', 'legacy_unknown'})

def normalized_chat_history(messages: list) -> list:
    """Make legacy completion uncertainty explicit without mutating archived records."""
    if not isinstance(messages, list):
        return []
    normalized = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        entry = dict(message)
        if entry.get('role') == 'assistant' and entry.get('status') not in CHAT_TURN_STATUSES:
            entry['status'] = 'legacy_unknown'
        normalized.append(entry)
    return normalized


def append_assistant_message(*, user_id: int, news_id: int, session_id: int,
                             generation: int, content: str, status: str = 'complete',
                             article_context=None, model_source=None) -> ChatSnapshot:
    if status not in {'complete', 'failed', 'interrupted'}:
        raise ValueError('invalid assistant completion status')
    return _append_message(
        user_id=user_id,
        news_id=news_id,
        message={'role': 'assistant', 'content': content, 'status': status,
                 **({'article_context': article_context} if article_context is not None else {}),
                 **({'model_source': model_source} if model_source is not None else {})},
        session_id=session_id,
        generation=generation,
        create=False,
    )


def clear_chat_history(*, user_id: int, news_id: int) -> bool:
    """Clear one owner's history and fence their already-reserved article turns.

    The conditional turn update and generation/revision CAS share a short
    transaction. Turn rows are updated before ChatSession to match completion's
    turn-then-history write order and avoid a lock-order inversion.
    """
    last_busy_error: OperationalError | None = None

    for attempt in range(1, MAX_CAS_ATTEMPTS + 1):
        try:
            with transaction.atomic():
                ArticleChatTurn.objects.filter(
                    user_id=user_id, news_id=news_id,
                    status__in=('pending', 'dispatched'),
                ).update(status='cancelled')
                session = ChatSession.objects.filter(user_id=user_id, news_id=news_id).first()
                if session is None:
                    return False
                updated = ChatSession.objects.filter(
                    pk=session.pk,
                    user_id=user_id,
                    news_id=news_id,
                    revision=session.revision,
                    generation=session.generation,
                ).update(
                    messages=[],
                    revision=session.revision + 1,
                    generation=session.generation + 1,
                    updated_at=timezone.now(),
                )
                if updated:
                    return True
        except OperationalError as error:
            if not _is_sqlite_busy(error):
                raise
            last_busy_error = error
            if attempt < MAX_CAS_ATTEMPTS:
                _pause_before_retry(attempt)
            continue

        if attempt < MAX_CAS_ATTEMPTS:
            _pause_before_retry(attempt)

    raise ChatConflict('chat_conflict') from last_busy_error
