"""Opt-in source-development profile. Always use `news-server dev` to enter."""
import os
from pathlib import Path

from .dev_runtime import environment, install_io_guard, port

# Validate ownership before importing normal settings or touching the database.
_directory = Path(os.environ['NEWSHUB_DEV_RUNTIME'])
_api_port = port(os.environ['NEWSHUB_DEV_BACKEND_PORT'])
_env = environment(_directory, _api_port, os.environ['NEWSHUB_DEV_FRONTEND_PORT'])
# Only Django's internally set reload-child flag survives. The launcher never sets it.
if os.environ.get('RUN_MAIN') == 'true':
    _env['RUN_MAIN'] = 'true'
os.environ.clear()
os.environ.update(_env)
install_io_guard(_api_port)

from .settings import *  # noqa: E402,F403

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS  # noqa: F405
CORS_ALLOW_CREDENTIALS = True
STATICFILES_DIRS = []  # Vite serves source assets; no bundle build is required.
MEDIA_ROOT = _directory / 'media'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': str(_directory)}}
# The SPA reads csrftoken by its standard name; a separate browser profile is
# still required because cookies are host-, not port-scoped.
SESSION_COOKIE_NAME = 'newshub_dev_' + _env['CHATGPT_DEPLOYMENT_INSTANCE_ID'].replace('-', '')
