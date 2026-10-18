"""T04 explicit per-turn BYOK chat through the current trusted one-shot gateway.

No implicit personal model selection, site-Key fallback or response-token
streaming. The pinned Chat Completions gateway deliberately verifies a
complete 'stop' reply before any answer text is exposed downstream; T04 uses
the existing article/chat session stream only to transport that verified turn.
"""
from dataclasses import asdict
from uuid import UUID

from django.http import Http404

from api.services.ai_credentials import CredentialUnavailable
from api.services.ai_gateway import AIGatewayError, build_gateway_client
from api.services.ai_task_preferences import (
    ModelSelectionError, require_task_model_snapshot, resolve_task_model,
)
from api.services.ai_worker_fencing import (
    SNAPSHOT_SCHEMA_VERSION, commit_result, dispatch_once,
)
from api.services.chat_history import ChatConflict, append_assistant_message
from api.services.stored_readers import StoredContentChanged, require_current, snapshot_metadata


MAX_CHAT_OUTPUT_TOKENS = 2048
MAX_CHAT_ANSWER_CHARS = 32768


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
    return selection


def _verified_answer(gateway, model_alias, messages):
    """Read the entire provider response before releasing *any* answer bytes.

    Our existing gateway adapter converts stream=True to a single verified
    completion and enforces finish_reason='stop'. Double-check its narrow
    chunk interface so a future adapter change cannot silently trust EOF.
    """
    stream = gateway.chat.completions.create(
        model=model_alias, messages=messages, stream=True,
        max_tokens=MAX_CHAT_OUTPUT_TOKENS, temperature=0.7,
    )
    pieces = []
    total = 0
    stopped = False
    try:
        for frame in stream:
            if stopped:
                raise ArticleChatError('incomplete_response')
            choices = getattr(frame, 'choices', None)
            if not isinstance(choices, (list, tuple)) or len(choices) != 1:
                raise ArticleChatError('incomplete_response')
            choice = choices[0]
            reason = getattr(choice, 'finish_reason', None)
            if reason not in (None, 'stop'):
                raise ArticleChatError('incomplete_response')
            content = getattr(getattr(choice, 'delta', None), 'content', None)
            if content is not None:
                if not isinstance(content, str):
                    raise ArticleChatError('incomplete_response')
                total += len(content)
                if total > MAX_CHAT_ANSWER_CHARS:
                    raise ArticleChatError('incomplete_response')
                pieces.append(content)
            if reason == 'stop':
                stopped = True
    finally:
        close = getattr(stream, 'close', None)
        if close:
            close()
    text = ''.join(pieces)
    if not stopped or not text.strip():
        raise ArticleChatError('incomplete_response')
    return text


def complete_article_chat(*, user, stored, chat_snapshot, messages, selection):
    """Exactly one approved send then fenced, version-bound successful history.

    Called by the existing NewsChatView only when an explicit model_config_id
    is supplied. A cancelled, incomplete or stale turn stays only as the user
    question in private history; it is NEVER persisted as a completed answer.
    """
    if selection.task_kind != 'article_qa' or selection.user_id != user.pk:
        raise ArticleChatError('model_unavailable')
    if (not isinstance(messages, list) or len(messages) > 24
            or any(not isinstance(msg, dict) or msg.get('role') not in {'system', 'user', 'assistant'}
                   or not isinstance(msg.get('content'), str) for msg in messages)
            or sum(len(msg['content']) for msg in messages) > 48000):
        raise ArticleChatError('context_unavailable')
    try:
        require_current(user, stored)
        require_task_model_snapshot(selection, owner_id=user.pk)
    except (ModelSelectionError, StoredContentChanged, Http404):
        raise ArticleChatError('execution_changed') from None

    connection_data = {
        'schema_version': SNAPSHOT_SCHEMA_VERSION,
        **asdict(selection.connection),
    }

    def send(provider_key):
        gateway = None
        try:
            # Recheck T02 model/probe immediately before the only billable send,
            # after T01 dispatch_once admitted the connection credential.
            require_task_model_snapshot(selection, owner_id=user.pk)
            require_current(user, stored)
            gateway = build_gateway_client(provider_key)
            return _verified_answer(gateway, selection.proxy_alias, messages)
        except ArticleChatError:
            raise
        except (ModelSelectionError, StoredContentChanged, Http404):
            raise ArticleChatError('execution_changed') from None
        except AIGatewayError:
            raise ArticleChatError('incomplete_response') from None
        except Exception:
            # Provider/network/SDK errors may contain secrets or user material.
            raise ArticleChatError('provider_unavailable') from None
        finally:
            if gateway is not None:
                gateway.close()

    try:
        # Credential checks and one send are isolated from transaction-bound
        # final persistence; never auto retry an ambiguous billable result.
        answer = dispatch_once(connection_data, task_owner_id=user.pk, send=send)

        def persist():
            model = require_task_model_snapshot(selection, owner_id=user.pk)
            require_current(user, stored)
            source = {'provider': model.connection.provider_id, 'model': model.display_name}
            append_assistant_message(
                user_id=user.pk, news_id=stored.news_id,
                session_id=chat_snapshot.session_id, generation=chat_snapshot.generation,
                content=answer, status='complete',
                article_context=snapshot_metadata(stored), model_source=source,
            )
            return source

        source = commit_result(connection_data, task_owner_id=user.pk, persist=persist)
        return answer, source
    except (CredentialUnavailable, ModelSelectionError, StoredContentChanged, Http404, ChatConflict):
        raise ArticleChatError('execution_changed') from None
