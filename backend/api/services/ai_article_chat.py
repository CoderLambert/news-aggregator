"""T04 explicit per-turn BYOK chat with verified, token-by-token streaming.

The only stream route is the pinned DeepSeek alias whose LiteLLM Proxy hook
validates the upstream finish reason before releasing the terminal chunk.
"""
from dataclasses import asdict
import time
from uuid import UUID

from django.http import Http404
from django.db import OperationalError, connection

from api.services.ai_credentials import CredentialUnavailable
from api.services.ai_model_registry import ARTICLE_CHAT_SUPPORTED_ALIAS
from api.services.ai_gateway import AIGatewayError, build_gateway_client
from api.services.ai_task_preferences import (
    ModelSelectionError, require_task_model_snapshot, resolve_task_model,
)
from api.services.ai_worker_fencing import (
    SNAPSHOT_SCHEMA_VERSION, commit_result, dispatch_once,
)
from api.services.chat_history import ChatConflict, _is_sqlite_busy, append_assistant_message
from api.services.ai_article_turns import (
    ArticleChatTurnError, cancel_turn, mark_dispatched, mark_complete,
    require_dispatched,
)
from api.services.stored_readers import StoredContentChanged, require_current, snapshot_metadata


MAX_CHAT_OUTPUT_TOKENS = 2048
MAX_CHAT_ANSWER_CHARS = 32768
SUPPORTED_STREAM_ALIAS = ARTICLE_CHAT_SUPPORTED_ALIAS


MAX_TERMINAL_COMMIT_ATTEMPTS = 5


def _commit_article_result(snapshot_data, *, task_owner_id, persist):
    """Retry only a rolled-back, DB-only T04 terminal transaction.

    The callback must recheck article/model/turn/generation on every attempt.
    Provider dispatch and streaming stay outside this boundary. Never retry a
    caller-owned transaction or a non-SQLite/non-contention database failure.
    """
    outer_atomic = connection.in_atomic_block
    for attempt in range(1, MAX_TERMINAL_COMMIT_ATTEMPTS + 1):
        try:
            return commit_result(
                snapshot_data, task_owner_id=task_owner_id, persist=persist,
            )
        except (OperationalError, ChatConflict) as error:
            # commit_result's owner/credential transaction has exited and rolled
            # back before this catch; the next attempt obtains a fresh fence.
            busy_error = error.__cause__ if isinstance(error, ChatConflict) else error
            if (outer_atomic or not isinstance(busy_error, OperationalError)
                    or not _is_sqlite_busy(busy_error)
                    or attempt == MAX_TERMINAL_COMMIT_ATTEMPTS):
                raise
            time.sleep(0.005 * attempt)


class ArticleChatError(RuntimeError):
    """Only expose one small safe error code; never upstream URLs or tokens."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def prepare_article_chat(user, model_config_id):
    """Never infer an explicit billing intent from a saved preference alone."""
    if type(model_config_id) is not str or len(model_config_id) != 36:
        raise ArticleChatError('invalid_model_selection')
    try:
        model_uuid = UUID(model_config_id)
        if str(model_uuid) != model_config_id:
            raise ValueError
    except (TypeError, ValueError):
        raise ArticleChatError('invalid_model_selection') from None
    try:
        selection = resolve_task_model(
            user, 'article_qa', explicit_model_id=model_uuid,
        )
        require_task_model_snapshot(selection, owner_id=user.pk)
    except ModelSelectionError as error:
        if error.code == 'model_not_found':
            raise ArticleChatError('model_not_found') from None
        raise ArticleChatError('model_unavailable') from None
    if selection.proxy_alias != SUPPORTED_STREAM_ALIAS:
        raise ArticleChatError('model_unavailable')
    return selection


def _check_execution(user, stored, selection, turn_id, *, dispatched=True):
    if dispatched:
        require_dispatched(user_id=user.pk, news_id=stored.news_id, turn_id=turn_id)
    require_current(user, stored)
    require_task_model_snapshot(selection, owner_id=user.pk)


def complete_article_chat(*, user, stored, chat_snapshot, messages, selection, turn_id):
    """Return a generator of delta events followed by one durable completion.

    The send callback opens the SDK stream synchronously inside dispatch_once,
    immediately after credential admission. Network reads/yields happen with no
    DB lock. The only complete event is emitted after real stop validation and
    fenced assistant-history persistence. Partial output may be visible on
    failure but is never retried or saved as a completed answer.
    """
    if selection.task_kind != 'article_qa' or selection.user_id != user.pk:
        raise ArticleChatError('model_unavailable')
    if selection.proxy_alias != SUPPORTED_STREAM_ALIAS:
        raise ArticleChatError('model_unavailable')
    if (not isinstance(messages, list) or len(messages) > 24
            or any(not isinstance(msg, dict) or msg.get('role') not in {'system', 'user', 'assistant'}
                   or not isinstance(msg.get('content'), str) for msg in messages)
            or sum(len(msg['content']) for msg in messages) > 48000):
        raise ArticleChatError('context_unavailable')

    def execute():
        try:
            _check_execution(user, stored, selection, turn_id, dispatched=False)
        except (ArticleChatTurnError, ModelSelectionError, StoredContentChanged, Http404) as error:
            if isinstance(error, ArticleChatTurnError):
                raise ArticleChatError(error.code) from None
            raise ArticleChatError('execution_changed') from None

        connection_data = {
            'schema_version': SNAPSHOT_SCHEMA_VERSION,
            **asdict(selection.connection),
        }
        gateway = None
        stream = None
        succeeded = False

        def send(provider_key):
            nonlocal gateway, stream
            try:
                # Repeat all mutable authorization checks at the exact send
                # boundary, then open the SDK stream before returning.
                _check_execution(user, stored, selection, turn_id, dispatched=False)
                mark_dispatched(
                    user_id=user.pk, news_id=stored.news_id, turn_id=turn_id,
                )
                gateway = build_gateway_client(provider_key)
                stream = gateway.chat.completions.create(
                    model=selection.proxy_alias, messages=messages,
                    stream=True, max_tokens=MAX_CHAT_OUTPUT_TOKENS,
                    temperature=0.7, reasoning_effort='none',
                )
                return stream
            except ArticleChatTurnError as error:
                raise ArticleChatError(error.code) from None
            except (ModelSelectionError, StoredContentChanged, Http404):
                raise ArticleChatError('execution_changed') from None
            except AIGatewayError:
                raise ArticleChatError('provider_unavailable') from None
            except Exception:
                raise ArticleChatError('provider_unavailable') from None

        try:
            # Credential checks and the single network request are outside any
            # long-lived transaction. Unknown provider outcomes are not retried.
            stream = dispatch_once(connection_data, task_owner_id=user.pk, send=send)
            pieces = []
            total = 0
            saw_stop = False
            usage_seen = False
            for frame in stream:
                try:
                    _check_execution(user, stored, selection, turn_id)
                except (ArticleChatTurnError, ModelSelectionError, StoredContentChanged, Http404) as error:
                    if isinstance(error, ArticleChatTurnError):
                        raise ArticleChatError(error.code) from None
                    raise ArticleChatError('execution_changed') from None

                choices = getattr(frame, 'choices', None)
                if not isinstance(choices, (list, tuple)):
                    raise ArticleChatError('incomplete_response')
                if not choices:
                    # The official SDK can expose one optional usage-only chunk
                    # either before or after the verified terminal.
                    if getattr(frame, 'usage', None) is None or usage_seen:
                        raise ArticleChatError('incomplete_response')
                    usage_seen = True
                    continue
                if len(choices) != 1:
                    raise ArticleChatError('incomplete_response')
                choice = choices[0]
                reason = getattr(choice, 'finish_reason', None)
                if reason not in (None, 'stop'):
                    raise ArticleChatError('incomplete_response')
                delta = getattr(choice, 'delta', None)
                if any(getattr(delta, name, None) for name in (
                    'tool_calls', 'function_call', 'refusal',
                )):
                    raise ArticleChatError('incomplete_response')
                content = getattr(delta, 'content', None)
                if content is not None:
                    if saw_stop or not isinstance(content, str):
                        raise ArticleChatError('incomplete_response')
                    total += len(content)
                    if total > MAX_CHAT_ANSWER_CHARS:
                        raise ArticleChatError('incomplete_response')
                    pieces.append(content)
                    yield {'type': 'delta', 'content': content}
                if reason == 'stop':
                    if saw_stop:
                        raise ArticleChatError('incomplete_response')
                    saw_stop = True
                elif saw_stop:
                    raise ArticleChatError('incomplete_response')

            answer = ''.join(pieces)
            if not saw_stop or not answer.strip():
                raise ArticleChatError('incomplete_response')

            def persist():
                model = require_task_model_snapshot(selection, owner_id=user.pk)
                require_current(user, stored)
                source = {'provider': model.connection.provider_id, 'model': model.display_name}
                mark_complete(
                    user_id=user.pk, news_id=stored.news_id, turn_id=turn_id,
                )
                append_assistant_message(
                    user_id=user.pk, news_id=stored.news_id,
                    session_id=chat_snapshot.session_id, generation=chat_snapshot.generation,
                    content=answer, status='complete',
                    article_context=snapshot_metadata(stored), model_source=source,
                )
                return source

            try:
                source = _commit_article_result(
                    connection_data, task_owner_id=user.pk, persist=persist,
                )
            except ArticleChatTurnError as error:
                raise ArticleChatError(error.code) from None
            except (CredentialUnavailable, ModelSelectionError, StoredContentChanged, Http404, ChatConflict):
                raise ArticleChatError('execution_changed') from None
            succeeded = True
            yield {'type': 'complete', 'model_source': source}
        except GeneratorExit:
            # Closing the HTTP response during an in-flight stream fences any
            # later commit. This records no false provider-success receipt.
            try:
                cancel_turn(user_id=user.pk, news_id=stored.news_id, turn_id=turn_id)
            except ArticleChatTurnError:
                pass
            raise
        except ArticleChatError:
            raise
        except ArticleChatTurnError as error:
            raise ArticleChatError(error.code) from None
        except (CredentialUnavailable, ModelSelectionError, StoredContentChanged, Http404, ChatConflict):
            raise ArticleChatError('execution_changed') from None
        except Exception:
            raise ArticleChatError('provider_unavailable') from None
        finally:
            close = getattr(stream, 'close', None)
            if close is not None:
                try:
                    close()
                except Exception:
                    if not succeeded:
                        pass
            if gateway is not None:
                try:
                    gateway.close()
                except Exception:
                    pass

    return execute()
