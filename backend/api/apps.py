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

        # Auto-start the full-content fetch daemon (dev only, skip autoreloader child)
        # Set AUTO_FETCH_FULL_CONTENT=0 in .env to disable
        if (
            os.environ.get('AUTO_FETCH_FULL_CONTENT', '1') == '1'
            and os.environ.get('DJANGO_AUTORELOAD_ENV') != 'true'
        ):
            try:
                from api.management.commands.auto_fetch_full_content import run_loop
                daemon = threading.Thread(target=run_loop, name='auto-fetch-full-content', daemon=True)
                daemon.start()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('[auto-fetch] failed to start daemon: %s', exc)
