"""HTTP-level feature and read-only gates for the public API."""
from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.urls import Resolver404, resolve
import json
import re
import uuid

RSS_API_PATH = re.compile(r'^/api/(?:rss/|me/rss-|admin/rss/|news/\d+/rss-refetch/|me/news/\d+/read-state/)')


def rss_policy_envelope(request, response):
    """Keep the new API contract even when policy rejects before view dispatch."""
    if not RSS_API_PATH.match(request.path_info) or response.status_code < 400:
        return response
    try:
        payload = json.loads(response.content)
    except (ValueError, AttributeError):
        return response
    if isinstance(payload.get('error'), dict):
        return response
    code = payload.get('error_code', 'stale' if response.status_code == 409 else 'forbidden')
    message = payload.get('error') or payload.get('detail') or '请求无法完成。'
    response.content = json.dumps({'error': {'code': code, 'message': message, 'retryable': False},
                                   'request_id': str(uuid.uuid4())}, ensure_ascii=False).encode()
    response['Cache-Control'] = 'private, no-store'
    return response

READ_ONLY_ROUTES = frozenset({
    'news-list', 'news-detail', 'category-list', 'source-list', 'auth-csrf',
    'capabilities', 'health-live', 'health-ready', 'rss-directory',
    'smart-channel-catalog', 'smart-channel-profile', 'smart-channel-dashboard',
})
READ_ONLY_METHODS = frozenset({'GET', 'HEAD'})
AI_GATED_METHODS = {
    'byok-translation-start': frozenset({'POST'}),
    'news-chat': frozenset({'POST'}), 'news-chat-cancel': frozenset({'POST'}),
    'news-translate': frozenset({'POST'}),
    'news-suggested-questions': frozenset({'POST'}), 'research-create': frozenset({'POST'}),
    'research-chat': frozenset({'POST'}), 'news-tts': frozenset({'GET', 'HEAD'}),
    'provider-comparison-list': frozenset({'POST'}), 'provider-comparison-retest': frozenset({'POST'}),
}
ERROR_MESSAGES = {
    'public_read_only': '当前站点处于只读公开模式。',
    'semantic_search_disabled': '语义搜索当前不可用。',
    'signup_disabled': '公开注册当前已关闭。', 'ai_disabled': '此 AI 功能当前已关闭。',
    'chatgpt_auth_disabled': 'ChatGPT 订阅连接当前已关闭。',
    'hosted_integration_unapproved': '网站订阅集成尚未获批。',
    'chatgpt_plan_usage_disabled': 'ChatGPT 订阅模型调用当前已关闭。',
}


def policy_error(error_code: str, status_code: int = 403) -> JsonResponse:
    response = JsonResponse({'error': ERROR_MESSAGES[error_code], 'error_code': error_code}, status=status_code)
    response['Cache-Control'] = 'no-store'
    return response


class PublicPolicyMiddleware:
    """Reject disabled API work before DRF authentication and view dispatch."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method == 'OPTIONS' and request.META.get('HTTP_ACCESS_CONTROL_REQUEST_METHOD')
                and request.path_info.startswith('/api/') and settings.PUBLIC_SITE_MODE == 'read_only'):
            try:
                resolve(request.path_info)
            except Resolver404:
                return HttpResponseNotFound()
            return rss_policy_envelope(request, policy_error('public_read_only'))
        return rss_policy_envelope(request, self.get_response(request))

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.path_info.startswith('/api/'):
            return None
        resolver_match = request.resolver_match
        route_name = resolver_match.url_name if resolver_match else None
        if route_name is None:
            return None
        if settings.PUBLIC_SITE_MODE == 'read_only':
            if route_name not in READ_ONLY_ROUTES or request.method not in READ_ONLY_METHODS:
                return policy_error('public_read_only')
        expected_viewer = request.META.get('HTTP_X_WORKSPACE_VIEWER')
        if expected_viewer is not None and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            user = getattr(request, 'user', None)
            if not user or not user.is_authenticated or expected_viewer != str(user.pk):
                response = JsonResponse({'detail': '账号已变化，请刷新页面后重试。'}, status=409)
                response['Cache-Control'] = 'no-store'
                return response
        if (route_name == 'news-list' and request.method in READ_ONLY_METHODS
                and (settings.PUBLIC_SITE_MODE == 'read_only' or not settings.PUBLIC_AI_ENABLED)):
            if request.GET.get('mode') not in (None, 'keyword'):
                return policy_error('semantic_search_disabled')
        if route_name == 'auth-register' and not settings.PUBLIC_SIGNUP_ENABLED:
            return policy_error('signup_disabled')
        byok_research_create = (
            route_name in {'research-create', 'research-chat'}
            and request.method == 'POST'
            and settings.PUBLIC_SITE_MODE == 'full'
            and getattr(settings, 'AI_BYOK_ENABLED', False)
        )
        if (not settings.PUBLIC_AI_ENABLED
                and request.method in AI_GATED_METHODS.get(route_name, ())
                and not byok_research_create):
            return policy_error('ai_disabled')
        if (settings.DJANGO_ENV == 'production'
                and route_name in {'research-create', 'research-chat'}
                and request.method == 'POST'
                and not byok_research_create):
            return policy_error('hosted_integration_unapproved', status_code=503)
        if route_name.startswith('chatgpt-subscription-'):
            auth_mode = settings.CHATGPT_AUTH_MODE
            if auth_mode == 'disabled':
                return policy_error('chatgpt_auth_disabled')
            if auth_mode == 'website':
                return policy_error('hosted_integration_unapproved', status_code=503)
            if auth_mode == 'local_oss' and route_name == 'chatgpt-subscription-models' and not settings.CHATGPT_PLAN_USAGE_ENABLED:
                return policy_error('chatgpt_plan_usage_disabled')
        return None
