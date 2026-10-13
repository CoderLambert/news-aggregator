import os
import sys
from importlib import import_module
from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def import_models(self):
        super().import_models()
        # Explicitly register the modular models before migrations and checks.
        import_module('api.smart_channel_models')

    def ready(self):
        is_test_process = ('pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ or 'test' in sys.argv)
        crawl_only_mode = os.environ.get('NEWS_CRAWL_ONLY') == '1'
        if (not is_test_process and not crawl_only_mode
                and os.environ.get('RUN_MAIN') != 'true'
                and os.environ.get('DJANGO_AUTORELOAD_ENV') != 'true'):
            try:
                from api.services.embedding import EmbeddingService
                EmbeddingService.preload()
            except Exception:
                pass
