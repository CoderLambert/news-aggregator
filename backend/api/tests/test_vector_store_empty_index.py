"""A cold derived index must not break local keyword/hybrid readers."""
from unittest.mock import Mock

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError
import pytest

from api.services.vector_store import DEFAULT_COLLECTION, VectorStoreService


@pytest.fixture
def store(tmp_path, settings, monkeypatch):
    settings.SEMANTIC_SEARCH_ENABLED = True
    settings.PUBLIC_SITE_MODE = 'full'
    settings.PUBLIC_AI_ENABLED = True
    settings.CHROMA_DATA_DIR = str(tmp_path / 'index')
    monkeypatch.setattr(VectorStoreService, '_instance', None)
    service = VectorStoreService()
    monkeypatch.setattr(service, 'active_collection_name', lambda: DEFAULT_COLLECTION)
    return service


def test_default_count_on_fresh_chroma_is_zero_without_creating_collection(store):
    store._client = chromadb.PersistentClient(
        path=str(store.chroma_dir), settings=Settings(anonymized_telemetry=False),
    )
    assert store._client.list_collections() == []
    assert store.count() == 0
    assert store._client.list_collections() == []
    # Management/rebuild requests name a collection and must detect its loss.
    with pytest.raises(NotFoundError):
        store.count(collection_name=DEFAULT_COLLECTION)


def test_default_count_does_not_hide_other_storage_failures(store):
    store._client = Mock()
    store._client.get_collection.side_effect = RuntimeError('synthetic storage failure')
    with pytest.raises(RuntimeError, match='synthetic storage failure'):
        store.count()
