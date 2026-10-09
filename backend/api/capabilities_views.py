"""Public, non-sensitive description of site-level feature switches."""

from django.conf import settings
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

    if not settings.PUBLIC_AI_ENABLED:
        features["semantic_search"] = _feature(False, "semantic_search_disabled")
        for name in AI_FEATURE_NAMES:
            features[name] = _feature(False, "ai_disabled")

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
