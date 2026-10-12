"""Read-only, owner-scoped resolution for completed article translations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from api.models import ChatGPTArticleTranslation, ChatGPTTranslationTask
from api.services.shared_translations import get_shared_translation, source_hash


class TranslationResultNotFound(Exception):
    """An explicit result is missing, belongs to another user, or another article."""


def _supported_result_id(result_id: str) -> bool:
    if not isinstance(result_id, str) or not result_id or len(result_id) > 64:
        return False
    try:
        uuid.UUID(result_id)
        return True
    except (AttributeError, TypeError, ValueError):
        return result_id.isdecimal() and len(result_id) <= 20 and int(result_id) > 0


@dataclass(frozen=True)
class ArticleTranslation:
    content: str
    source: str
    result_id: str | None
    source_hash: str | None
    current_match: bool | None
    fetched_at: datetime | None
    provider: str | None = None
    model: str | None = None


def _task_translation(task, current_hash: str) -> ArticleTranslation | None:
    payload = task.result if isinstance(task.result, dict) else {}
    content = payload.get('full_content_zh')
    if not isinstance(content, str) or not content.strip():
        return None
    model_source = payload.get('model_source')
    if not isinstance(model_source, dict):
        model_source = {}
    return ArticleTranslation(
        content=content,
        source='byok',
        result_id=str(task.pk),
        source_hash=task.source_hash,
        current_match=task.source_hash == current_hash,
        fetched_at=task.finished_at or task.updated_at,
        provider=model_source.get('provider') if isinstance(model_source.get('provider'), str) else task.provider_id_snapshot or None,
        model=model_source.get('model') if isinstance(model_source.get('model'), str) else task.model_slug,
    )


def _authenticated(user) -> bool:
    return bool(user is not None and getattr(user, 'is_authenticated', False))


def _task_by_uuid(query, result_id: str):
    try:
        task_id = uuid.UUID(str(result_id))
    except (AttributeError, TypeError, ValueError):
        return None
    return query.filter(pk=task_id).first()


def _find_byok_result(user, news, result_id: str, current_hash: str) -> ArticleTranslation | None:
    tasks = ChatGPTTranslationTask.objects.filter(
        user=user,
        news=news,
        ai_connection__isnull=False,
        status='succeeded',
    )
    task = _task_by_uuid(tasks, result_id)
    if task is None:
        # Older successful tasks used the mutable ChatGPTArticleTranslation row
        # UUID as result_id. Preserve those links while returning the task's
        # immutable canonical ID to new clients.
        for candidate in tasks.order_by('-finished_at', '-updated_at'):
            payload = candidate.result if isinstance(candidate.result, dict) else {}
            if payload.get('result_id') == result_id:
                task = candidate
                break
    return _task_translation(task, current_hash) if task is not None else None


def get_byok_result(user, news, result_id: str) -> ArticleTranslation:
    if not _authenticated(user) or not _supported_result_id(result_id):
        raise TranslationResultNotFound
    result = _find_byok_result(user, news, str(result_id), current_source_hash(news))
    if result is None:
        raise TranslationResultNotFound
    return result


def get_byok_result_for_owner(user, result_id: str) -> ArticleTranslation:
    if not _authenticated(user) or not _supported_result_id(result_id):
        raise TranslationResultNotFound
    tasks = ChatGPTTranslationTask.objects.filter(
        user=user,
        ai_connection__isnull=False,
        status='succeeded',
    ).select_related('news')
    task = _task_by_uuid(tasks, result_id)
    if task is None:
        for candidate in tasks.order_by('-finished_at', '-updated_at'):
            payload = candidate.result if isinstance(candidate.result, dict) else {}
            if payload.get('result_id') == str(result_id):
                task = candidate
                break
    if task is None:
        raise TranslationResultNotFound
    result = _task_translation(task, source_hash(task.news.full_content or ''))
    if result is None:
        raise TranslationResultNotFound
    return result


def _current_byok_result(user, news, digest: str) -> ArticleTranslation | None:
    tasks = ChatGPTTranslationTask.objects.filter(
        user=user,
        news=news,
        ai_connection__isnull=False,
        source_hash=digest,
        status='succeeded',
    ).order_by('-finished_at', '-updated_at')
    for task in tasks:
        result = _task_translation(task, digest)
        if result is not None:
            return result
    return None


def get_stale_byok_result(user, news) -> ArticleTranslation | None:
    if not _authenticated(user):
        return None
    digest = current_source_hash(news)
    tasks = ChatGPTTranslationTask.objects.filter(
        user=user,
        news=news,
        ai_connection__isnull=False,
        status='succeeded',
    ).exclude(source_hash=digest).order_by('-finished_at', '-updated_at')
    for task in tasks:
        result = _task_translation(task, digest)
        if result is not None:
            return result
    return None


def resolve_article_translation(news, user=None, result_id: str | None = None) -> ArticleTranslation | None:
    """Resolve an explicit owned result, then current personal/public/legacy output.

    This function is read-only: it never starts a task, contacts a provider, or
    refreshes credentials. An explicit unknown or unauthorized ID fails closed.
    """
    digest = source_hash(news.full_content or '')
    if result_id is not None:
        return get_byok_result(user, news, result_id)

    active_subscription = False
    if _authenticated(user):
        personal = _current_byok_result(user, news, digest)
        if personal is not None:
            return personal

        from api.services.chatgpt_subscription import active_connection_for_user

        connection = active_connection_for_user(user)
        active_subscription = connection is not None
        if connection is not None:
            subscription_result = ChatGPTArticleTranslation.objects.filter(
                user=user,
                connection=connection,
                news=news,
                source_hash=digest,
            ).first()
            if subscription_result is not None and subscription_result.content:
                return ArticleTranslation(
                    content=subscription_result.content,
                    source='subscription',
                    result_id=str(subscription_result.pk),
                    source_hash=subscription_result.source_hash,
                    current_match=True,
                    fetched_at=subscription_result.completed_at,
                    provider='chatgpt',
                    model=subscription_result.model_slug,
                )

    shared = get_shared_translation(news)
    if shared is not None:
        return ArticleTranslation(
            content=shared.content,
            source='shared',
            result_id=None,
            source_hash=shared.source_hash,
            current_match=True,
            fetched_at=shared.completed_at,
            provider=shared.provider,
            model=shared.model_slug,
        )

    # Keep the historic field as the final compatibility fallback. Its source
    # hash was never stored, so callers must not treat it as an identified
    # private result.
    if news.full_content_zh and not active_subscription:
        return ArticleTranslation(
            content=news.full_content_zh,
            source='legacy',
            result_id=None,
            source_hash=None,
            current_match=None,
            fetched_at=news.full_content_zh_fetched_at,
        )
    return None


def current_source_hash(news) -> str:
    return source_hash(news.full_content or '')


def result_payload(result: ArticleTranslation | None) -> dict:
    if result is None:
        return {
            'content': '', 'source': None, 'result_id': None,
            'source_hash': None, 'current_match': None, 'fetched_at': None,
            'model_source': None,
        }
    return {
        'content': result.content,
        'source': result.source,
        'result_id': result.result_id,
        'source_hash': result.source_hash,
        'current_match': result.current_match,
        'fetched_at': result.fetched_at,
        'model_source': (
            {'provider': result.provider, 'model': result.model}
            if result.provider or result.model else None
        ),
    }
