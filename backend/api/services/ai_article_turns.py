"""T04 one-shot owner-scoped chat turn reservations and durable cancellation.

The UUID is minted by the authenticated browser before the paid POST.
Cancel-before-POST writes a tombstone; reserve rejects it. Once an attempt is
admitted, it can never be replayed on the same UUID. A cancellation that wins
the terminal CAS prevents a completed history write. Cancellation cannot
guarantee that an already-dispatched provider request was not billed.
"""
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


def reserve_turn(*, user_id, news_id, turn_id):
    """First use only. A pre-cancelled or duplicate ID never causes a send."""
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
    except OperationalError:
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
    for _ in range(5):
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
        except OperationalError:
            raise ArticleChatTurnError('chat_turn_unavailable') from None
    raise ArticleChatTurnError('chat_turn_unavailable')
