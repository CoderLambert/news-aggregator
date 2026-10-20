"""Shared v1 HTTP contract for RSS endpoints; existing session CSRF stays active."""
from collections.abc import Mapping
import uuid

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import APIException, NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView


class RssConflict(APIException):
    status_code = 409
    default_detail = '状态已改变，请刷新后重试。'
    default_code = 'stale'


class RssAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    personal = True

    def initial(self, request, *args, **kwargs):
        self.request_id = str(uuid.uuid4())
        super().initial(request, *args, **kwargs)
        if self.personal and not request.user.is_authenticated:
            raise NotAuthenticated('请先登录。')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if not request.user.is_authenticated:
                raise NotAuthenticated('请先登录。')
            if settings.PUBLIC_SITE_MODE == 'read_only':
                raise PermissionDenied('当前站点只允许阅读。', code='public_read_only')
            if request.content_type == 'application/json' and not isinstance(request.data, Mapping):
                raise ValidationError('请求内容须为 JSON 对象。')

    def handle_exception(self, exc):
        from api.rss.operations import OperationError
        if isinstance(exc, OperationError):
            from api.rss.rsshub import MESSAGES
            if exc.code in MESSAGES:
                exc = APIException(MESSAGES[exc.code],code=exc.code)
                exc.status_code=400
        if isinstance(exc, OperationError):
            if exc.code == 'not_found':
                from rest_framework.exceptions import NotFound
                exc = NotFound()
            elif exc.code in {'refetch_not_allowed', 'invalid_actor',
                              'source_collection_not_permitted', 'full_content_policy_not_permitted',
                              'unsupported_association_policy', 'full_content_disabled'}:
                exc = PermissionDenied('当前策略不允许此操作。', code=exc.code)
            elif exc.code in {'idempotency_conflict', 'policy_conflict', 'stale_policy'}:
                exc = RssConflict(code=exc.code)
            else:
                exc = ValidationError('RSS 请求无效。', code=exc.code)
        response = super().handle_exception(exc)
        if isinstance(exc, NotAuthenticated):
            response.status_code = 401
        status = response.status_code
        defaults = {400: 'invalid_input', 401: 'not_authenticated', 403: 'forbidden',
                    404: 'not_found', 409: 'stale', 413: 'too_large', 429: 'rate_limited',
                    502: 'engine_failed', 503: 'unavailable'}
        detail = getattr(exc, 'detail', None)
        response.data = {'error': {
            'code': getattr(detail, 'code', None) or defaults.get(status, 'request_failed'),
            'message': str(detail) if isinstance(detail, str) else '请求无法完成。',
            'retryable': status in {429, 502, 503},
        }, 'request_id': getattr(self, 'request_id', str(uuid.uuid4()))}
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response
