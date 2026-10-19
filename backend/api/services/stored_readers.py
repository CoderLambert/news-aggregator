"""Current stored snapshots shared by AI, translation and speech readers."""
from django.http import Http404
from django.db import OperationalError
from api.rss.operations import sqlite_retry
from api.rss.access import get_stored_article


class StoredContentChanged(Exception):
    pass


def article_snapshot(news, user=None):
    return get_stored_article(user if user is not None else getattr(news, '_rss_access_user', None), news.pk)


def require_current(user, stored, *, full=False):
    try:
        return _require_current(user, stored, full=full)
    except OperationalError:
        # Exhausted DB contention is a safe unavailable read, never permission
        # to return a stale snapshot or leak a database exception into SSE.
        raise StoredContentChanged('读取暂不可用，请重试。') from None


@sqlite_retry
def _require_current(user, stored, *, full=False):
    if getattr(user, 'is_authenticated', False):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
        if user is None:
            raise Http404
    current = get_stored_article(user, stored.news_id)
    if ((full and current.scope != 'full') or current.scope != stored.scope
            or current.canonical_hash != stored.canonical_hash or current.revision != stored.revision
            or current.title != stored.title or current.summary != stored.summary
            or current.provenance != stored.provenance
            or current.policy_versions != stored.policy_versions):
        raise StoredContentChanged('原文或读取权限已变化，请重新打开文章。')
    return current


def snapshot_metadata(stored):
    import json
    from hashlib import sha256
    return dict(context_scope=stored.scope, full_content_revision=stored.revision,
                canonical_hash=stored.canonical_hash, content_completeness=stored.completeness,
                provenance_hash=sha256(json.dumps(stored.provenance, sort_keys=True).encode()).hexdigest())


class PrivateTranslationNotFound(Exception):
    """An explicit completed private result is missing or unauthorized."""


def _valid_private_translation(record, user, stored):
    task = getattr(record, 'task', None)
    if (task is None or task.status != 'succeeded'
            or record.user_id != getattr(user, 'pk', None)
            or record.news_id != stored.news_id
            or record.api_connection_id is None or record.connection_id is not None
            or task.user_id != record.user_id or task.news_id != record.news_id
            or task.api_connection_id != record.api_connection_id or task.connection_id is not None
            or getattr(record.api_connection, 'user_id', None) != record.user_id
            or task.source_hash != record.source_hash or task.model_slug != record.model_slug):
        return False
    result = task.result if isinstance(task.result, dict) else {}
    if (result.get('result_id') != record.pk or result.get('task_id') != str(task.pk)
            or result.get('content') != record.content or result.get('source_hash') != record.source_hash
            or result.get('scope') != 'private' or result.get('target_language') != 'zh'):
        return False
    snapshot = task.execution_snapshot if isinstance(task.execution_snapshot, dict) else {}
    article = snapshot.get('article') if isinstance(snapshot.get('article'), dict) else {}
    record.current_match = record.source_hash == stored.canonical_hash
    record.source_title = article.get('title') if isinstance(article.get('title'), str) else ''
    record.source_revision = article.get('revision')
    return True


def _private_translation_for_hash(user, stored, source_hash=None, result_id=None):
    from api.models import ChatGPTArticleTranslation
    if not getattr(user, 'is_authenticated', False):
        if result_id is not None:
            raise PrivateTranslationNotFound
        return None
    require_current(user, stored, full=True)
    query = ChatGPTArticleTranslation.objects.select_related(
        'task', 'api_connection',
    ).filter(
        user_id=user.pk, news_id=stored.news_id,
        api_connection__isnull=False, api_connection__user_id=user.pk,
        connection__isnull=True,
    )
    if result_id is not None:
        if isinstance(result_id, bool):
            raise PrivateTranslationNotFound
        try:
            parsed_id = int(result_id)
        except (TypeError, ValueError):
            raise PrivateTranslationNotFound from None
        if parsed_id <= 0 or str(parsed_id) != str(result_id):
            raise PrivateTranslationNotFound
        record = query.filter(pk=parsed_id).first()
        if record is None or not _valid_private_translation(record, user, stored):
            raise PrivateTranslationNotFound
        return record
    if source_hash is not None:
        query = query.filter(source_hash=source_hash)
    for record in query.order_by('-completed_at', '-pk'):
        if _valid_private_translation(record, user, stored):
            return record
    return None


def private_translation_history(user, stored, *, limit=50):
    """Return recent validated owner-private results under the current full-body ACL."""
    if stored.scope != 'full' or not getattr(user, 'is_authenticated', False):
        return []
    from api.models import ChatGPTArticleTranslation
    require_current(user, stored, full=True)
    query = ChatGPTArticleTranslation.objects.select_related(
        'task', 'api_connection',
    ).filter(
        user_id=user.pk, news_id=stored.news_id,
        api_connection__isnull=False, api_connection__user_id=user.pk,
        connection__isnull=True, task__status='succeeded',
    ).order_by('-completed_at', '-pk')
    results = []
    requested_limit = max(1, min(int(limit), 100))
    for record in query.iterator(chunk_size=100):
        if _valid_private_translation(record, user, stored):
            results.append(record)
            if len(results) >= requested_limit:
                break
    return results


def private_translation_result(user, stored, result_id=None):
    """Read latest or explicit owner-private history under the current full-body ACL."""
    if result_id is not None:
        if stored.scope != 'full':
            raise PrivateTranslationNotFound
        return _private_translation_for_hash(user, stored, result_id=result_id)
    history = private_translation_history(user, stored, limit=1)
    return history[0] if history else None


def translation_for_read(user, stored, result_id=None):
    """Resolve one exact private result, or the ordinary current-translation fallback."""
    if result_id is not None:
        return _private_translation_for_hash(user, stored, result_id=result_id), 'private'
    return current_translation(user, stored)


def current_translation(user, stored, *, include_private=True):
    """Current-source translation: owner-private BYOK, subscription, shared, then legacy."""
    from api.models import ChatGPTArticleTranslation, SharedArticleTranslation
    from api.services.chatgpt_subscription import active_connection_for_user
    from api.services.shared_translations import cache_key
    require_current(user, stored)
    if stored.scope != 'full':
        return None, None
    if include_private and getattr(user, 'is_authenticated', False):
        record = _private_translation_for_hash(user, stored, source_hash=stored.canonical_hash)
        if record is not None:
            return record, 'private'
    connection = active_connection_for_user(user) if include_private and getattr(user, 'is_authenticated', False) else None
    if connection is not None:
        record = ChatGPTArticleTranslation.objects.filter(user=user, connection=connection,
            news_id=stored.news_id, source_hash=stored.canonical_hash).first()
        if record is not None:
            return record, 'private'
    record = SharedArticleTranslation.objects.filter(**cache_key(stored.news_id, stored.canonical_hash)).first()
    if record is not None:
        return record, 'shared'
    legacy = legacy_translation(stored.news_id, 'full_content', stored.markdown)
    if legacy is not None:
        from types import SimpleNamespace
        return SimpleNamespace(content=legacy.translated_text, completed_at=legacy.captured_at, provider='legacy'), 'legacy'
    return None, None

def legacy_translation(news_id, field, source_text):
    from hashlib import sha256
    from api.models import LegacyTranslationSnapshot
    return LegacyTranslationSnapshot.objects.filter(news_id=news_id, field=field,
        source_hash=sha256(source_text.encode('utf-8')).hexdigest(), source_text=source_text,
        origin__in=('legacy', 'legacy-bound')).order_by('-captured_at', '-pk').first()


def readable_chat_messages(messages, stored):
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, dict) and (
        message.get('role') == 'user' or message.get('article_context') == snapshot_metadata(stored))]


def filter_current_keyword(queryset, term, *, full=False):
    """Search originals and exact-source-bound legacy translations in SQL."""
    from django.db.models import Exists, OuterRef, Q
    from api.models import LegacyTranslationSnapshot
    translations = LegacyTranslationSnapshot.objects.filter(news_id=OuterRef('pk'),
        origin__in=('legacy', 'legacy-bound'), translated_text__icontains=term).filter(
            Q(field='title', source_text=OuterRef('title')) | Q(field='content', source_text=OuterRef('content')))
    match = Q(title__icontains=term) | Q(content__icontains=term) | Q(_bound_translation_match=True)
    if full:
        match |= Q(full_content__icontains=term)
    return queryset.alias(_bound_translation_match=Exists(translations)).filter(match)
