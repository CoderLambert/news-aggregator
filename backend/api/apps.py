import os
import threading
import sys
from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        # Avoid model downloads during pytest/Django tests and their child processes.
        is_test_process = (
            'pytest' in sys.modules
            or 'PYTEST_CURRENT_TEST' in os.environ
            or 'test' in sys.argv
        )
        # Preload embedding model in background on application startup.
        crawl_only_mode = os.environ.get('NEWS_CRAWL_ONLY') == '1'
        if (
            not is_test_process
            and not crawl_only_mode
            and os.environ.get('RUN_MAIN') != 'true'
            and os.environ.get('DJANGO_AUTORELOAD_ENV') != 'true'
        ):
            # Only preload once (skip reloader child process)
            try:
                from api.services.embedding import EmbeddingService
                EmbeddingService.preload()
            except Exception:
                pass
