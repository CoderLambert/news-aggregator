import logging
import threading

logger = logging.getLogger(__name__)


class EmbeddingService:
    _instance = None
    _lock = threading.Lock()
    _model_lock = threading.Lock()
    _ready_event = threading.Event()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._model = None
            return cls._instance

    @property
    def model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            from sentence_transformers import SentenceTransformer
            logger.info('Loading sentence-transformer model...')
            self._model = SentenceTransformer(
                'paraphrase-multilingual-MiniLM-L12-v2'
            )
            logger.info('Sentence-transformer model loaded.')
            self._ready_event.set()
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

    @classmethod
    def preload(cls):
        """Load the model in a background thread during Django startup."""
        def _load():
            try:
                instance = cls()
                instance.model  # triggers model load (thread-safe)
                instance.encode('warmup')  # pay first-inference init cost
                logger.info('Embedding model preloaded and ready.')
            except Exception as e:
                logger.warning(f'Failed to preload embedding model: {e}')

        threading.Thread(target=_load, daemon=True).start()

    @classmethod
    def wait_until_ready(cls, timeout=None):
        """Block until the model is loaded, with optional timeout."""
        return cls._ready_event.wait(timeout=timeout)

    @classmethod
    def is_loaded(cls):
        return cls._ready_event.is_set()
