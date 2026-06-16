import os
import threading
from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        # Preload embedding model in background on startup
        if os.environ.get('RUN_MAIN') != 'true' and os.environ.get('DJANGO_AUTORELOAD_ENV') != 'true':
            # Only preload once (skip reloader child process)
            try:
                from api.services.embedding import EmbeddingService
                EmbeddingService.preload()
            except Exception:
                pass
