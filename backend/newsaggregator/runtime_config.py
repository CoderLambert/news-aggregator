"""Side-effect-free parsing for deployment and Waitress configuration."""

from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass, field
from typing import Mapping

from django.core.exceptions import ImproperlyConfigured


PUBLIC_HOST = "news.lambert.host"
PUBLIC_CSRF_ORIGIN = "https://news.lambert.host"
DEVELOPMENT_CSRF_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:9527",
    "http://localhost:9527",
)
WAITRESS_TRUSTED_PROXY_HEADERS = frozenset(
    {"x-forwarded-proto", "x-forwarded-for"}
)


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    debug: bool
    secret_key: str = field(repr=False)
    allowed_hosts: tuple[str, ...]
    csrf_trusted_origins: tuple[str, ...]
    public_site_mode: str
    public_signup_enabled: bool
    public_ai_enabled: bool
    chatgpt_plan_usage_enabled: bool
    chatgpt_auth_mode: str
    waitress_trusted_proxy: str | None


def resolve_django_environment(environ: Mapping[str, str]) -> str:
    """Resolve the process-selected mode without consulting dotenv files."""
    value = environ.get("DJANGO_ENV", "development")
    if value not in {"development", "production"}:
        raise ImproperlyConfigured(
            "DJANGO_ENV must be exactly 'development' or 'production'."
        )
    return value


def _boolean(environ: Mapping[str, str], name: str, default: str) -> bool:
    value = environ.get(name, default)
    if value == "0":
        return False
    if value == "1":
        return True
    raise ImproperlyConfigured(f"{name} must be exactly '0' or '1'.")


def _comma_separated(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _strict_comma_separated(value: str) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in value.split(","))
    if any(not part for part in parts):
        return ()
    return parts


def _enum(
    environ: Mapping[str, str], name: str, default: str, choices: set[str]
) -> str:
    value = environ.get(name, default)
    if value not in choices:
        expected = ", ".join(sorted(choices))
        raise ImproperlyConfigured(f"{name} must be one of: {expected}.")
    return value


def _production_secret(environ: Mapping[str, str]) -> str:
    value = environ.get("DJANGO_SECRET_KEY", "")
    if not value:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be explicitly configured in production."
        )
    if (
        len(value) < 50
        or len(set(value)) < 5
        or value.startswith(("dev-only-", "django-insecure-"))
        or "change-me" in value.lower()
        or "replace-me" in value.lower()
    ):
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be at least 50 characters, use at least five distinct characters, and not use a development prefix."
        )
    return value


def _production_proxy(environ: Mapping[str, str]) -> str:
    value = environ.get("WAITRESS_TRUSTED_PROXY", "")
    if not value:
        raise ImproperlyConfigured(
            "WAITRESS_TRUSTED_PROXY must be one trusted proxy IP in production."
        )
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ImproperlyConfigured(
            "WAITRESS_TRUSTED_PROXY must be one valid IP address, not a network, list, wildcard, or hostname."
        ) from None


def parse_runtime_config(
    environ: Mapping[str, str], *, environment: str | None = None
) -> RuntimeConfig:
    """Validate runtime values without loading files or changing process state."""
    mode = environment if environment is not None else resolve_django_environment(environ)
    if mode not in {"development", "production"}:
        raise ImproperlyConfigured(
            "DJANGO_ENV must be exactly 'development' or 'production'."
        )
    production = mode == "production"

    debug = _boolean(environ, "DJANGO_DEBUG", "0" if production else "1")
    if production and debug:
        raise ImproperlyConfigured("DJANGO_DEBUG=1 is forbidden in production.")

    if production:
        secret_key = _production_secret(environ)
    else:
        secret_key = environ.get("DJANGO_SECRET_KEY") or (
            "dev-only-" + secrets.token_urlsafe(48)
        )

    if production:
        allowed_hosts = (
            _strict_comma_separated(environ["DJANGO_ALLOWED_HOSTS"])
            if "DJANGO_ALLOWED_HOSTS" in environ
            else (PUBLIC_HOST,)
        )
        if allowed_hosts != (PUBLIC_HOST,):
            raise ImproperlyConfigured(
                "DJANGO_ALLOWED_HOSTS in production must contain only news.lambert.host."
            )

        csrf_origins = (
            _strict_comma_separated(environ["DJANGO_CSRF_TRUSTED_ORIGINS"])
            if "DJANGO_CSRF_TRUSTED_ORIGINS" in environ
            else (PUBLIC_CSRF_ORIGIN,)
        )
        if csrf_origins != (PUBLIC_CSRF_ORIGIN,):
            raise ImproperlyConfigured(
                "DJANGO_CSRF_TRUSTED_ORIGINS in production must contain only https://news.lambert.host."
            )
    else:
        allowed_hosts = _comma_separated(environ.get("DJANGO_ALLOWED_HOSTS", "*"))
        csrf_origins = _comma_separated(
            environ.get(
                "DJANGO_CSRF_TRUSTED_ORIGINS", ",".join(DEVELOPMENT_CSRF_ORIGINS)
            )
        )

    public_site_mode = _enum(
        environ,
        "PUBLIC_SITE_MODE",
        "read_only" if production else "full",
        {"read_only", "full"},
    )
    public_signup_enabled = _boolean(
        environ, "PUBLIC_SIGNUP_ENABLED", "0" if production else "1"
    )
    public_ai_enabled = _boolean(environ, "PUBLIC_AI_ENABLED", "0" if production else "1")
    chatgpt_plan_usage_enabled = _boolean(
        environ, "CHATGPT_PLAN_USAGE_ENABLED", "0" if production else "1"
    )
    chatgpt_auth_mode = _enum(
        environ,
        "CHATGPT_AUTH_MODE",
        "disabled" if production else "local_oss",
        {"disabled", "local_oss", "website"},
    )
    if production and chatgpt_auth_mode == "local_oss":
        raise ImproperlyConfigured(
            "CHATGPT_AUTH_MODE=local_oss is forbidden in production."
        )

    trusted_proxy = _production_proxy(environ) if production else None

    return RuntimeConfig(
        environment=mode,
        debug=debug,
        secret_key=secret_key,
        allowed_hosts=allowed_hosts,
        csrf_trusted_origins=csrf_origins,
        public_site_mode=public_site_mode,
        public_signup_enabled=public_signup_enabled,
        public_ai_enabled=public_ai_enabled,
        chatgpt_plan_usage_enabled=chatgpt_plan_usage_enabled,
        chatgpt_auth_mode=chatgpt_auth_mode,
        waitress_trusted_proxy=trusted_proxy,
    )


def _positive_integer(
    environ: Mapping[str, str], name: str, default: str, *, maximum: int | None = None
) -> int:
    value = environ.get(name, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from None
    if parsed <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    if maximum is not None and parsed > maximum:
        raise ImproperlyConfigured(f"{name} must be between 1 and {maximum}.")
    return parsed


def build_waitress_options(
    environ: Mapping[str, str], *, environment: str | None = None
) -> dict[str, object]:
    """Return validated Waitress options; this function never starts a server."""
    config = parse_runtime_config(environ, environment=environment)
    termux_mode = environ.get("TERMUX_MODE", "0") == "1"
    threads = _positive_integer(
        environ, "WAITRESS_THREADS", "2" if termux_mode else "4"
    )
    connection_limit = _positive_integer(
        environ, "WAITRESS_CONN_LIMIT", "256" if termux_mode else "1000"
    )
    port = _positive_integer(environ, "WAITRESS_PORT", "9527", maximum=65535)
    trusted = config.waitress_trusted_proxy is not None
    return {
        "host": "127.0.0.1" if config.environment == "production" else "0.0.0.0",
        "port": port,
        "threads": threads,
        "connection_limit": connection_limit,
        "channel_timeout": 300,
        "trusted_proxy": config.waitress_trusted_proxy,
        "trusted_proxy_count": 1 if trusted else None,
        "trusted_proxy_headers": (
            set(WAITRESS_TRUSTED_PROXY_HEADERS) if trusted else set()
        ),
        "clear_untrusted_proxy_headers": True,
    }
