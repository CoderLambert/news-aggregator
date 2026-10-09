from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from api import urls as api_urls
from api.models import (
    Category,
    ChatSession,
    News,
    ProviderComparison,
    ResearchSearchResult,
    ResearchSession,
    Source,
)
from api.public_policy import PublicPolicyMiddleware
from api.views import NewsListView


ALL_HTTP_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
READ_ONLY_ROUTE_NAMES = {
    "news-list",
    "news-detail",
    "category-list",
    "source-list",
    "auth-csrf",
    "capabilities",
    "health-live",
    "health-ready",
}
FEATURE_NAMES = {
    "news",
    "keyword_search",
    "semantic_search",
    "accounts",
    "signup",
    "favorites",
    "blocked_news",
    "chat_history",
    "fetch_full",
    "translation",
    "chat",
    "suggested_questions",
    "tts",
    "research",
    "provider_comparisons",
    "admin",
    "chatgpt_subscription",
}
TEST_UUID = uuid.UUID("00000000-0000-0000-0000-000000000123")


@pytest.fixture
def news_obj(db):
    category = Category.objects.create(name="Policy test", slug="policy-test")
    source = Source.objects.create(
        name="Policy test source", url="https://source.example.test/news"
    )
    return News.objects.create(
        title="PolicyKeyword marker article",
        content="A local keyword-search fixture.",
        publish_time=timezone.now(),
        source=source,
        category=category,
        url="https://article.example.test/policy-keyword-marker",
    )


def _route_pattern(name):
    return next(pattern for pattern in api_urls.urlpatterns if pattern.name == name)


def _route_path(pattern, *, news_id=None):
    kwargs = {}
    for name, converter in pattern.pattern.converters.items():
        converter_name = converter.__class__.__name__
        if converter_name == "IntConverter":
            kwargs[name] = news_id if name == "pk" and news_id is not None else 1
        elif converter_name == "UUIDConverter":
            kwargs[name] = TEST_UUID
        else:
            kwargs[name] = "policy-probe"
    return reverse(pattern.name, kwargs=kwargs)


def _assert_policy_response(response, code="public_read_only", status=403):
    assert response.status_code == status
    assert response["Cache-Control"] == "no-store"
    if response.wsgi_request.method == "HEAD":
        assert response.content == b""
    else:
        assert response.json()["error_code"] == code
        assert isinstance(response.json()["error"], str)


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="read_only",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_every_resolved_api_route_and_method_obeys_read_only_matrix(
    news_obj, monkeypatch
):
    client = APIClient()
    assert all(pattern.name for pattern in api_urls.urlpatterns)

    for pattern in api_urls.urlpatterns:
        route_name = pattern.name
        path = _route_path(
            pattern,
            news_id=news_obj.pk if route_name == "news-detail" else None,
        )
        for method in ALL_HTTP_METHODS:
            allowed = route_name in READ_ONLY_ROUTE_NAMES and method in {"GET", "HEAD"}
            if allowed:
                response = client.generic(method, path)
                assert response.status_code in {200, 405}, (
                    route_name,
                    method,
                    response.status_code,
                    getattr(response, "content", b"")[:300],
                )
                if route_name == "news-detail":
                    assert response.status_code == 200
            else:
                view_spy = Mock()
                with monkeypatch.context() as scoped:
                    scoped.setattr(pattern, "callback", view_spy)
                    response = client.generic(method, path)
                _assert_policy_response(response)
                view_spy.assert_not_called()

    unknown = client.get("/api/route-that-does-not-exist/")
    assert unknown.status_code == 404


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="read_only",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_read_only_cors_preflight_cannot_bypass_route_policy(news_obj, monkeypatch):
    client = APIClient()
    preflight_headers = {
        "HTTP_ORIGIN": "https://client.example.test",
        "HTTP_ACCESS_CONTROL_REQUEST_METHOD": "POST",
    }
    known_routes = (
        ("health-live", {}),
        ("news-list", {}),
        ("news-chat", {"pk": news_obj.pk}),
        ("chatgpt-subscription-handoff", {}),
        ("crawler-admin-dashboard", {}),
    )

    with (
        patch("api.views.get_openai_client") as openai_client,
        patch("api.views.stream_chat") as stream_chat,
        patch("api.services.article_fetcher.comparison.compare_providers") as compare,
        patch("api.services.chatgpt_subscription.handoff_authorization") as handoff_auth,
    ):
        for route_name, kwargs in known_routes:
            pattern = _route_pattern(route_name)
            path = _route_path(pattern, news_id=kwargs.get("pk"))
            view_spy = Mock()
            with monkeypatch.context() as scoped:
                scoped.setattr(pattern, "callback", view_spy)
                known = client.options(
                    path, **preflight_headers
                )
            _assert_policy_response(known)
            view_spy.assert_not_called()

        unknown = client.options(
            "/api/route-that-does-not-exist/", **preflight_headers
        )
        assert unknown.status_code == 404

        openai_client.assert_not_called()
        stream_chat.assert_not_called()
        compare.assert_not_called()
        handoff_auth.assert_not_called()


@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=False,
    PUBLIC_AI_ENABLED=False,
    CHATGPT_AUTH_MODE="disabled",
    CORS_ALLOW_ALL_ORIGINS=True,
)
def test_full_mode_cors_preflight_behavior_is_unchanged():
    origin = "https://client.example.test"
    client = APIClient()
    for route_name, kwargs in (
        ("news-list", {}),
        ("news-chat", {"pk": 1}),
        ("auth-register", {}),
        ("chatgpt-subscription-handoff", {}),
    ):
        response = client.options(
            reverse(route_name, kwargs=kwargs or None),
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        assert response.status_code == 200
        assert response["Access-Control-Allow-Origin"] == origin
        assert "POST" in response["Access-Control-Allow-Methods"]


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="read_only",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_keyword_search_uses_database_and_semantic_modes_fail_before_embedding(news_obj):
    client = APIClient()
    with (
        patch.object(NewsListView, "_semantic_search") as semantic_search,
        patch.object(NewsListView, "_hybrid_search") as hybrid_search,
        patch("api.services.embedding.EmbeddingService.encode") as encode,
    ):
        keyword = client.get(
            reverse("news-list"), {"search": "PolicyKeyword", "mode": "keyword"}
        )
        assert keyword.status_code == 200
        assert [item["id"] for item in keyword.json()["results"]] == [news_obj.pk]

        for query in (
            {"search": "PolicyKeyword", "mode": "semantic"},
            {"search": "PolicyKeyword", "mode": "hybrid"},
            {"mode": "semantic"},
            {"search": "PolicyKeyword", "mode": ""},
        ):
            response = client.get(reverse("news-list"), query)
            _assert_policy_response(response, "semantic_search_disabled")

        semantic_search.assert_not_called()
        hybrid_search.assert_not_called()
        encode.assert_not_called()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_full_mode_allows_semantic_and_hybrid_search_when_ai_enabled():
    client = APIClient()
    with (
        patch.object(
            NewsListView,
            "_semantic_search",
            return_value=Response({"count": 0, "next": None, "previous": None, "results": []}),
        ) as semantic_search,
        patch.object(
            NewsListView,
            "_hybrid_search",
            return_value=Response({"count": 0, "next": None, "previous": None, "results": []}),
        ) as hybrid_search,
    ):
        semantic = client.get(
            reverse("news-list"), {"search": "semantic probe", "mode": "semantic"}
        )
        hybrid = client.get(
            reverse("news-list"), {"search": "hybrid probe", "mode": "hybrid"}
        )

    assert semantic.status_code == 200
    assert semantic.json()["search_mode_applied"] == "semantic"
    assert hybrid.status_code == 200
    assert hybrid.json()["search_mode_applied"] == "hybrid"
    semantic_search.assert_called_once()
    hybrid_search.assert_called_once()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=False,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_full_mode_blocks_semantic_and_hybrid_search_when_ai_disabled(news_obj):
    client = APIClient()
    with (
        patch.object(NewsListView, "_semantic_search") as semantic_search,
        patch.object(NewsListView, "_hybrid_search") as hybrid_search,
        patch("api.services.embedding.EmbeddingService.encode") as encode,
    ):
        keyword = client.get(reverse("news-list"), {"search": "PolicyKeyword"})
        assert keyword.status_code == 200
        assert [item["id"] for item in keyword.json()["results"]] == [news_obj.pk]

        for mode in ("semantic", "hybrid"):
            response = client.get(
                reverse("news-list"), {"search": "PolicyKeyword", "mode": mode}
            )
            _assert_policy_response(response, "semantic_search_disabled")

        semantic_search.assert_not_called()
        hybrid_search.assert_not_called()
        encode.assert_not_called()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="read_only",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_read_only_precedes_authentication_for_anonymous_user_and_admin(news_obj):
    user = User.objects.create_user(username="policy-user", password="test-password")
    admin = User.objects.create_superuser(
        username="policy-admin", email="policy-admin@example.test", password="test-password"
    )
    anonymous_client = APIClient()
    user_client = APIClient()
    user_client.force_login(user)
    admin_client = APIClient()
    admin_client.force_login(admin)

    chat_path = reverse("news-chat", args=[news_obj.pk])
    restricted_requests = (
        (anonymous_client, "get", chat_path, {}),
        (user_client, "get", chat_path, {}),
        (user_client, "delete", chat_path, {}),
        (anonymous_client, "get", reverse("news-tts", args=[news_obj.pk]), {}),
        (user_client, "get", reverse("research-session-list"), {}),
        (user_client, "post", reverse("research-create"), {"query": "test"}),
        (anonymous_client, "post", reverse("chatgpt-subscription-handoff"), {}),
        (
            anonymous_client,
            "get",
            reverse("chatgpt-subscription-callback") + "?code=fake&state=fake",
            {},
        ),
        (admin_client, "get", reverse("crawler-admin-dashboard"), {}),
    )

    before = {
        "users": User.objects.count(),
        "chats": ChatSession.objects.count(),
        "research": ResearchSession.objects.count(),
        "research_results": ResearchSearchResult.objects.count(),
        "comparisons": ProviderComparison.objects.count(),
    }
    with (
        patch.object(NewsListView, "_semantic_search") as semantic_search,
        patch.object(NewsListView, "_hybrid_search") as hybrid_search,
        patch("api.views.get_openai_client") as openai_client,
        patch("api.views.stream_chat") as stream_chat,
        patch("api.services.article_fetcher.comparison.compare_providers") as compare,
        patch("api.services.chatgpt_subscription.complete_authorization") as authorize,
        patch("api.services.chatgpt_subscription.discover_models") as discover,
    ):
        for client, method, path, data in restricted_requests:
            if method == "get":
                response = client.get(path)
            else:
                response = getattr(client, method)(path, data, format="json")
            _assert_policy_response(response)

        semantic_search.assert_not_called()
        hybrid_search.assert_not_called()
        openai_client.assert_not_called()
        stream_chat.assert_not_called()
        compare.assert_not_called()
        authorize.assert_not_called()
        discover.assert_not_called()

    assert before == {
        "users": User.objects.count(),
        "chats": ChatSession.objects.count(),
        "research": ResearchSession.objects.count(),
        "research_results": ResearchSearchResult.objects.count(),
        "comparisons": ProviderComparison.objects.count(),
    }


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=False,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_closed_signup_returns_fixed_error_without_creating_user():
    client = APIClient()
    before = User.objects.count()
    response = client.post(
        reverse("auth-register"),
        {"username": "must-not-register", "password": "test-password"},
        format="json",
    )
    _assert_policy_response(response, "signup_disabled")
    assert User.objects.count() == before


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=False,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_ai_disabled_rejects_only_frozen_expensive_methods_before_dispatch(
    news_obj, monkeypatch
):
    client = APIClient()
    requests = (
        ("news-chat", "POST", {"pk": news_obj.pk}),
        ("news-translate", "POST", {"pk": news_obj.pk}),
        ("news-suggested-questions", "POST", {"pk": news_obj.pk}),
        ("research-create", "POST", {}),
        ("research-chat", "POST", {"pk": TEST_UUID}),
        ("news-tts", "GET", {"pk": news_obj.pk}),
        ("news-tts", "HEAD", {"pk": news_obj.pk}),
        ("provider-comparison-list", "POST", {}),
        ("provider-comparison-retest", "POST", {"pk": 1}),
    )

    with (
        patch.object(NewsListView, "_semantic_search") as semantic_search,
        patch.object(NewsListView, "_hybrid_search") as hybrid_search,
        patch("api.views.get_openai_client") as openai_client,
        patch("api.views.stream_chat") as stream_chat,
        patch("api.services.article_fetcher.comparison.compare_providers") as compare,
    ):
        for route_name, method, kwargs in requests:
            path = reverse(route_name, kwargs=kwargs or None)
            view_spy = Mock()
            pattern = _route_pattern(route_name)
            with monkeypatch.context() as scoped:
                scoped.setattr(pattern, "callback", view_spy)
                response = client.generic(method, path, data={})
            _assert_policy_response(response, "ai_disabled")
            view_spy.assert_not_called()

        semantic_search.assert_not_called()
        hybrid_search.assert_not_called()
        openai_client.assert_not_called()
        stream_chat.assert_not_called()
        compare.assert_not_called()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=False,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=False,
)
def test_ai_disabled_still_allows_personal_chat_and_research_history(news_obj):
    user = User.objects.create_user(username="history-user", password="test-password")
    chat = ChatSession.objects.create(news=news_obj, messages=[{"role": "user", "content": "saved"}])
    research = ResearchSession.objects.create(
        user=user,
        title="Saved research",
        messages=[{"role": "user", "content": "saved"}],
    )
    client = APIClient()
    client.force_login(user)

    chat_path = reverse("news-chat", args=[news_obj.pk])
    chat_response = client.get(chat_path)
    assert chat_response.status_code == 200
    assert chat_response.json() == {"messages": chat.messages}
    assert client.delete(chat_path).status_code == 200
    assert not ChatSession.objects.filter(pk=chat.pk).exists()

    research_path = reverse("research-session-detail", args=[research.pk])
    assert client.get(research_path).status_code == 200
    assert client.delete(research_path).status_code == 204
    assert not ResearchSession.objects.filter(pk=research.pk).exists()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="disabled",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_disabled_chatgpt_auth_rejects_all_subscription_routes():
    client = APIClient()
    for pattern in api_urls.urlpatterns:
        if not pattern.name.startswith("chatgpt-subscription-"):
            continue
        response = client.get(_route_path(pattern))
        _assert_policy_response(response, "chatgpt_auth_disabled")


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="website",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_website_subscription_mode_fails_closed_even_with_request_credentials():
    client = APIClient()
    with (
        patch("api.services.chatgpt_subscription.complete_authorization") as complete,
        patch("api.services.chatgpt_subscription.handoff_authorization") as handoff_auth,
    ):
        callback = client.get(
            reverse("chatgpt-subscription-callback")
            + "?client_id=fake-client&redirect_uri=https%3A%2F%2Fnews.lambert.host%2Fcallback"
            + "&code=fake-code&state=fake-state"
        )
        _assert_policy_response(callback, "hosted_integration_unapproved", status=503)

        handoff = client.post(
            reverse("chatgpt-subscription-handoff"),
            {"client_id": "fake-client", "redirect_uri": "https://news.lambert.host/callback"},
            format="json",
        )
        _assert_policy_response(handoff, "hosted_integration_unapproved", status=503)

        complete.assert_not_called()
        handoff_auth.assert_not_called()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=False,
)
def test_local_subscription_models_require_plan_usage_flag(monkeypatch):
    client = APIClient()
    user = User.objects.create_user(username="plan-user", password="test-password")
    client.force_login(user)
    route = _route_pattern("chatgpt-subscription-models")
    path = _route_path(route)
    view_spy = Mock()
    with monkeypatch.context() as scoped:
        scoped.setattr(route, "callback", view_spy)
        response = client.get(path)
    _assert_policy_response(response, "chatgpt_plan_usage_disabled")
    view_spy.assert_not_called()


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="read_only",
    PUBLIC_SIGNUP_ENABLED=False,
    PUBLIC_AI_ENABLED=False,
    CHATGPT_AUTH_MODE="disabled",
    CHATGPT_PLAN_USAGE_ENABLED=False,
)
def test_read_only_capabilities_have_fixed_schema_no_store_and_no_secrets():
    response = APIClient().get(reverse("capabilities"))
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"site_mode", "chatgpt_auth_mode", "features"}
    assert payload["site_mode"] == "read_only"
    assert payload["chatgpt_auth_mode"] == "disabled"
    features = payload["features"]
    assert set(features) == FEATURE_NAMES
    assert all(set(value) == {"enabled", "reason"} for value in features.values())
    assert all(isinstance(value["enabled"], bool) for value in features.values())
    assert features["news"] == {"enabled": True, "reason": None}
    assert features["keyword_search"] == {"enabled": True, "reason": None}
    for name, feature in features.items():
        if name not in {"news", "keyword_search"}:
            assert feature == {"enabled": False, "reason": "public_read_only"}
    assert "SECRET_KEY" not in str(payload)
    assert "DJANGO_SECRET_KEY" not in str(payload)
    assert "DATABASES" not in str(payload)
    assert "WAITRESS_TRUSTED_PROXY" not in str(payload)


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=False,
    PUBLIC_AI_ENABLED=False,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=False,
)
def test_full_capabilities_match_closed_feature_error_codes():
    client = APIClient()
    payload = client.get(reverse("capabilities")).json()
    features = payload["features"]
    assert payload["site_mode"] == "full"
    assert payload["chatgpt_auth_mode"] == "local_oss"
    assert features["signup"] == {"enabled": False, "reason": "signup_disabled"}
    assert features["semantic_search"] == {
        "enabled": False,
        "reason": "semantic_search_disabled",
    }
    for name in ("translation", "chat", "suggested_questions", "tts", "research", "provider_comparisons"):
        assert features[name] == {"enabled": False, "reason": "ai_disabled"}
    assert features["chat_history"] == {"enabled": True, "reason": None}
    assert features["fetch_full"] == {"enabled": True, "reason": None}
    assert features["chatgpt_subscription"] == {
        "enabled": False,
        "reason": "chatgpt_plan_usage_disabled",
    }

    signup = client.post(
        reverse("auth-register"),
        {"username": "not-created", "password": "test-password"},
        format="json",
    )
    _assert_policy_response(signup, features["signup"]["reason"])

    ai = client.post(reverse("news-chat", args=[1]), {"question": "blocked"}, format="json")
    _assert_policy_response(ai, features["chat"]["reason"])

    subscription = client.get(
        reverse("chatgpt-subscription-models", kwargs={"connection_id": TEST_UUID})
    )
    _assert_policy_response(subscription, features["chatgpt_subscription"]["reason"])


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_full_capabilities_report_semantic_search_enabled_with_ai():
    payload = APIClient().get(reverse("capabilities")).json()
    assert payload["features"]["semantic_search"] == {"enabled": True, "reason": None}


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="website",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_website_capability_remains_disabled_until_approved():
    payload = APIClient().get(reverse("capabilities")).json()
    assert payload["features"]["chatgpt_subscription"] == {
        "enabled": False,
        "reason": "hosted_integration_unapproved",
    }


@override_settings(PUBLIC_SITE_MODE="read_only")
def test_policy_does_not_apply_to_non_api_paths_or_management_work():
    middleware = PublicPolicyMiddleware(lambda request: None)
    request = RequestFactory().get("/internal/crawler/worker/")
    request.resolver_match = Mock(url_name="crawler-admin-dashboard")
    assert middleware.process_view(request, Mock(), (), {}) is None


@pytest.mark.django_db
@override_settings(
    PUBLIC_SITE_MODE="full",
    PUBLIC_SIGNUP_ENABLED=True,
    PUBLIC_AI_ENABLED=True,
    CHATGPT_AUTH_MODE="local_oss",
    CHATGPT_PLAN_USAGE_ENABLED=True,
)
def test_full_development_signup_behavior_is_not_changed():
    response = APIClient().post(
        reverse("auth-register"),
        {"username": "full-mode-user", "password": "test-password"},
        format="json",
    )
    assert response.status_code == 201
    assert User.objects.filter(username="full-mode-user").exists()
