"""T04 one-shot owner-scoped chat turn reservations and durable cancellation.

The UUID is minted by the authenticated browser before the paid POST.
Cancel-before-POST writes a tombstone; reserve rejects it. Once an attempt is
admitted, it can never be replayed on the same UUID. A cancellation that wins
the terminal CAS prevents a completed history write. Cancellation cannot
guarantee that an already-dispatched provider request was not billed.
"""
import time
from uuid import UUID

from django.db import IntegrityError, OperationalError, transaction

from api.models import ArticleChatTurn


class ArticleChatTurnError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def parse_turn_id(value):
    if type(value) is not str or len(value) != 36:
        raise ArticleChatTurnError('invalid_chat_turn')
    try:
        turn_id = UUID(value)
        if str(turn_id) != value or turn_id.version != 4:
            raise ValueError
    except (TypeError, ValueError):
        raise ArticleChatTurnError('invalid_chat_turn') from None
    return turn_id


MAX_TURN_CAS_ATTEMPTS = 10


def _is_sqlite_busy(error):
    # Reuse chat-history's SQLite classifier so all short turn/history
    # transactions recognize Django-wrapped driver error codes consistently.
    from api.services.chat_history import _is_sqlite_busy as classify_sqlite_busy

    return classify_sqlite_busy(error)


def _create_turn(*, user_id, news_id, turn_id):
    """Create in a savepoint so a duplicate can be read inside an outer tx."""
    try:
        with transaction.atomic():
            ArticleChatTurn.objects.create(
                id=turn_id, user_id=user_id, news_id=news_id, status='pending',
            )
    except IntegrityError:
        row = ArticleChatTurn.objects.filter(pk=turn_id).values(
            'user_id', 'news_id', 'status',
        ).first()
        if row is None or (row['user_id'], row['news_id']) != (user_id, news_id):
            raise ArticleChatTurnError('chat_turn_not_found') from None
        raise ArticleChatTurnError(
            'chat_turn_cancelled' if row['status'] == 'cancelled' else 'duplicate_chat_turn',
        ) from None


def reserve_turn(*, user_id, news_id, turn_id):
    """First use only. A pre-cancelled or duplicate ID never causes a send."""
    for attempt in range(1, MAX_TURN_CAS_ATTEMPTS + 1):
        try:
            with transaction.atomic():
                _create_turn(user_id=user_id, news_id=news_id, turn_id=turn_id)
            return
        except OperationalError as error:
            if _is_sqlite_busy(error) and attempt < MAX_TURN_CAS_ATTEMPTS:
                time.sleep(0.005 * attempt)
                continue
            raise ArticleChatTurnError('chat_turn_unavailable') from None


def reserve_turn_with_question(*, user_id, news_id, turn_id, question, article_context=None):
    """Reserve the UUID and append its question atomically, before provider I/O.

    Clear-history cannot interleave between the reservation and initial append:
    it either cancels this committed turn or runs before this whole transaction.
    """
    from api.services.chat_history import append_user_message

    for attempt in range(1, MAX_TURN_CAS_ATTEMPTS + 1):
        try:
            with transaction.atomic():
                _create_turn(user_id=user_id, news_id=news_id, turn_id=turn_id)
                return append_user_message(
                    user_id=user_id, news_id=news_id, content=question, article_context=article_context,
                )
        except OperationalError as error:
            if _is_sqlite_busy(error) and attempt < MAX_TURN_CAS_ATTEMPTS:
                time.sleep(0.005 * attempt)
                continue
            raise ArticleChatTurnError('chat_turn_unavailable') from None


def mark_dispatched(*, user_id, news_id, turn_id):
    """The one-way admission point immediately before initiating I/O."""
    try:
        updated = ArticleChatTurn.objects.filter(
            pk=turn_id, user_id=user_id, news_id=news_id, status='pending',
        ).update(status='dispatched')
    except OperationalError:
        raise ArticleChatTurnError('chat_turn_unavailable') from None
    if updated != 1:
        raise ArticleChatTurnError('chat_turn_cancelled')


def require_dispatched(*, user_id, news_id, turn_id):
    """Reject work after owner/article-scoped cancellation or terminalization."""
    try:
        status = ArticleChatTurn.objects.filter(
            pk=turn_id, user_id=user_id, news_id=news_id,
        ).values_list('status', flat=True).first()
    except OperationalError:
        raise ArticleChatTurnError('chat_turn_unavailable') from None
    if status != 'dispatched':
        raise ArticleChatTurnError('chat_turn_cancelled')
    return True


def mark_complete(*, user_id, news_id, turn_id):
    """Called INSIDE commit_result's transaction before appending the answer."""
    updated = ArticleChatTurn.objects.filter(
        pk=turn_id, user_id=user_id, news_id=news_id, status='dispatched',
    ).update(status='complete')
    if updated != 1:
        raise ArticleChatTurnError('chat_turn_cancelled')


def cancel_turn(*, user_id, news_id, turn_id):
    """Idempotent owner-only cancellation including a pre-request tombstone.

    Conditional SQL updates serialize cancellation vs completion; if completion
    wins, do not falsely acknowledge cancellation. Never persist credentials,
    prompts or answers in this control row.
    """
    for attempt in range(1, MAX_TURN_CAS_ATTEMPTS + 1):
        try:
            row = ArticleChatTurn.objects.filter(pk=turn_id).values(
                'user_id', 'news_id', 'status',
            ).first()
            if row is None:
                try:
                    with transaction.atomic():
                        ArticleChatTurn.objects.create(
                            id=turn_id, user_id=user_id, news_id=news_id, status='cancelled',
                        )
                except IntegrityError:
                    continue
                return 'cancelled'
            if (row['user_id'], row['news_id']) != (user_id, news_id):
                raise ArticleChatTurnError('chat_turn_not_found')
            if row['status'] == 'cancelled':
                return 'cancelled'
            if row['status'] == 'complete':
                return 'already_completed'
            if ArticleChatTurn.objects.filter(
                pk=turn_id, user_id=user_id, news_id=news_id,
                status__in=('pending', 'dispatched'),
            ).update(status='cancelled') == 1:
                return 'cancelled'
        except OperationalError as error:
            if _is_sqlite_busy(error) and attempt < MAX_TURN_CAS_ATTEMPTS:
                time.sleep(0.005 * attempt)
                continue
            raise ArticleChatTurnError('chat_turn_unavailable') from None
    raise ArticleChatTurnError('chat_turn_unavailable')
