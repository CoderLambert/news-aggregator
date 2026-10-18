"""T01 durable worker authorization contract for future explicit T02/T03 bindings.

One secret-free snapshot per job. Enqueue/claim/retry/dispatch/commit all verify
the same connection identity. No model selection, fallback or provider call is
implemented here; ChatGPT Subscription remains a separate execution path.

An admitted request can already be in flight when revocation commits. The
worker should attempt cancellation, but MUST fence the final DB commit.
"""
from dataclasses import asdict
from typing import Callable, TypeVar

from django.db import transaction

from api.ai_connection_models import UserAIConnection
from api.services.ai_credentials import (
    ConnectionSnapshot, CredentialUnavailable,
    lock_owner, locked_active_connection, read_execution_credential,
    require_active_snapshot, snapshot_connection,
)

T = TypeVar('T')
SNAPSHOT_SCHEMA_VERSION = 1
_FIELDS = frozenset(ConnectionSnapshot.__dataclass_fields__)


def _decode(snapshot_data, task_owner_id: int) -> ConnectionSnapshot:
    if (type(snapshot_data) is not dict or
            set(snapshot_data) != _FIELDS | {'schema_version'} or
            type(snapshot_data.get('schema_version')) is not int or
            snapshot_data['schema_version'] != SNAPSHOT_SCHEMA_VERSION or
            type(task_owner_id) is not int or task_owner_id < 1):
        raise CredentialUnavailable('execution_snapshot_invalid')
    snapshot = ConnectionSnapshot(**{
        key: snapshot_data[key] for key in ConnectionSnapshot.__dataclass_fields__
    })
    if snapshot.user_id != task_owner_id:
        raise CredentialUnavailable('execution_owner_changed')
    return snapshot


def capture_at_enqueue(*, owner, connection_id) -> dict:
    """Capture an existing authorized connection under the same revocation lock.

    Pass the authenticated task owner, never a globally selected connection.
    The queued payload contains no Key, gateway Key, ciphertext or raw headers.
    A failed decryption prevents enqueue rather than creating an unusable job.
    """
    if (owner is None or not getattr(owner, 'is_authenticated', False) or
            type(getattr(owner, 'pk', None)) is not int):
        raise CredentialUnavailable('execution_owner_changed')
    with transaction.atomic():
        lock_owner(owner.pk)
        try:
            connection = UserAIConnection.objects.filter(pk=connection_id, user_id=owner.pk).first()
        except (ValueError, TypeError):
            raise CredentialUnavailable('execution_snapshot_invalid') from None
        if connection is None:
            raise CredentialUnavailable('credential_unavailable')
        snapshot = snapshot_connection(connection)
        require_active_snapshot(snapshot)
        return {'schema_version': SNAPSHOT_SCHEMA_VERSION, **asdict(snapshot)}


def check_at_claim(snapshot_data: dict, *, task_owner_id: int) -> ConnectionSnapshot:
    """Revalidate queue claim AND each retry; do not roll a stale epoch forward."""
    snapshot = _decode(snapshot_data, task_owner_id)
    require_active_snapshot(snapshot)
    return snapshot


def is_revoked(snapshot_data: dict, *, task_owner_id: int) -> bool:
    """Best-effort cooperative cancellation poll for long-running work."""
    try:
        check_at_claim(snapshot_data, task_owner_id=task_owner_id)
        return False
    except CredentialUnavailable:
        return True


def dispatch_once(snapshot_data: dict, *, task_owner_id: int,
                  send: Callable[[str], T]) -> T:
    """Authorize immediately before ONE upstream send; never retry implicitly.

    The injected send callback receives a request-scoped plaintext Key. It must
    not persist/log the Key. A send already admitted before a concurrent
    revocation may still reach upstream; no unbounded transaction surrounds I/O.
    """
    snapshot = _decode(snapshot_data, task_owner_id)
    return send(read_execution_credential(snapshot))


def commit_result(snapshot_data: dict, *, task_owner_id: int,
                  persist: Callable[[], T]) -> T:
    """Run a short, DB-only terminal result commit under the revocation fence.

    Persist must include task lease/generation and terminal status checks in the
    same transaction. Exceptions roll back the entire result write. Never put
    network I/O, SSE streaming or lengthy processing in this callback.
    """
    snapshot = _decode(snapshot_data, task_owner_id)
    with locked_active_connection(snapshot):
        return persist()
