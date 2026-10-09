"""Production configuration is validated in isolated Python processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
PYTHONPATH = os.pathsep.join(
    [os.path.join(REPO_ROOT, "backend"), os.path.join(REPO_ROOT, "crawler")]
)
SECRET_SENTINEL = "NO_REAL_CREDENTIALS_TEST_SECRET_SENTINEL-0123456789ABC"
VALID_SECRET = SECRET_SENTINEL


def _base_env(tmp_path, **overrides):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": PYTHONPATH,
        "HOME": str(tmp_path),
        "PYTHONNOUSERSITE": "1",
        "DJANGO_ENV": "production",
        "DJANGO_DEBUG": "0",
        "DJANGO_SECRET_KEY": VALID_SECRET,
        "WAITRESS_TRUSTED_PROXY": "127.0.0.1",
        "RUN_MAIN": "true",
    }
    env.update(overrides)
    return env


def _import_settings(tmp_path, overrides=None, prelude=""):
    script = prelude + "\nimport json\nimport newsaggregator.settings as s\n" + "print(json.dumps({\n" \
        "'environment': s.DJANGO_ENV, 'debug': s.DEBUG, 'allowed_hosts': s.ALLOWED_HOSTS,\n" \
        "'csrf_origins': s.CSRF_TRUSTED_ORIGINS, 'site_mode': s.PUBLIC_SITE_MODE,\n" \
        "'signup': s.PUBLIC_SIGNUP_ENABLED, 'ai': s.PUBLIC_AI_ENABLED,\n" \
        "'plan': s.CHATGPT_PLAN_USAGE_ENABLED, 'auth_mode': s.CHATGPT_AUTH_MODE,\n" \
        "'trusted_proxy': s.WAITRESS_TRUSTED_PROXY,\n" \
        "'cors_all': s.CORS_ALLOW_ALL_ORIGINS, 'cors_credentials': s.CORS_ALLOW_CREDENTIALS,\n" \
        "'session_secure': s.SESSION_COOKIE_SECURE, 'session_domain': s.SESSION_COOKIE_DOMAIN,\n" \
        "'session_httponly': s.SESSION_COOKIE_HTTPONLY, 'csrf_secure': s.CSRF_COOKIE_SECURE,\n" \
        "'csrf_domain': s.CSRF_COOKIE_DOMAIN, 'csrf_httponly': s.CSRF_COOKIE_HTTPONLY,\n" \
        "'session_samesite': s.SESSION_COOKIE_SAMESITE, 'csrf_samesite': s.CSRF_COOKIE_SAMESITE,\n" \
        "'ssl_redirect': s.SECURE_SSL_REDIRECT, 'redirect_exempt': s.SECURE_REDIRECT_EXEMPT,\n" \
        "'proxy_ssl_header': s.SECURE_PROXY_SSL_HEADER, 'hsts': s.SECURE_HSTS_SECONDS,\n" \
        "'hsts_subdomains': s.SECURE_HSTS_INCLUDE_SUBDOMAINS, 'hsts_preload': s.SECURE_HSTS_PRELOAD\n" \
        "}))\n"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=_base_env(tmp_path, **(overrides or {})),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_invalid(tmp_path, name, value):
    env = _base_env(tmp_path)
    if value is None:
        env.pop(name, None)
    else:
        env[name] = value
    return subprocess.run(
        [sys.executable, "-c", "import newsaggregator.settings"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_production_defaults_fail_closed_and_set_browser_security(tmp_path):
    result = _import_settings(tmp_path)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["environment"] == "production"
    assert config["debug"] is False
    assert config["allowed_hosts"] == ["news.lambert.host"]
    assert config["csrf_origins"] == ["https://news.lambert.host"]
    assert config["site_mode"] == "read_only"
    assert config["signup"] is config["ai"] is config["plan"] is False
    assert config["auth_mode"] == "disabled"
    assert config["trusted_proxy"] == "127.0.0.1"
    assert config["cors_all"] is config["cors_credentials"] is False
    assert config["session_secure"] is config["csrf_secure"] is True
    assert config["session_domain"] is config["csrf_domain"] is None
    assert config["session_httponly"] is True
    assert config["csrf_httponly"] is False
    assert config["session_samesite"] == config["csrf_samesite"] == "Lax"
    assert config["ssl_redirect"] is True
    assert config["redirect_exempt"] == [r"^api/health/(live|ready)/$"]
    assert config["proxy_ssl_header"] is None
    assert config["hsts"] == 3600
    assert config["hsts_subdomains"] is config["hsts_preload"] is False


def test_production_accepts_only_explicit_fixed_origin_and_website_skeleton(tmp_path):
    result = _import_settings(
        tmp_path,
        overrides={
            "DJANGO_ALLOWED_HOSTS": "news.lambert.host",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://news.lambert.host",
            "CHATGPT_AUTH_MODE": "website",
        },
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["allowed_hosts"] == ["news.lambert.host"]
    assert config["csrf_origins"] == ["https://news.lambert.host"]
    assert config["auth_mode"] == "website"


def test_production_does_not_import_or_call_dotenv(tmp_path):
    prelude = """
import sys, types
dotenv = types.ModuleType('dotenv')
def fail_if_loaded(*args, **kwargs):
    raise AssertionError('production loaded dotenv')
dotenv.load_dotenv = fail_if_loaded
sys.modules['dotenv'] = dotenv
"""
    result = _import_settings(tmp_path, prelude=prelude)
    assert result.returncode == 0, result.stderr
    # The probe script emits only settings data, never secret material.
    assert SECRET_SENTINEL not in result.stdout + result.stderr


def test_development_defaults_remain_compatible(tmp_path):
    env = _base_env(tmp_path)
    env.pop("DJANGO_SECRET_KEY", None)
    env.pop("WAITRESS_TRUSTED_PROXY", None)
    env.pop("DJANGO_DEBUG", None)
    env["DJANGO_ENV"] = "development"
    script = """import sys, types
dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules['dotenv'] = dotenv
import json, newsaggregator.settings as s
print(json.dumps({'debug': s.DEBUG, 'hosts': s.ALLOWED_HOSTS,
'csrf': s.CSRF_TRUSTED_ORIGINS, 'site': s.PUBLIC_SITE_MODE,
'flags': [s.PUBLIC_SIGNUP_ENABLED, s.PUBLIC_AI_ENABLED, s.CHATGPT_PLAN_USAGE_ENABLED],
'auth': s.CHATGPT_AUTH_MODE, 'proxy': s.WAITRESS_TRUSTED_PROXY,
'cors': [s.CORS_ALLOW_ALL_ORIGINS, s.CORS_ALLOW_CREDENTIALS]}))"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, env=env,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config == {
        "debug": True,
        "hosts": ["*"],
        "csrf": [
            "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
            "http://127.0.0.1:5173", "http://127.0.0.1:9527", "http://localhost:9527",
        ],
        "site": "full",
        "flags": [True, True, True],
        "auth": "local_oss",
        "proxy": None,
        "cors": [True, True],
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DJANGO_SECRET_KEY", None),
        ("DJANGO_SECRET_KEY", "short"),
        ("DJANGO_SECRET_KEY", "dev-only-" + "x" * 60),
        ("DJANGO_SECRET_KEY", "django-insecure-" + "x" * 60),
        ("DJANGO_SECRET_KEY", "Safe-Long-" + "change-me-" + "A1b2C3d4" * 8),
        ("DJANGO_SECRET_KEY", "Safe-Long-" + "replace-me-" + "A1b2C3d4" * 8),
        ("DJANGO_SECRET_KEY", "x" * 60),
        ("DJANGO_DEBUG", "1"),
        ("DJANGO_DEBUG", "true"),
        ("PUBLIC_SIGNUP_ENABLED", "true"),
        ("PUBLIC_AI_ENABLED", "false"),
        ("CHATGPT_PLAN_USAGE_ENABLED", "yes"),
        ("DJANGO_ALLOWED_HOSTS", ""),
        ("DJANGO_ALLOWED_HOSTS", "*"),
        ("DJANGO_ALLOWED_HOSTS", "news.lambert.host,example.com"),
        ("DJANGO_ALLOWED_HOSTS", "news.lambert.host,"),
        ("DJANGO_CSRF_TRUSTED_ORIGINS", "http://news.lambert.host"),
        ("DJANGO_CSRF_TRUSTED_ORIGINS", "https://news.lambert.host,https://other.test"),
        ("WAITRESS_TRUSTED_PROXY", None),
        ("WAITRESS_TRUSTED_PROXY", "*"),
        ("WAITRESS_TRUSTED_PROXY", "127.0.0.0/24"),
        ("WAITRESS_TRUSTED_PROXY", "127.0.0.1,127.0.0.2"),
        ("WAITRESS_TRUSTED_PROXY", "nginx.internal"),
        ("PUBLIC_SITE_MODE", "unexpected"),
        ("CHATGPT_AUTH_MODE", "unexpected"),
        ("CHATGPT_AUTH_MODE", "local_oss"),
    ],
)
def test_invalid_production_values_fail_without_echoing_secret(tmp_path, name, value):
    result = _run_invalid(tmp_path, name, value)
    assert result.returncode != 0
    assert SECRET_SENTINEL not in result.stdout + result.stderr
    assert VALID_SECRET not in result.stdout + result.stderr


def test_invalid_environment_name_fails_closed(tmp_path):
    result = _run_invalid(tmp_path, "DJANGO_ENV", "staging")
    assert result.returncode != 0

