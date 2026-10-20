"""Read current stored article context without publisher IO."""


def pick_chat_context(news, user=None, *, translation_result_id=None, translation_mode=None,
                      stored=None, with_metadata=False):
    """Resolve original/current/exact saved-result evidence without dispatching work."""
    from hashlib import sha256
    from api.services.stored_readers import (
        article_snapshot, translation_for_read,
    )

    if translation_mode is None:
        translation_mode = 'result' if translation_result_id not in (None, '') else 'current'
    if (not isinstance(translation_mode, str)
            or translation_mode not in {'current', 'original', 'result'}
            or (translation_mode == 'result' and translation_result_id in (None, ''))
            or (translation_mode != 'result' and translation_result_id not in (None, ''))):
        raise ValueError('invalid_translation_selection')

    stored = stored or article_snapshot(news, user)
    if translation_mode == 'original':
        text = stored.markdown
        metadata = {
            'source': 'original', 'current_match': True,
            'content_hash': sha256(text.encode('utf-8')).hexdigest(),
        }
        return (text, metadata) if with_metadata else text

    selected_id = translation_result_id if translation_mode == 'result' else None
    record, visibility = translation_for_read(user, stored, selected_id)
    if record is None:
        text = stored.markdown
        metadata = {
            'source': 'original', 'current_match': True,
            'content_hash': sha256(text.encode('utf-8')).hexdigest(),
        }
    else:
        text = record.content
        is_byok = getattr(record, 'api_connection_id', None) is not None
        current_match = (
            bool(getattr(record, 'current_match', False))
            if is_byok else
            getattr(record, 'source_hash', stored.canonical_hash) == stored.canonical_hash
        )
        metadata = {
            'source': 'byok' if is_byok else visibility,
            'current_match': current_match,
            'content_hash': sha256(text.encode('utf-8')).hexdigest(),
        }
        source_hash = getattr(record, 'source_hash', None)
        if isinstance(source_hash, str):
            metadata['source_hash'] = source_hash
        metadata['source_revision'] = (
            getattr(record, 'source_revision', None) if is_byok else stored.revision
        )
        metadata['source_title'] = (
            getattr(record, 'source_title', '') if is_byok and not current_match else stored.title
        )
        if getattr(record, 'pk', None) is not None:
            metadata['result_id'] = record.pk
        task_id = getattr(record, 'task_id', None)
        if task_id:
            metadata['task_id'] = str(task_id)
        model_slug = getattr(record, 'model_slug', None)
        if model_slug:
            metadata['model'] = model_slug
    return (text, metadata) if with_metadata else text


def context_scope(news, user=None):
    from api.services.stored_readers import article_snapshot
    return article_snapshot(news, user).scope
