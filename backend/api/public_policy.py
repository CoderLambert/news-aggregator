"""HTTP-level feature and read-only gates for the public API."""

from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.urls import Resolver404, resolve


READ_ONLY_ROUTES = frozenset(
    {
        "news-list",
        "news-detail",
        "category-list",
        "source-list",
        "auth-csrf",
        "capabilities",
        "health-live",
        "health-ready",
    }
)
READ_ONLY_METHODS = frozenset({"GET", "HEAD"})

AI_GATED_METHODS = {
    "news-chat": frozenset({"POST"}),
    "news-translate": frozenset({"POST"}),
    "news-suggested-questions": frozenset({"POST"}),
    "research-create": frozenset({"POST"}),
    "research-chat": frozenset({"POST"}),
    "news-tts": frozenset({"GET", "HEAD"}),
    "provider-comparison-list": frozenset({"POST"}),
    "provider-comparison-retest": frozenset({"POST"}),
}

ERROR_MESSAGES = {
    "public_read_only": "当前站点处于只读公开模式。",
    "semantic_search_disabled": "语义搜索当前不可用。",
    "signup_disabled": "公开注册当前已关闭。",
    "ai_disabled": "此 AI 功能当前已关闭。",
    "chatgpt_auth_disabled": "ChatGPT 订阅连接当前已关闭。",
    "hosted_integration_unapproved": "网站订阅集成尚未获批。",
    "chatgpt_plan_usage_disabled": "ChatGPT 订阅模型调用当前已关闭。",
}


def policy_error(error_code: str, status_code: int = 403) -> JsonResponse:
    """Create a fixed, non-sensitive policy response that cannot be cached."""
    response = JsonResponse(
        {
            "error": ERROR_MESSAGES[error_code],
            "error_code": error_code,
        },
        status=status_code,
    )
    response["Cache-Control"] = "no-store"
    return response


class PublicPolicyMiddleware:
    """Reject disabled API work before DRF authentication and view dispatch."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # CorsMiddleware handles preflight OPTIONS requests before Django runs
        # process_view. Resolve API preflights here so read-only policy and the
        # unknown-route 404 behavior still apply before CORS can short-circuit.
        if (
            request.method == "OPTIONS"
            and request.META.get("HTTP_ACCESS_CONTROL_REQUEST_METHOD")
            and request.path_info.startswith("/api/")
            and settings.PUBLIC_SITE_MODE == "read_only"
        ):
            try:
                resolve(request.path_info)
            except Resolver404:
                return HttpResponseNotFound()
            return policy_error("public_read_only")
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        path = request.path_info
        if not path.startswith("/api/"):
            return None

        resolver_match = request.resolver_match
        route_name = resolver_match.url_name if resolver_match else None
        if route_name is None:
            return None

        if settings.PUBLIC_SITE_MODE == "read_only":
            if route_name not in READ_ONLY_ROUTES or request.method not in READ_ONLY_METHODS:
                return policy_error("public_read_only")

        if (
            route_name == "news-list"
            and request.method in READ_ONLY_METHODS
            and (
                settings.PUBLIC_SITE_MODE == "read_only"
                or not settings.PUBLIC_AI_ENABLED
            )
        ):
            requested_mode = request.GET.get("mode")
            if requested_mode not in (None, "keyword"):
                return policy_error("semantic_search_disabled")

        if route_name == "auth-register" and not settings.PUBLIC_SIGNUP_ENABLED:
            return policy_error("signup_disabled")

        if not settings.PUBLIC_AI_ENABLED:
            allowed_methods = AI_GATED_METHODS.get(route_name, ())
            if request.method in allowed_methods:
                return policy_error("ai_disabled")

        if route_name.startswith("chatgpt-subscription-"):
            auth_mode = settings.CHATGPT_AUTH_MODE
            if auth_mode == "disabled":
                return policy_error("chatgpt_auth_disabled")
            if auth_mode == "website":
                return policy_error("hosted_integration_unapproved", status_code=503)
            if (
                auth_mode == "local_oss"
                and route_name == "chatgpt-subscription-models"
                and not settings.CHATGPT_PLAN_USAGE_ENABLED
            ):
                return policy_error("chatgpt_plan_usage_disabled")

        return None
