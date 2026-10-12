#!/usr/bin/env python3
"""Start Django with Waitress when run as a script.

The configuration helpers are import-safe so tests can validate them without
initializing Django, reading credentials, or opening a listening socket.
"""

from __future__ import annotations

import os
import sys


def build_waitress_config(environ=None, *, environment=None):
    """Build validated Waitress arguments without importing or starting it."""
    from newsaggregator.runtime_config import build_waitress_options

    values = os.environ if environ is None else environ
    return build_waitress_options(values, environment=environment)


def main() -> None:
    backend_path = os.path.join(os.path.dirname(__file__), "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsaggregator.settings")

    from newsaggregator.runtime_config import resolve_django_environment

    environment = resolve_django_environment(os.environ)
    os.environ.setdefault("DJANGO_ENV", environment)
    import django

    django.setup()

    from django.conf import settings
    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    application = get_wsgi_application()
    config = build_waitress_config(os.environ, environment=settings.DJANGO_ENV)
    mode = "Termux" if os.environ.get("TERMUX_MODE", "0") == "1" else "Server"
    print(
        f"Starting Waitress on {config['host']}:{config['port']} "
        f"({mode} mode, threads={config['threads']}, "
        f"connections={config['connection_limit']})...",
        flush=True,
    )
    serve(application, **config)


if __name__ == "__main__":
    main()
