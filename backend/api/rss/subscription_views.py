"""Thin HTTP routes for personal Feed relationships and explicit controls."""
from datetime import timedelta
from hashlib import sha256

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from rest_framework.response import Response

from api.models import ChannelSubscription
from api.rss.access import authorized_news, authorized_sources
from api.rss.discovery import discovery_operation_result
from api.rss.http import RssAPIView
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation, SourceFeedLink
from api.rss.operations import change_policy, enqueue_operation, get_operation_for_actor
from api.rss.subscriptions import subscribe, subscription_data, unsubscribe


class SubscriptionsView(RssAPIView):
    def get(self, request):
        rows = ChannelSubscription.objects.filter(user=request.user,
            source_id__in=authorized_sources(request.user).values('pk'), source__feed_links__isnull=False).distinct().select_related('source__publication')
        return Response({'results': [subscription_data(row) for row in rows]})

    def post(self, request):
        status, data = subscribe(request.user, request.data, request.headers.get('Idempotency-Key'))
        return Response(data, status=status)


class SubscriptionDetailView(RssAPIView):
    def delete(self, request, pk):
        unsubscribe(request.user, pk)
        return Response(status=204)


class OperationView(RssAPIView):
    def get(self, request, pk):
        data = get_operation_for_actor(request.user, pk)
        if data['kind'] == 'discover':
            operation = get_object_or_404(FeedOperation, pk=pk, actor=request.user)
            data['result'] = discovery_operation_result(operation, request.user)
        return Response(data)


def _authorized_binding(user, pk):
    return get_object_or_404(FeedBinding.objects.filter(pk=pk, source_links__source_id__in=
        authorized_sources(user).values('pk'), source_links__enabled=True,
        source_links__source__publication__owner='miniflux').distinct())


def _key(request, prefix):
    raw = request.headers.get('Idempotency-Key')
    if not isinstance(raw, str) or not 1 <= len(raw) <= 128 or not raw.isprintable():
        raise ValidationError('请提供有效的 Idempotency-Key。')
    return prefix + ':' + sha256(raw.encode()).hexdigest()


class RefreshFeedView(RssAPIView):
    @transaction.atomic
    def post(self, request, pk):
        FeedBinding.objects.filter(pk=pk).update(updated_at=F('updated_at'))
        binding = _authorized_binding(request.user, pk)
        if not binding.desired_enabled or binding.connection_state != 'ready':
            raise PermissionDenied('来源尚未连接或已暂停。')
        key = _key(request, 'refresh')
        recent = FeedOperation.objects.filter(binding=binding, kind='refresh_feed',
            created_at__gte=timezone.now() - timedelta(seconds=60)).order_by('-created_at').first()
        if recent and (recent.actor_id != request.user.pk or recent.dedupe_key != key):
            raise Throttled(wait=60, detail='刷新已在处理中，请稍后查看。')
        operation = enqueue_operation('refresh_feed', actor=request.user, dedupe_key=key, binding=binding)
        return Response({'operation_id': str(operation.pk), 'state': operation.state}, status=202)


class RefetchArticleView(RssAPIView):
    @transaction.atomic
    def post(self, request, pk):
        # Reserve writer before ACL/token reads; no engine work runs here.
        from django.contrib.auth import get_user_model
        get_user_model().objects.filter(pk=request.user.pk).update(last_login=F('last_login'))
        news = get_object_or_404(authorized_news(request.user), pk=pk)
        if news.body_owner_binding_id is None:
            raise PermissionDenied('此文章尚未由 RSS 引擎接管。')
        binding = _authorized_binding(request.user, news.body_owner_binding_id)
        source_ids = authorized_sources(request.user, body=True).values('pk')
        link = SourceFeedLink.objects.filter(binding=binding, enabled=True,
            source_id__in=source_ids, source__publication__owner='miniflux').order_by('pk').first()
        entry = EngineEntryMap.objects.filter(binding=binding, news=news, source_url=news.url,
                                             disposition='linked').order_by('engine_entry_id').first()
        if link is None or entry is None:
            raise Http404
        recent = FeedOperation.objects.filter(binding=binding, entry=entry, kind='refetch_entry',
            created_at__gte=timezone.now()-timedelta(seconds=60)).order_by('-created_at').first()
        if recent and recent.actor_id != request.user.pk:
            raise Throttled(wait=60, detail='正文修复已在处理中，请稍后查看。')
        if (recent and recent.intent_version == binding.policy_version
                and recent.safe_input.get('fence', {}).get('expected_revision') == news.full_content_revision):
            return Response({'operation_id': str(recent.pk), 'state': recent.state}, status=202)
        operation = enqueue_operation('refetch_entry', actor=request.user, binding=binding, entry=entry,
            source_id=link.source_id, dedupe_key=_key(request, 'refetch'))
        return Response({'operation_id': str(operation.pk), 'state': operation.state}, status=202)


class FeedPolicyView(RssAPIView):
    def patch(self, request, pk):
        if not request.user.is_staff:
            raise PermissionDenied('需要管理权限。')
        if (not isinstance(request.data, dict) or set(request.data) != {'desired_mode', 'expected_policy_version'}
                or type(request.data['expected_policy_version']) is not int
                or request.data['expected_policy_version'] < 1):
            raise ValidationError('请提供采集模式及当前策略版本。')
        binding = get_object_or_404(FeedBinding, pk=pk)
        operation = change_policy(binding.pk, actor=request.user,
            expected_policy_version=request.data['expected_policy_version'], desired_mode=request.data['desired_mode'])
        return Response({'operation_id': str(operation.pk), 'state': operation.state}, status=202)
