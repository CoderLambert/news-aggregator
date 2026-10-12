from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.crawler_views import IsActiveSuperuser, error_response
from api.models import JinaFallbackPolicy
from api.services.article_fetch_monitor import (
    monitor_dashboard,
    policy_payload,
    validate_policy_domain,
)


logger = logging.getLogger(__name__)
ALLOWED_WINDOWS = {1, 7, 30}


def _domain_from_request(value) -> str | None:
    try:
        return validate_policy_domain(value)
    except ValueError:
        return None


class ArticleFetchDashboardView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 7))
        except (TypeError, ValueError):
            days = 0
        if days not in ALLOWED_WINDOWS:
            return error_response('invalid_window', 'days 只允许 1、7 或 30。')
        return Response(monitor_dashboard(days=days))


class JinaFallbackPolicyListView(APIView):
    permission_classes = [IsActiveSuperuser]

    def post(self, request):
        if set(request.data) - {'domain', 'enabled'} or 'domain' not in request.data:
            return error_response('invalid_policy', '只允许提交 domain 和可选的 enabled。')
        domain = _domain_from_request(request.data.get('domain'))
        enabled = request.data.get('enabled', False)
        if domain is None or not isinstance(enabled, bool):
            return error_response('invalid_policy', '域名或 enabled 无效。')
        if JinaFallbackPolicy.objects.filter(pk=domain).exists():
            return error_response('policy_exists', '该域名策略已存在。', status.HTTP_409_CONFLICT)
        policy = JinaFallbackPolicy.objects.create(
            domain=domain,
            enabled=enabled,
            auto_discovered=False,
            last_seen_at=timezone.now(),
            updated_by=request.user,
        )
        logger.warning(
            'jina_fallback_policy_created domain=%s enabled=%s user_id=%s',
            domain,
            enabled,
            request.user.pk,
        )
        return Response(policy_payload(policy), status=status.HTTP_201_CREATED)


class JinaFallbackPolicyDetailView(APIView):
    permission_classes = [IsActiveSuperuser]

    def patch(self, request, domain):
        if set(request.data) != {'enabled'} or not isinstance(request.data.get('enabled'), bool):
            return error_response('invalid_policy', '只允许修改 enabled 布尔值。')
        normalized = _domain_from_request(domain)
        if normalized is None:
            return error_response('invalid_policy', '域名格式无效。')
        try:
            policy = JinaFallbackPolicy.objects.get(pk=normalized)
        except JinaFallbackPolicy.DoesNotExist:
            return error_response('policy_not_found', '域名策略不存在。', status.HTTP_404_NOT_FOUND)
        policy.enabled = request.data['enabled']
        policy.auto_discovered = False
        policy.updated_by = request.user
        policy.save(update_fields=['enabled', 'auto_discovered', 'updated_by', 'updated_at'])
        logger.warning(
            'jina_fallback_policy_changed domain=%s enabled=%s user_id=%s',
            normalized,
            policy.enabled,
            request.user.pk,
        )
        return Response(policy_payload(policy))
