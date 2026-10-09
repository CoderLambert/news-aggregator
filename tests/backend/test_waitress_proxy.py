from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest
from django.core.exceptions import DisallowedHost, ImproperlyConfigured
from django.core.handlers.wsgi import WSGIRequest
from django.test import override_settings
from waitress.proxy_headers import proxy_headers_middleware

import start_waitress


TEST_SECRET = "WAITRESS_PROXY_TEST_ONLY_0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _production_env(**overrides):
    env = {
        "DJANGO_ENV": "production",
        "DJANGO_DEBUG": "0",
        "DJANGO_SECRET_KEY": TEST_SECRET,
        "WAITRESS_TRUSTED_PROXY": "127.0.0.1",
    }
    env.update(overrides)
    return env


def _environ(remote_addr, host="news.lambert.host", **headers):
    environ = {
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "",
        "PATH_INFO": "/api/health/live/",
        "QUERY_STRING": "",
        "SERVER_NAME": "news.lambert.host",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": remote_addr,
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": "0",
        "HTTP_HOST": host,
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    environ.update(headers)
    return environ


def _request_result(environ, start_response):
    request = WSGIRequest(environ)
    payload = {
        "secure": request.is_secure(),
        "remote_addr": request.META.get("REMOTE_ADDR"),
        "host": request.get_host(),
    }
    start_response("200 OK", [("Content-Type", "application/json")])
    return [json.dumps(payload).encode("utf-8")]


def _proxy_app(options):
    return proxy_headers_middleware(
        _request_result,
        trusted_proxy=options["trusted_proxy"],
        trusted_proxy_count=options["trusted_proxy_count"],
        trusted_proxy_headers=options["trusted_proxy_headers"],
        clear_untrusted=options["clear_untrusted_proxy_headers"],
    )


def _call(app, environ):
    statuses = []
    body = b"".join(app(environ, lambda status, _headers: statuses.append(status)))
    return statuses[0], json.loads(body)


def test_production_waitress_binds_loopback_with_explicit_proxy_and_defaults():
    options = start_waitress.build_waitress_config(_production_env())
    assert options == {
        "host": "127.0.0.1",
        "port": 9527,
        "threads": 4,
        "connection_limit": 1000,
        "channel_timeout": 300,
        "trusted_proxy": "127.0.0.1",
        "trusted_proxy_count": 1,
        "trusted_proxy_headers": {"x-forwarded-proto", "x-forwarded-for"},
        "clear_untrusted_proxy_headers": True,
    }


def test_development_waitress_does_not_trust_forwarded_headers():
    options = start_waitress.build_waitress_config(
        {"DJANGO_ENV": "development"}, environment="development"
    )
    assert options["host"] == "0.0.0.0"
    assert options["port"] == 9527
    assert options["trusted_proxy"] is None
    assert options["trusted_proxy_count"] is None
    assert options["trusted_proxy_headers"] == set()
    assert options["clear_untrusted_proxy_headers"] is True


def test_waitress_port_and_worker_counts_are_validated():
    assert start_waitress.build_waitress_config(
        _production_env(WAITRESS_PORT="19527", WAITRESS_THREADS="2", WAITRESS_CONN_LIMIT="50")
    )["port"] == 19527
    for name, value in (
        ("WAITRESS_PORT", "0"),
        ("WAITRESS_PORT", "65536"),
        ("WAITRESS_PORT", "invalid"),
        ("WAITRESS_THREADS", "0"),
        ("WAITRESS_THREADS", "-2"),
        ("WAITRESS_CONN_LIMIT", "invalid"),
    ):
        with pytest.raises(ImproperlyConfigured):
            start_waitress.build_waitress_config(_production_env(**{name: value}))


def test_waitress_trusts_forwarded_scheme_only_from_configured_proxy():
    options = start_waitress.build_waitress_config(_production_env())
    middleware = _proxy_app(options)

    with override_settings(ALLOWED_HOSTS=["news.lambert.host"]):
        trusted_environ = _environ(
            "127.0.0.1",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_FORWARDED_FOR="198.51.100.42",
        )
        status, result = _call(middleware, trusted_environ)
        assert status == "200 OK"
        assert result == {
            "secure": True,
            "remote_addr": "198.51.100.42",
            "host": "news.lambert.host",
        }

        untrusted_environ = _environ(
            "203.0.113.1",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_FORWARDED_FOR="198.51.100.42",
        )
        status, result = _call(middleware, untrusted_environ)
        assert status == "200 OK"
        assert result == {
            "secure": False,
            "remote_addr": "203.0.113.1",
            "host": "news.lambert.host",
        }
        assert "HTTP_X_FORWARDED_PROTO" not in untrusted_environ
        assert "HTTP_X_FORWARDED_FOR" not in untrusted_environ


def test_wsgi_request_rejects_unlisted_host():
    options = start_waitress.build_waitress_config(_production_env())
    middleware = _proxy_app(options)
    with override_settings(ALLOWED_HOSTS=["news.lambert.host"]):
        _call(middleware, _environ("127.0.0.1", host="news.lambert.host"))
        with pytest.raises(DisallowedHost):
            _call(middleware, _environ("127.0.0.1", host="attacker.invalid"))


def test_production_hermes_fallback_is_skipped_and_import_is_inert(monkeypatch):
    calls = []

    def unexpected_hermes_stat(path):
        calls.append(path)
        raise AssertionError("production tried to inspect Hermes config")

    monkeypatch.setattr(start_waitress.os.path, "isfile", unexpected_hermes_stat)
    production_env = {"DJANGO_ENV": "production"}
    assert start_waitress.load_development_hermes_key(production_env) is False
    assert calls == []
    assert "DASHSCOPE_CODING_API_KEY" not in production_env

    script = """import sys, types
calls = []
waitress = types.ModuleType('waitress')
waitress.serve = lambda *args, **kwargs: calls.append((args, kwargs))
sys.modules['waitress'] = waitress
import start_waitress
assert calls == []
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")),
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_development_waitress_defaults_remain_compatible():
    options = start_waitress.build_waitress_config(
        {"DJANGO_ENV": "development", "TERMUX_MODE": "1"},
        environment="development",
    )
    assert options["threads"] == 2
    assert options["connection_limit"] == 256
    assert options["host"] == "0.0.0.0"
