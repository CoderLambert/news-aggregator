from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Category, News, SearchIndexRun, SearchIndexSettings, Source
from api.services.embedding import MODEL_NAME
from api.services.search_index import (
    cleanup_recovered_index_runs,
    synchronize_search_index,
)
from api.services.search_index_control import (
    INDEX_SCHEMA_VERSION,
    SearchIndexOwnershipLost,
    claim_next_index_run,
    finish_index_run,
    queue_search_index_run,
    recover_interrupted_index_runs,
)
from api.services.search_index_lock import (
    SearchIndexExecutionLockUnavailable,
    acquire_search_index_execution_lock,
)


class FakeVectorStore:
    def __init__(self, news_id, old_collection='news_embeddings'):
        self.news_id = news_id
        self.collections = {old_collection: {news_id}}
        self.deleted = []

    def create_collection(self, collection_name):
        self.collections[collection_name] = {self.news_id}

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def count(self, *, collection_name=None):
        return len(self.collections[collection_name])

    def get_stored_ids(self, *, collection_name=None):
        return set(self.collections[collection_name])

    def delete_collection(self, collection_name):
        self.deleted.append(collection_name)
        self.collections.pop(collection_name, None)


@pytest.fixture
def news(db):
    source = Source.objects.create(name='Index test source', url='https://example.com')
    category = Category.objects.create(name='Index test', slug='index-test')
    return News.objects.create(
        title='Index recovery test',
        content='Test content',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://example.com/index-recovery-test',
    )


@pytest.fixture
def index_settings(db):
    return SearchIndexSettings.objects.create(
        pk=1,
        active_collection='news_embeddings',
        model_name=MODEL_NAME,
        schema_version=INDEX_SCHEMA_VERSION,
    )


@pytest.mark.django_db
def test_fresh_interrupted_run_is_recovered_immediately_by_new_lock_owner(
    index_settings,
    news,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv('SEARCH_INDEX_WORKER_LOCK', str(tmp_path / 'worker.lock'))
    interrupted = SearchIndexRun.objects.create(
        trigger='manual',
        mode='rebuild',
        status='running',
        started_at=timezone.now(),
        heartbeat_at=timezone.now(),
        worker_instance_id='dead-worker',
        collection_name='candidate_from_dead_worker',
    )
    vector_store = FakeVectorStore(news.pk)
    vector_store.collections['candidate_from_dead_worker'] = {news.pk}

    with acquire_search_index_execution_lock():
        with pytest.raises(SearchIndexExecutionLockUnavailable):
            with acquire_search_index_execution_lock():
                pass
        recovered = recover_interrupted_index_runs(
            recovery_owner_id='replacement-worker',
            force=True,
        )
        assert [run.pk for run in recovered] == [interrupted.pk]
        with pytest.raises(SearchIndexOwnershipLost):
            finish_index_run(
                interrupted.pk,
                instance_id='dead-worker',
                status='succeeded',
            )
        assert cleanup_recovered_index_runs(recovered, vector_store=vector_store) == 1
        replacement, created = queue_search_index_run(trigger='startup', mode='sync')
        assert created
        claimed = claim_next_index_run('replacement-worker')

    interrupted.refresh_from_db()
    assert interrupted.status == 'failed'
    assert interrupted.safe_error_code == 'worker_interrupted'
    assert interrupted.worker_instance_id == 'replacement-worker'
    assert claimed.pk == replacement.pk
    assert claimed.status == 'running'
    assert claimed.worker_instance_id == 'replacement-worker'
    assert 'candidate_from_dead_worker' not in vector_store.collections
    assert index_settings.active_collection in vector_store.collections


@pytest.mark.django_db(transaction=True)
def test_rebuild_final_progress_failure_rolls_back_pointer_and_preserves_active_index(
    index_settings,
    news,
):
    run = SearchIndexRun.objects.create(
        trigger='manual',
        mode='rebuild',
        status='running',
        started_at=timezone.now(),
        heartbeat_at=timezone.now(),
        worker_instance_id='worker-a',
    )
    vector_store = FakeVectorStore(news.pk)

    with (
        patch('api.services.search_index.VectorStoreService', return_value=vector_store),
        patch('api.services.search_index._reconcile_pass', return_value=(0, 0, 0)),
        patch(
            'api.services.search_index._write_final_progress',
            side_effect=RuntimeError('injected_final_progress_failure'),
        ),
    ):
        with pytest.raises(RuntimeError, match='injected_final_progress_failure'):
            synchronize_search_index(run.pk)

    index_settings.refresh_from_db()
    candidate = f'news_embeddings_{INDEX_SCHEMA_VERSION}_{str(run.id)[:8]}'
    assert index_settings.active_collection == 'news_embeddings'
    assert 'news_embeddings' in vector_store.collections
    assert candidate not in vector_store.collections
    assert vector_store.deleted == [candidate]


@pytest.mark.django_db
def test_settings_patch_does_not_restore_stale_runtime_fields(index_settings, monkeypatch):
    user = get_user_model().objects.create_superuser(
        username='index-admin',
        email='index-admin@example.com',
        password='test-password',
    )
    client = APIClient()
    client.force_authenticate(user=user)

    from api.search_index_serializers import SearchIndexSettingsSerializer

    original_is_valid = SearchIndexSettingsSerializer.is_valid

    def validate_then_finish_rebuild(serializer, *args, **kwargs):
        valid = original_is_valid(serializer, *args, **kwargs)
        SearchIndexSettings.objects.filter(pk=index_settings.pk).update(
            active_collection='news_embeddings_news-v2_verified',
            model_name='new-model',
            schema_version='news-v2',
            worker_instance_id='new-worker',
            worker_heartbeat_at=timezone.now(),
        )
        return valid

    monkeypatch.setattr(SearchIndexSettingsSerializer, 'is_valid', validate_then_finish_rebuild)
    response = client.patch(
        '/api/admin/search-index/settings/',
        {'batch_size': 77},
        format='json',
    )

    assert response.status_code == 200
    index_settings.refresh_from_db()
    assert index_settings.batch_size == 77
    assert index_settings.active_collection == 'news_embeddings_news-v2_verified'
    assert index_settings.model_name == 'new-model'
    assert index_settings.schema_version == 'news-v2'
    assert index_settings.worker_instance_id == 'new-worker'
    assert index_settings.updated_by == user
