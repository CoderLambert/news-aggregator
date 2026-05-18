import os
import threading

import chromadb

from .embedding import EmbeddingService


class VectorStoreService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._client = None
                cls._instance._collection = None
            return cls._instance

    @property
    def client(self):
        if self._client is None:
            from django.conf import settings
            chroma_dir = os.path.join(
                os.path.dirname(settings.BASE_DIR), 'chroma_data'
            )
            self._client = chromadb.PersistentClient(path=chroma_dir)
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name='news_embeddings',
                metadata={'hnsw:space': 'cosine'},
            )
        return self._collection

    def add_news(self, news_id, text):
        embedding = EmbeddingService().encode(text)
        self.collection.upsert(
            ids=[str(news_id)],
            embeddings=[embedding],
            metadatas=[{'news_id': news_id}],
        )

    def add_news_batch(self, news_ids, texts):
        embedding_svc = EmbeddingService()
        embeddings = embedding_svc.encode_batch(texts)
        self.collection.upsert(
            ids=[str(nid) for nid in news_ids],
            embeddings=embeddings,
            metadatas=[{'news_id': nid} for nid in news_ids],
        )

    def search(self, query, n=20):
        if not query or not query.strip():
            return []
        embedding = EmbeddingService().encode(query)
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(n, self.collection.count()) if self.collection.count() > 0 else 1,
        )
        if not results['ids'] or not results['ids'][0]:
            return []
        ids = [int(x) for x in results['ids'][0]]
        distances = results['distances'][0]
        return list(zip(ids, distances))

    def delete_news(self, news_id):
        try:
            self.collection.delete(ids=[str(news_id)])
        except Exception:
            pass

    def get_stored_ids(self):
        existing = self.collection.get(include=[])
        return set(int(x) for x in existing['ids']) if existing['ids'] else set()

    def count(self):
        return self.collection.count()
