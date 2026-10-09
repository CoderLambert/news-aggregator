#!/usr/bin/env python3
"""Start Django with Waitress when run as a script.

The configuration helpers are import-safe so tests can validate them without
initializing Django, reading credentials, or opening a listening socket.
"""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping


def build_waitress_config(environ=None, *, environment=None):
    """Build validated Waitress arguments without importing or starting it."""
    from newsaggregator.runtime_config import build_waitress_options

    values = os.environ if environ is None else environ
    return build_waitress_options(values, environment=environment)


def load_development_hermes_key(environ: MutableMapping[str, str] | None = None) -> bool:
    """Load the legacy Hermes key only for development, preserving local use."""
    values = os.environ if environ is None else environ
    if values.get("DJANGO_ENV", "development") == "production":
        return False
    if values.get("DASHSCOPE_CODING_API_KEY"):
        return False

    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.isfile(config_path):
        return False
    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file)
        if not isinstance(config, dict):
            return False
        model = config.get("model")
        api_key = model.get("api_key", "") if isinstance(model, dict) else ""
        if not isinstance(api_key, str) or not api_key:
            return False
        values["DASHSCOPE_CODING_API_KEY"] = api_key
        print("Loaded development API key from Hermes config", flush=True)
        return True
    except Exception:
        print("Warning: Could not load the development Hermes API key.", flush=True)
        return False


def main() -> None:
    backend_path = os.path.join(os.path.dirname(__file__), "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsaggregator.settings")

    from newsaggregator.runtime_config import resolve_django_environment

    environment = resolve_django_environment(os.environ)
    os.environ.setdefault("DJANGO_ENV", environment)
    if environment == "development":
        load_development_hermes_key(os.environ)

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
