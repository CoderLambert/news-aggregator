"""Read current article context and request durable work without publisher IO."""
from api.services.full_content_status import has_full_content, get_readable_full_content, enqueue_fetch, fetch_eligibility
from api.services.full_content_worker import worker_health


def pick_chat_context(news):
    if has_full_content(news):
        from api.services.shared_translations import get_shared_translation
        shared = get_shared_translation(news)
        return (shared.content if shared else '') or news.full_content_zh or get_readable_full_content(news)
    return news.content_zh or news.content or ''


def context_scope(news):
    return 'full' if has_full_content(news) else 'summary'


def request_full_content(news, *, force=False, priority=0, execution_guard=None):
    from api.services.body_access import authorized_fetch
    if execution_guard:
        execution_guard()
    if has_full_content(news) and not force:
        return 'cached'
    if fetch_eligibility(news) or (news.full_content_fetch_status == 'blocked' or (news.full_content_fetch_status == 'unsupported' and not authorized_fetch(news))) or news.full_content_retry_count >= 5:
        return 'rejected'
    if not worker_health(require_enabled=True):
        return 'unavailable'
    outcome = enqueue_fetch(news, force=force, priority=priority)
    if execution_guard:
        execution_guard()
    return outcome
