import threading


class EmbeddingService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._model = None
            return cls._instance

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                'paraphrase-multilingual-MiniLM-L12-v2'
            )
        return self._model

    def encode(self, text):
        if not text or not text.strip():
            return [0.0] * 384
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def encode_batch(self, texts, batch_size=32):
        if not texts:
            return []
        return self.model.encode(
            texts, normalize_embeddings=True, batch_size=batch_size
        ).tolist()
