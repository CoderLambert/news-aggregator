import hashlib
import re
from dataclasses import dataclass

from django.db.models import Max
from django.utils import timezone

from api.models import News, SearchIndexRun, SearchIndexSettings
from api.services.embedding import MODEL_NAME
from api.services.search_index_control import INDEX_SCHEMA_VERSION, get_search_index_settings
from api.services.vector_store import VectorStoreService


_WHITESPACE = re.compile(r'\s+')


class SearchIndexCancelled(Exception):
    pass


@dataclass(frozen=True)
class IndexAudit:
    available: bool
    news_count: int
    vector_count: int
    missing_count: int
    changed_count: int
    orphaned_count: int
    error_code: str = ''


def normalize_index_text(value):
    return _WHITESPACE.sub(' ', (value or '').strip())


def build_index_text(title, content):
    clean_title = normalize_index_text(title)
    clean_content = normalize_index_text((content or '')[:500])
    return f'{clean_title}\n{clean_content}'.strip()


def index_source_hash(text, *, model_name=MODEL_NAME, schema_version=INDEX_SCHEMA_VERSION):
    payload = f'{schema_version}\0{model_name}\0{text}'.encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _metadata(news_id, source_hash, settings):
    return {
        'news_id': int(news_id),
        'source_hash': source_hash,
        'schema_version': settings.schema_version,
        'model_name': settings.model_name,
        'indexed_at': timezone.now().isoformat(),
    }


def audit_search_index(*, include_changed=True):
    news_count = News.objects.count()
    settings = get_search_index_settings()
    if (
        settings.model_name != MODEL_NAME
        or settings.schema_version != INDEX_SCHEMA_VERSION
    ):
        return IndexAudit(
            False,
            news_count,
            0,
            0,
            news_count,
            0,
            'index_version_mismatch',
        )
    try:
        records = VectorStoreService().get_records()
    except Exception:
        return IndexAudit(False, news_count, 0, news_count, 0, 0, 'vector_store_unavailable')

    database_ids = set(News.objects.values_list('id', flat=True))
    stored_ids = set(records)
    changed = 0
    if include_changed:
        for news_id, title, content in News.objects.values_list('id', 'title', 'content').iterator(chunk_size=500):
            text = build_index_text(title, content)
            expected = index_source_hash(
                text,
                model_name=settings.model_name,
                schema_version=settings.schema_version,
            )
            if news_id in records and records[news_id].get('source_hash') != expected:
                changed += 1
    return IndexAudit(
        True,
        news_count,
        len(stored_ids),
        len(database_ids - stored_ids),
        changed,
        len(stored_ids - database_ids),
    )


def _update_progress(run_id, **values):
    values['heartbeat_at'] = timezone.now()
    SearchIndexRun.objects.filter(pk=run_id).update(**values)


def _check_cancel(run_id, callback):
    if callback and callback():
        raise SearchIndexCancelled()
    if SearchIndexRun.objects.filter(pk=run_id, status='cancel_requested').exists():
        raise SearchIndexCancelled()


def _reconcile_pass(
    *,
    run_id,
    collection_name,
    settings,
    max_news_id,
    count_changes=True,
    progress_base=0,
    heartbeat=None,
    cancel_requested=None,
):
    vector_store = VectorStoreService()
    stored = vector_store.get_records(collection_name=collection_name)
    batch_ids = []
    batch_texts = []
    batch_metadata = []
    missing = changed = upserted = 0

    def flush():
        nonlocal upserted, batch_ids, batch_texts, batch_metadata
        if not batch_ids:
            return
        _check_cancel(run_id, cancel_requested)
        vector_store.add_news_batch(
            batch_ids,
            batch_texts,
            metadatas=batch_metadata,
            collection_name=collection_name,
            batch_size=min(64, settings.batch_size),
        )
        upserted += len(batch_ids)
        _update_progress(run_id, upserted_count=progress_base + upserted)
        if heartbeat:
            heartbeat()
        batch_ids = []
        batch_texts = []
        batch_metadata = []

    # Keyset pages close their SQLite read cursor before progress writes. A
    # long-lived QuerySet.iterator() cursor would attempt to upgrade the same
    # connection from read to write and can fail immediately under WAL.
    last_id = 0
    while last_id < max_news_id:
        rows = list(
            News.objects.filter(id__gt=last_id, id__lte=max_news_id)
            .order_by('id')
            .values_list('id', 'title', 'content')[:500]
        )
        if not rows:
            break
        last_id = rows[-1][0]
        for news_id, title, content in rows:
            text = build_index_text(title, content)
            digest = index_source_hash(
                text,
                model_name=settings.model_name,
                schema_version=settings.schema_version,
            )
            existing = stored.get(news_id)
            if existing is None:
                missing += 1
            elif existing.get('source_hash') == digest:
                continue
            else:
                changed += 1
            batch_ids.append(news_id)
            batch_texts.append(text)
            batch_metadata.append(_metadata(news_id, digest, settings))
            if len(batch_ids) >= settings.batch_size:
                flush()
    flush()
    if count_changes:
        _update_progress(
            run_id,
            missing_count=missing,
            changed_count=changed,
            upserted_count=progress_base + upserted,
        )
    return missing, changed, upserted


def synchronize_search_index(run_id, *, heartbeat=None, cancel_requested=None):
    run = SearchIndexRun.objects.get(pk=run_id)
    settings = get_search_index_settings()
    vector_store = VectorStoreService()
    old_collection = settings.active_collection
    if run.mode == 'rebuild':
        # Use the code's target contract in memory. The persisted settings keep
        # describing the active collection until the replacement is verified.
        settings.model_name = MODEL_NAME
        settings.schema_version = INDEX_SCHEMA_VERSION
        collection_name = f'news_embeddings_{INDEX_SCHEMA_VERSION}_{str(run.id)[:8]}'
        vector_store.create_collection(collection_name)
    else:
        if (
            settings.model_name != MODEL_NAME
            or settings.schema_version != INDEX_SCHEMA_VERSION
        ):
            raise RuntimeError('index_rebuild_required')
        collection_name = old_collection
        if not vector_store.collection_exists(collection_name):
            vector_store.create_collection(collection_name)

    max_news_id = News.objects.aggregate(value=Max('id'))['value'] or 0
    news_count = News.objects.filter(id__lte=max_news_id).count()
    before = vector_store.count(collection_name=collection_name)
    _update_progress(
        run_id,
        collection_name=collection_name,
        model_name=settings.model_name,
        schema_version=settings.schema_version,
        news_count=news_count,
        vector_count_before=before,
    )

    try:
        missing, changed, upserted = _reconcile_pass(
            run_id=run_id,
            collection_name=collection_name,
            settings=settings,
            max_news_id=max_news_id,
            heartbeat=heartbeat,
            cancel_requested=cancel_requested,
        )
        _check_cancel(run_id, cancel_requested)

        # A rebuild receives bounded catch-up passes before activation so news
        # created while earlier passes ran can enter the replacement collection.
        # If writes never settle, the equality guard below keeps the old
        # collection active and a later task can retry safely.
        if run.mode == 'rebuild':
            for _ in range(3):
                catchup_max = News.objects.aggregate(value=Max('id'))['value'] or 0
                if catchup_max <= max_news_id:
                    break
                _, _, catchup_upserts = _reconcile_pass(
                    run_id=run_id,
                    collection_name=collection_name,
                    settings=settings,
                    max_news_id=catchup_max,
                    count_changes=False,
                    progress_base=upserted,
                    heartbeat=heartbeat,
                    cancel_requested=cancel_requested,
                )
                upserted += catchup_upserts
                max_news_id = catchup_max
                _update_progress(run_id, upserted_count=upserted)

        current_ids = set(News.objects.values_list('id', flat=True))
        stored_ids = vector_store.get_stored_ids(collection_name=collection_name)
        orphaned = sorted(stored_ids - current_ids)
        deleted = 0
        for offset in range(0, len(orphaned), settings.batch_size):
            _check_cancel(run_id, cancel_requested)
            chunk = orphaned[offset:offset + settings.batch_size]
            vector_store.delete_news_batch(chunk, collection_name=collection_name)
            deleted += len(chunk)
            _update_progress(run_id, deleted_count=deleted)
            if heartbeat:
                heartbeat()

        after = vector_store.count(collection_name=collection_name)
        final_news_count = len(current_ids)
        if run.mode == 'rebuild':
            final_ids = vector_store.get_stored_ids(collection_name=collection_name)
            final_database_ids = set(News.objects.values_list('id', flat=True))
            if final_ids != final_database_ids:
                raise RuntimeError('replacement_collection_not_consistent')
            final_news_count = len(final_database_ids)
            SearchIndexSettings.objects.filter(pk=settings.pk).update(
                active_collection=collection_name,
                model_name=MODEL_NAME,
                schema_version=INDEX_SCHEMA_VERSION,
            )

        _update_progress(
            run_id,
            news_count=final_news_count,
            vector_count_after=after,
            missing_count=missing,
            changed_count=changed,
            orphaned_count=len(orphaned),
            upserted_count=upserted,
            deleted_count=deleted,
        )
        return {
            'collection_name': collection_name,
            'news_count': final_news_count,
            'vector_count_before': before,
            'vector_count_after': after,
            'missing_count': missing,
            'changed_count': changed,
            'orphaned_count': len(orphaned),
            'upserted_count': upserted,
            'deleted_count': deleted,
        }
    except Exception:
        if run.mode == 'rebuild' and collection_name != old_collection:
            try:
                vector_store.delete_collection(collection_name)
            except Exception:
                pass
        raise
