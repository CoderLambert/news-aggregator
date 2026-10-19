"""Read current article context and request durable work without publisher IO."""
from api.services.full_content_status import has_full_content, enqueue_fetch, fetch_eligibility
from api.services.full_content_worker import worker_health


def pick_chat_context(news, user=None, *, translation_result_id=None, stored=None, with_metadata=False):
    """Use the same owner-private/current translation result as detail and TTS."""
    from api.services.stored_readers import article_snapshot, translation_for_read
    stored = stored or article_snapshot(news, user)
    record, visibility = translation_for_read(user, stored, translation_result_id)
    if record is None:
        text = stored.markdown
        metadata = {'source': 'original', 'current_match': True}
    else:
        is_byok = getattr(record, 'api_connection_id', None) is not None
        current_match = getattr(record, 'source_hash', stored.canonical_hash) == stored.canonical_hash
        metadata = {'source': 'byok' if is_byok else visibility, 'current_match': current_match}
        if is_byok:
            metadata.update({
                'result_id': record.pk, 'task_id': str(record.task_id),
                'model': record.model_slug, 'source_hash': record.source_hash,
                'source_revision': getattr(record, 'source_revision', None),
                'source_title': getattr(record, 'source_title', '') if not current_match else stored.title,
            })
        text = record.content
    return (text, metadata) if with_metadata else text


def context_scope(news, user=None):
    from api.services.stored_readers import article_snapshot
    return article_snapshot(news, user).scope


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
