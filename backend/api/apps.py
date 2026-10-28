import os
import sys
from importlib import import_module
from django.apps import AppConfig
from api.services.semantic_search import semantic_search_enabled


class ApiConfig(AppConfig):
    name = 'api'

    def import_models(self):
        super().import_models()
        # Explicitly register the modular models before migrations and checks.
        import_module('api.smart_channel_models')
        import_module('api.ai_connection_models')
        import_module('api.ai_model_models')
        import_module('api.ai_preference_models')

    def ready(self):
        # rss-sync uses ORM and stored HTML only; never preload model services.
        if os.environ.get('NEWSHUB_RUNTIME_ROLE') == 'rss_sync':
            return
        is_test_process = ('pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ or 'test' in sys.argv)
        is_lightweight_health = sys.argv[1:2] == ['runtime_health']
        crawl_only_mode = os.environ.get('NEWS_CRAWL_ONLY') == '1'
        if (semantic_search_enabled() and not is_test_process and not crawl_only_mode and not is_lightweight_health
                and os.environ.get('RUN_MAIN') != 'true'
                and os.environ.get('DJANGO_AUTORELOAD_ENV') != 'true'):
            try:
                from api.services.embedding import EmbeddingService
                EmbeddingService.preload()
            except Exception:
                pass
