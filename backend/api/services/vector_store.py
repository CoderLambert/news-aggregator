import os
import threading
from contextlib import contextmanager
from pathlib import Path

import chromadb

from .embedding import EmbeddingService

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows local development
    fcntl = None


DEFAULT_COLLECTION = 'news_embeddings'
COLLECTION_METADATA = {'hnsw:space': 'cosine'}


class VectorStoreService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._client = None
                cls._instance._collections = {}
                cls._instance._operation_lock = threading.RLock()
            return cls._instance

    @property
    def chroma_dir(self):
        from django.conf import settings
        path = Path(settings.BASE_DIR).parent / 'chroma_data'
        path.mkdir(parents=True, exist_ok=True)
        return path

    @contextmanager
    def _data_lock(self, *, exclusive=False):
        """Coordinate local Chroma readers and writers across processes."""
        with self._operation_lock:
            lock_path = self.chroma_dir / '.index.lock'
            handle = lock_path.open('a+')
            try:
                if fcntl is not None:
                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
                    )
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()

    @property
    def client(self):
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self.chroma_dir))
        return self._client

    def active_collection_name(self):
        try:
            from api.models import SearchIndexSettings
            value = (
                SearchIndexSettings.objects.filter(pk=1)
                .values_list('active_collection', flat=True)
                .first()
            )
            return value or DEFAULT_COLLECTION
        except Exception:
            # Migrations and first boot must remain able to use the legacy name.
            return DEFAULT_COLLECTION

    def get_collection(self, collection_name=None, *, create=True):
        name = collection_name or self.active_collection_name()
        cached = self._collections.get(name)
        if cached is not None:
            return cached
        if create:
            collection = self.client.get_or_create_collection(
                name=name,
                metadata=COLLECTION_METADATA,
            )
        else:
            collection = self.client.get_collection(name=name)
        self._collections[name] = collection
        return collection

    @property
    def collection(self):
        return self.get_collection()

    def create_collection(self, collection_name):
        with self._data_lock(exclusive=True):
            return self.get_collection(collection_name, create=True)

    def collection_exists(self, collection_name):
        with self._data_lock():
            return any(
                getattr(item, 'name', item) == collection_name
                for item in self.client.list_collections()
            )

    def delete_collection(self, collection_name):
        with self._data_lock(exclusive=True):
            exists = any(
                getattr(item, 'name', item) == collection_name
                for item in self.client.list_collections()
            )
            if exists:
                self.client.delete_collection(name=collection_name)
            self._collections.pop(collection_name, None)

    def add_news(self, news_id, text, *, metadata=None, collection_name=None):
        embedding = EmbeddingService().encode(text)
        record = {'news_id': int(news_id), **(metadata or {})}
        with self._data_lock(exclusive=True):
            self.get_collection(collection_name).upsert(
                ids=[str(news_id)],
                embeddings=[embedding],
                metadatas=[record],
            )

    def add_news_batch(
        self,
        news_ids,
        texts,
        *,
        metadatas=None,
        collection_name=None,
        batch_size=32,
    ):
        embedding_svc = EmbeddingService()
        embeddings = embedding_svc.encode_batch(texts, batch_size=batch_size)
        records = metadatas or [{'news_id': int(nid)} for nid in news_ids]
        with self._data_lock(exclusive=True):
            self.get_collection(collection_name).upsert(
                ids=[str(nid) for nid in news_ids],
                embeddings=embeddings,
                metadatas=records,
            )

    def search(self, query, n=20, *, collection_name=None):
        if not query or not query.strip():
            return []
        embedding = EmbeddingService().encode(query)
        with self._data_lock():
            collection = self.get_collection(collection_name, create=False)
            count = collection.count()
            results = collection.query(
                query_embeddings=[embedding],
                n_results=min(n, count) if count > 0 else 1,
            )
        if not results['ids'] or not results['ids'][0]:
            return []
        ids = [int(x) for x in results['ids'][0]]
        distances = results['distances'][0]
        return list(zip(ids, distances))

    def delete_news(self, news_id, *, collection_name=None):
        with self._data_lock(exclusive=True):
            self.get_collection(collection_name).delete(ids=[str(news_id)])

    def delete_news_batch(self, news_ids, *, collection_name=None):
        if not news_ids:
            return
        with self._data_lock(exclusive=True):
            self.get_collection(collection_name).delete(
                ids=[str(news_id) for news_id in news_ids]
            )

    def get_records(self, *, collection_name=None):
        with self._data_lock():
            result = self.get_collection(collection_name, create=False).get(
                include=['metadatas']
            )
        ids = result.get('ids') or []
        metadata = result.get('metadatas') or []
        return {
            int(news_id): (metadata[index] or {})
            for index, news_id in enumerate(ids)
        }

    def get_stored_ids(self, *, collection_name=None):
        return set(self.get_records(collection_name=collection_name))

    def count(self, *, collection_name=None):
        with self._data_lock():
            return self.get_collection(collection_name, create=False).count()
