from django.db import transaction
from django.db.models import Case, IntegerField, JSONField, Max, Min, OuterRef, Prefetch, Subquery, Value, When
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from api.crawler_serializers import (
    CrawlBatchSerializer,
    CrawlRunSerializer,
    CrawlerSettingsSerializer,
    CrawlerTargetSerializer,
    SourceConfigSerializer,
)
from api.models import (
    ChannelSubscription, CrawlBatch, CrawlRun, CrawlerTarget, FeedState, News,
    NewsSourceItem, RequestBudget, SourceConfig,
)
from api.services.crawler_control import (
    ACTIVE_RUN_STATUSES,
    NoTargetsQueued,
    create_crawl_batch,
    get_crawler_settings,
    request_run_cancel,
    sync_crawler_targets,
    worker_is_online,
)
from api.services.source_registry import runtime_registry


class IsActiveSuperuser(BasePermission):
    message = '只有超级管理员可以访问爬虫控制台。'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def error_response(code, message, http_status=status.HTTP_400_BAD_REQUEST, *, fields=None):
    payload = {'code': code, 'message': message}
    if fields:
        payload['fields'] = fields
    return Response(payload, status=http_status)


def target_queryset():
    active_runs = CrawlRun.objects.filter(status__in=ACTIVE_RUN_STATUSES).select_related('target', 'batch')
    latest = CrawlRun.objects.filter(target_id=OuterRef('pk'), finished_at__isnull=False).order_by('-finished_at', '-queued_at')
    return CrawlerTarget.objects.filter(spider_name__in=runtime_registry(include_unavailable=True)).annotate(
        last_run_stats=Subquery(latest.values('stats')[:1], output_field=JSONField()),
        last_run_exit_code=Subquery(latest.values('exit_code')[:1], output_field=IntegerField()),
    ).prefetch_related(
        Prefetch('runs', queryset=active_runs, to_attr='prefetched_active_runs'),
    ).order_by('sort_order', 'spider_name')


def batch_queryset():
    runs = CrawlRun.objects.select_related('target').prefetch_related(
        Prefetch(
            'retries',
            queryset=CrawlRun.objects.only('id', 'status', 'retry_of_id', 'queued_at', 'exit_code', 'stats').order_by('-queued_at'),
            to_attr='prefetched_retries',
        ),
    ).order_by('queued_at')
    return CrawlBatch.objects.prefetch_related(
        Prefetch('runs', queryset=runs),
    ).order_by('-queued_at')


class CrawlerReadinessView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        from api.services.crawler_readiness import readiness_snapshot
        return Response(readiness_snapshot())


class CrawlerDashboardView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        sync_crawler_targets()
        crawler_settings = get_crawler_settings()
        settings_data = CrawlerSettingsSerializer(crawler_settings).data
        settings_data['worker_online'] = worker_is_online(crawler_settings)
        active_run = (
            CrawlRun.objects.select_related('target', 'batch')
            .filter(status__in=ACTIVE_RUN_STATUSES)
            .annotate(active_order=Case(
                When(status='running', then=Value(0)),
                When(status='cancel_requested', then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ))
            .order_by('active_order', 'queued_at')
            .first()
        )
        recent_batches = batch_queryset()[:8]
        return Response({
            'settings': settings_data,
            'active_run': CrawlRunSerializer(active_run).data if active_run else None,
            'targets': CrawlerTargetSerializer(target_queryset(), many=True).data,
            'recent_batches': CrawlBatchSerializer(recent_batches, many=True).data,
            'server_time': timezone.now(),
        })


class CrawlerSettingsView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        instance = get_crawler_settings()
        data = CrawlerSettingsSerializer(instance).data
        data['worker_online'] = worker_is_online(instance)
        return Response(data)

    def patch(self, request):
        instance = get_crawler_settings()
        was_enabled = instance.scheduler_enabled
        serializer = CrawlerSettingsSerializer(instance, data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response('invalid_settings', '调度设置无效。', fields=serializer.errors)
        updated = serializer.save(updated_by=request.user)
        if 'interval_seconds' in request.data or (not was_enabled and updated.scheduler_enabled):
            from datetime import timedelta
            updated.next_run_at = timezone.now() + timedelta(seconds=updated.interval_seconds)
            updated.save(update_fields=['next_run_at'])
        data = CrawlerSettingsSerializer(updated).data
        data['worker_online'] = worker_is_online(updated)
        return Response(data)


class CrawlerTargetListView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        sync_crawler_targets()
        return Response(CrawlerTargetSerializer(target_queryset(), many=True).data)


class CrawlerTargetDetailView(APIView):
    permission_classes = [IsActiveSuperuser]

    def patch(self, request, spider_name):
        if spider_name not in runtime_registry(include_unavailable=True):
            return error_response('unknown_spider', '该爬虫不在服务器白名单中。', status.HTTP_404_NOT_FOUND)
        if set(request.data) != {'enabled'} or not isinstance(request.data.get('enabled'), bool):
            return error_response('invalid_target', '只允许修改 enabled 布尔值。')
        sync_crawler_targets()
        target = CrawlerTarget.objects.get(pk=spider_name)
        if request.data['enabled'] is False and target.runs.filter(status__in=ACTIVE_RUN_STATUSES).exists():
            return error_response('target_active', '运行中的来源不能停用。', status.HTTP_409_CONFLICT)
        target.enabled = request.data['enabled']
        target.save(update_fields=['enabled'])
        target = target_queryset().get(pk=spider_name)
        return Response(CrawlerTargetSerializer(target).data)


def _source_monitoring(source_key):
    target = CrawlerTarget.objects.filter(pk=source_key).first()
    feed = FeedState.objects.filter(source_key=source_key).aggregate(
        last_success_at=Max('last_success_at'), next_poll_at=Min('next_poll_at'),
    )
    latest_item = (
        NewsSourceItem.objects.filter(source_key=source_key)
        .select_related('news').order_by('-news__publish_time', '-last_seen_at').first()
    )
    last_success = (
        CrawlRun.objects.filter(target_id=source_key, status='succeeded')
        .order_by('-finished_at').values_list('finished_at', flat=True).first()
    )
    host_keys = []
    config = SourceConfig.objects.filter(pk=source_key).prefetch_related('endpoints').first()
    if config:
        from urllib.parse import urlsplit
        host_keys = [f'host:{urlsplit(endpoint.url).hostname}' for endpoint in config.endpoints.all()]
    cooldown = RequestBudget.objects.filter(pk__in=host_keys).aggregate(value=Max('cooldown_until'))['value']
    return {
        'last_success_at': last_success,
        'latest_article': ({
            'id': latest_item.news_id, 'title': latest_item.news.title,
            'publish_time': latest_item.news.publish_time, 'url': latest_item.news.url,
        } if latest_item else None),
        'last_failure': target.last_safe_error if target and target.last_status == 'failed' else '',
        'last_http_statuses': (
            CrawlRun.objects.filter(target_id=source_key).order_by('-queued_at')
            .values_list('http_statuses', flat=True).first() or {}
        ),
        'cooldown_until': cooldown,
        'next_poll_at': feed['next_poll_at'],
        'last_feed_success_at': feed['last_success_at'],
        'last_target_finished_at': target.last_finished_at if target else None,
    }


def _dynamic_source_data(config, request=None):
    data = SourceConfigSerializer(config, context={'request': request} if request else {}).data
    data['monitoring'] = _source_monitoring(config.source_key)
    data['read_only'] = False
    return data


def _code_source_data(source_key, entry):
    from api.services.source_policy import policy_for_key
    policy = policy_for_key(source_key)
    return {
        'source_key': source_key, 'publisher_name': policy.name, 'channel_name': policy.name,
        'category_name': policy.default_category, 'region': policy.region, 'language': policy.language,
        'content_kind': policy.content_kind, 'reading_policy': policy.reading_policy,
        'status': 'enabled', 'config_version': policy.contract_version, 'maintenance': 'code',
        'probe_is_current': True, 'approval_is_current': True, 'can_enable': False,
        'endpoints': ([{'kind': 'rss', 'url': policy.feed_url, 'allowed_domains': list(policy.domains)}]
                      if policy.feed_url else []),
        'monitoring': _source_monitoring(source_key), 'read_only': True,
    }


class SourceConfigListCreateView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        dynamic = {
            config.source_key: _dynamic_source_data(config, request)
            for config in SourceConfig.objects.select_related('category', 'source').prefetch_related('endpoints')
        }
        rows = []
        for key, entry in runtime_registry(include_unavailable=True).items():
            rows.append(dynamic.get(key) or _code_source_data(key, entry))
        return Response(rows)

    def post(self, request):
        serializer = SourceConfigSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return error_response('invalid_source_config', '来源配置无效。', fields=serializer.errors)
        config = serializer.save()
        return Response(_dynamic_source_data(config, request), status=status.HTTP_201_CREATED)


class SourceConfigDetailView(APIView):
    permission_classes = [IsActiveSuperuser]

    def _get(self, source_key):
        return SourceConfig.objects.select_related('category', 'source').prefetch_related('endpoints').filter(pk=source_key).first()

    def get(self, request, source_key):
        config = self._get(source_key)
        if config:
            return Response(_dynamic_source_data(config, request))
        entry = runtime_registry(include_unavailable=True).get(source_key)
        if entry and entry.maintenance == 'code':
            return Response(_code_source_data(source_key, entry))
        return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)

    def patch(self, request, source_key):
        config = self._get(source_key)
        if not config:
            if source_key in runtime_registry(include_unavailable=True):
                return error_response('code_maintained', '代码维护的来源不能在后台修改。', status.HTTP_409_CONFLICT)
            return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)
        serializer = SourceConfigSerializer(config, data=request.data, partial=True, context={'request': request})
        if not serializer.is_valid():
            return error_response('invalid_source_config', '来源配置无效。', fields=serializer.errors)
        config = serializer.save()
        return Response(_dynamic_source_data(config, request))

    @transaction.atomic
    def delete(self, request, source_key):
        config = SourceConfig.objects.select_for_update().filter(pk=source_key).first()
        if not config:
            return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)
        target = CrawlerTarget.objects.select_for_update().filter(pk=source_key).first()
        has_history = bool(target and target.runs.exists())
        has_articles = (NewsSourceItem.objects.filter(source_key=source_key).exists() or
                        (config.source_id and News.objects.filter(source_id=config.source_id).exists()))
        has_subscriptions = bool(config.source_id and ChannelSubscription.objects.filter(source_id=config.source_id).exists())
        if config.status != 'draft' or has_history or has_articles or has_subscriptions:
            return error_response(
                'source_must_be_disabled',
                '只有没有文章、运行记录和订阅关系的草稿配置可以删除；请改为停用。',
                status.HTTP_409_CONFLICT,
            )
        source = config.source
        config.delete()
        if target:
            target.delete()
        if source and not News.objects.filter(source=source).exists() and not ChannelSubscription.objects.filter(source=source).exists():
            source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SourceConfigProbeView(APIView):
    permission_classes = [IsActiveSuperuser]

    def post(self, request, source_key):
        config = SourceConfig.objects.filter(pk=source_key).first()
        if not config:
            return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)
        from api.services.source_probe import ProbeConflict, probe_source
        try:
            config = probe_source(config)
        except ProbeConflict:
            return error_response('configuration_changed', '探测期间配置已变化，请重新探测。', status.HTTP_409_CONFLICT)
        return Response(_dynamic_source_data(config, request))


class SourceConfigApproveView(APIView):
    permission_classes = [IsActiveSuperuser]

    @transaction.atomic
    def post(self, request, source_key):
        config = SourceConfig.objects.select_for_update().filter(pk=source_key).first()
        if not config:
            return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)
        if config.status != 'probed' or not config.probe_is_current:
            return error_response('probe_required', '必须先对当前配置版本完成成功探测。', status.HTTP_409_CONFLICT)
        config.status = 'approved'
        config.approved_config_version = config.config_version
        config.approved_by = request.user
        config.approved_at = timezone.now()
        config.save(update_fields=['status', 'approved_config_version', 'approved_by', 'approved_at', 'updated_at'])
        CrawlerTarget.objects.update_or_create(
            spider_name=source_key,
            defaults={'display_name': config.channel_name, 'enabled': False},
        )
        return Response(_dynamic_source_data(config, request))


class SourceConfigEnableView(APIView):
    permission_classes = [IsActiveSuperuser]

    @transaction.atomic
    def post(self, request, source_key):
        enabled = request.data.get('enabled', True)
        if not isinstance(enabled, bool):
            return error_response('invalid_enabled', 'enabled 必须是布尔值。')
        config = SourceConfig.objects.select_for_update().filter(pk=source_key).first()
        if not config:
            return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)
        target, _ = CrawlerTarget.objects.select_for_update().get_or_create(
            spider_name=source_key, defaults={'display_name': config.channel_name, 'enabled': False},
        )
        if not enabled and target.runs.filter(status__in=ACTIVE_RUN_STATUSES).exists():
            return error_response('target_active', '运行中的来源不能停用。', status.HTTP_409_CONFLICT)
        if enabled and not (config.probe_is_current and config.approval_is_current and config.status in {'approved', 'enabled'}):
            return error_response('approval_required', '当前配置版本尚未完成探测和审批。', status.HTTP_409_CONFLICT)
        target.enabled = enabled
        target.display_name = config.channel_name
        target.save(update_fields=['enabled', 'display_name'])
        config.status = 'enabled' if enabled else ('approved' if config.approval_is_current else 'draft')
        config.save(update_fields=['status', 'updated_at'])
        return Response(_dynamic_source_data(config, request))


class SourceConfigRunView(APIView):
    permission_classes = [IsActiveSuperuser]

    def post(self, request, source_key):
        config = SourceConfig.objects.filter(pk=source_key).first()
        if not config:
            return error_response('source_not_found', '来源配置不存在。', status.HTTP_404_NOT_FOUND)
        if not config.probe_is_current or not config.approval_is_current:
            return error_response('approval_required', '单次试运行也要求当前配置版本已探测并审批。', status.HTTP_409_CONFLICT)
        try:
            batch, active_runs = create_crawl_batch(
                trigger='manual', requested_by=request.user, spider_names=[source_key], allow_disabled=True,
            )
        except NoTargetsQueued as exc:
            return error_response('source_unavailable', str(exc), status.HTTP_409_CONFLICT)
        if batch is None:
            return Response({'code': 'already_active', 'active_runs': CrawlRunSerializer(active_runs, many=True).data})
        created = batch_queryset().get(pk=batch.pk)
        return Response(CrawlBatchSerializer(created).data, status=status.HTTP_201_CREATED)


class CrawlBatchListCreateView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(batch_queryset(), request)
        return paginator.get_paginated_response(CrawlBatchSerializer(page, many=True).data)

    def post(self, request):
        spider_names = request.data.get('spider_names')
        if spider_names is not None:
            if not isinstance(spider_names, list) or not spider_names or not all(isinstance(name, str) for name in spider_names):
                return error_response('invalid_spiders', 'spider_names 必须是非空字符串数组。')
            unknown = sorted(set(spider_names) - set(runtime_registry()))
            if unknown:
                return error_response('unknown_spider', '包含不在服务器白名单中的爬虫。', fields={'spider_names': unknown})
            spider_names = list(dict.fromkeys(spider_names))
        try:
            batch, active_runs = create_crawl_batch(
                trigger='manual',
                requested_by=request.user,
                spider_names=spider_names,
            )
        except NoTargetsQueued as exc:
            return error_response('no_enabled_targets', str(exc))
        if batch is None:
            return Response({
                'code': 'already_active',
                'message': '所选来源已有排队或运行任务。',
                'active_runs': CrawlRunSerializer(active_runs, many=True).data,
            })
        created = batch_queryset().get(pk=batch.pk)
        return Response(CrawlBatchSerializer(created).data, status=status.HTTP_201_CREATED)


class CrawlBatchDetailView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request, batch_id):
        try:
            batch = batch_queryset().get(pk=batch_id)
        except (CrawlBatch.DoesNotExist, ValueError):
            return error_response('batch_not_found', '抓取批次不存在。', status.HTTP_404_NOT_FOUND)
        return Response(CrawlBatchSerializer(batch).data)


class CrawlRunDetailView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request, run_id):
        try:
            run = CrawlRun.objects.select_related('target', 'batch').get(pk=run_id)
        except (CrawlRun.DoesNotExist, ValueError):
            return error_response('run_not_found', '抓取任务不存在。', status.HTTP_404_NOT_FOUND)
        return Response(CrawlRunSerializer(run).data)


class CrawlRunCancelView(APIView):
    permission_classes = [IsActiveSuperuser]

    def post(self, request, run_id):
        try:
            run = CrawlRun.objects.select_related('target', 'batch').get(pk=run_id)
        except (CrawlRun.DoesNotExist, ValueError):
            return error_response('run_not_found', '抓取任务不存在。', status.HTTP_404_NOT_FOUND)
        if run.status not in ACTIVE_RUN_STATUSES:
            return error_response('run_not_active', '该任务已经结束，不能再次停止。', status.HTTP_409_CONFLICT)
        run = request_run_cancel(run.pk, request.user)
        run.refresh_from_db()
        return Response(CrawlRunSerializer(run).data)


class CrawlRunRetryView(APIView):
    permission_classes = [IsActiveSuperuser]

    def post(self, request, run_id):
        try:
            run = CrawlRun.objects.select_related('target', 'batch').get(pk=run_id)
        except (CrawlRun.DoesNotExist, ValueError):
            return error_response('run_not_found', '抓取任务不存在。', status.HTTP_404_NOT_FOUND)
        if run.status not in {'failed', 'cancelled', 'skipped'}:
            return error_response('run_not_retryable', '只有失败、取消或跳过的任务可以重试。', status.HTTP_409_CONFLICT)
        try:
            batch, active_runs = create_crawl_batch(
                trigger='retry',
                requested_by=request.user,
                spider_names=[run.target_id],
                retry_of=run,
            )
        except NoTargetsQueued as exc:
            return error_response('target_disabled', str(exc), status.HTTP_409_CONFLICT)
        if batch is None:
            return Response({
                'code': 'already_active',
                'message': '该来源已有排队或运行任务。',
                'active_runs': CrawlRunSerializer(active_runs, many=True).data,
            })
        created = batch_queryset().get(pk=batch.pk)
        return Response(CrawlBatchSerializer(created).data, status=status.HTTP_201_CREATED)
