"""Public, non-sensitive description of site-level feature switches."""

from django.conf import settings
from api.services.semantic_search import semantic_search_enabled
from django.http import JsonResponse
from django.views.decorators.http import require_safe


FEATURE_NAMES = (
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
    "research_byok_create",
    "provider_comparisons",
    "admin",
    "chatgpt_subscription",
)

AI_FEATURE_NAMES = (
    "translation",
    "chat",
    "suggested_questions",
    "tts",
    "research",
    "provider_comparisons",
)


def _feature(enabled: bool, reason: str | None = None) -> dict[str, object]:
    return {"enabled": enabled, "reason": None if enabled else reason}


def _feature_snapshot() -> dict[str, dict[str, object]]:
    if settings.PUBLIC_SITE_MODE == "read_only":
        features = {name: _feature(False, "public_read_only") for name in FEATURE_NAMES}
        features["news"] = _feature(True)
        features["keyword_search"] = _feature(True)
        return features

    features = {name: _feature(True) for name in FEATURE_NAMES}

    if not settings.PUBLIC_SIGNUP_ENABLED:
        features["signup"] = _feature(False, "signup_disabled")

    features["semantic_search"] = _feature(semantic_search_enabled(), "semantic_search_disabled")
    if not settings.PUBLIC_AI_ENABLED:
        for name in AI_FEATURE_NAMES:
            features[name] = _feature(False, "ai_disabled")

    # Keep hosted/shared research closed in production. The historical public
    # capability name now covers either explicitly authorized personal source.
    if settings.DJANGO_ENV == "production":
        features["research"] = _feature(False, "hosted_integration_unapproved")
    subscription_create_enabled = (
        settings.CHATGPT_AUTH_MODE == "local_oss"
        and settings.DJANGO_ENV != "production"
        and getattr(settings, "CHATGPT_PLAN_USAGE_ENABLED", False)
    )
    # BYOK/subscription research create is independent of PUBLIC_AI_ENABLED.
    # Local full stacks with PUBLIC_AI still need this flag so the UI requires
    # explicit consent+model; otherwise creates fall into personal_clients_for_user
    # which refuses inference and the worker remaps that to provider_unavailable.
    authorized_create_enabled = (
        settings.PUBLIC_SITE_MODE == "full"
        and (
            getattr(settings, "AI_BYOK_ENABLED", False)
            or subscription_create_enabled
        )
    )
    features["research_byok_create"] = _feature(
        authorized_create_enabled,
        None if authorized_create_enabled else (
            "hosted_integration_unapproved"
            if settings.DJANGO_ENV == "production"
            else "ai_disabled"
        ),
    )

    if settings.CHATGPT_AUTH_MODE == "disabled":
        features["chatgpt_subscription"] = _feature(False, "chatgpt_auth_disabled")
    elif settings.CHATGPT_AUTH_MODE == "website":
        features["chatgpt_subscription"] = _feature(
            False, "hosted_integration_unapproved"
        )
    elif not settings.CHATGPT_PLAN_USAGE_ENABLED:
        features["chatgpt_subscription"] = _feature(
            False, "chatgpt_plan_usage_disabled"
        )

    features["provider_comparisons"] = _feature(False, "legacy_ingestion_retired")

    return features


@require_safe
def capabilities(_request):
    response = JsonResponse(
        {
            "site_mode": settings.PUBLIC_SITE_MODE,
            "chatgpt_auth_mode": settings.CHATGPT_AUTH_MODE,
            "features": _feature_snapshot(),
        }
    )
    response["Cache-Control"] = "no-store"
    return response
