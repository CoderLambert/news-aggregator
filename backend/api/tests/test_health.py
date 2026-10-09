from __future__ import annotations

from unittest.mock import Mock

import pytest
from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.contrib.sessions.middleware import SessionMiddleware
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_ready_probe_executes_select_one_against_test_database(client):
    response = client.get(reverse("health-ready"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_probe_does_not_access_database(client, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("live probe accessed the database")

    monkeypatch.setattr(connection, "cursor", fail_if_called)
    response = client.get(reverse("health-live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_probe_hides_database_failure_details(client, monkeypatch):
    monkeypatch.setattr(
        connection,
        "cursor",
        Mock(side_effect=RuntimeError("private database connection detail")),
    )
    response = client.get(reverse("health-ready"))
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert b"private database connection detail" not in response.content


@pytest.mark.django_db
def test_health_routes_support_only_get_and_head(client):
    live = client.head(reverse("health-live"))
    ready = client.head(reverse("health-ready"))
    assert live.status_code == ready.status_code == 200
    assert client.post(reverse("health-live")).status_code == 405
    assert client.post(reverse("health-ready")).status_code == 405


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_REDIRECT_EXEMPT=[r"^api/health/(live|ready)/$"],
    ALLOWED_HOSTS=["news.lambert.host"],
)
@pytest.mark.django_db
def test_only_exact_health_paths_skip_https_redirect_and_host_is_checked():
    client = Client(raise_request_exception=False)
    host = {"HTTP_HOST": "news.lambert.host"}

    assert client.get("/api/health/live/?next=/api/news/", **host).status_code == 200
    assert client.get("/api/health/ready/?next=/api/news/", **host).status_code == 200
    ordinary = client.get("/api/news/?next=/api/health/live/", **host)
    assert ordinary.status_code == 301
    assert ordinary["Location"].startswith("https://news.lambert.host/api/news/")

    invalid_host = client.get(
        "/api/news/", HTTP_HOST="attacker.invalid"
    )
    assert invalid_host.status_code == 400


@override_settings(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_DOMAIN=None,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    CSRF_COOKIE_SECURE=True,
    CSRF_COOKIE_DOMAIN=None,
    CSRF_COOKIE_HTTPONLY=False,
    CSRF_COOKIE_SAMESITE="Lax",
)
@pytest.mark.django_db
def test_session_and_csrf_cookies_are_secure_host_only_and_csrf_is_readable(client):
    request = RequestFactory().get("/")
    middleware = SessionMiddleware(lambda _request: HttpResponse())
    middleware.process_request(request)
    request.session["probe"] = True
    session_response = middleware.process_response(request, HttpResponse())

    session_cookie = session_response.cookies[settings.SESSION_COOKIE_NAME]
    assert session_cookie["secure"] is True
    assert session_cookie["httponly"] is True
    assert session_cookie["domain"] == ""
    assert session_cookie["samesite"] == "Lax"

    csrf_response = APIClient().get(reverse("auth-csrf"))
    csrf_cookie = csrf_response.cookies[settings.CSRF_COOKIE_NAME]
    assert csrf_cookie["secure"] is True
    assert not csrf_cookie["httponly"]
    assert csrf_cookie["domain"] == ""
    assert csrf_cookie["samesite"] == "Lax"
