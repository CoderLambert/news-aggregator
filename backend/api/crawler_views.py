from django.db.models import Case, IntegerField, Prefetch, Value, When
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
)
from api.management.commands.crawl import SPIDERS
from api.models import CrawlBatch, CrawlRun, CrawlerTarget
from api.services.crawler_control import (
    ACTIVE_RUN_STATUSES,
    NoTargetsQueued,
    create_crawl_batch,
    get_crawler_settings,
    request_run_cancel,
    sync_crawler_targets,
    worker_is_online,
)


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
    return CrawlerTarget.objects.prefetch_related(
        Prefetch('runs', queryset=active_runs, to_attr='prefetched_active_runs'),
    ).order_by('sort_order', 'spider_name')


def batch_queryset():
    runs = CrawlRun.objects.select_related('target').prefetch_related(
        Prefetch(
            'retries',
            queryset=CrawlRun.objects.only('id', 'status', 'retry_of_id', 'queued_at').order_by('-queued_at'),
            to_attr='prefetched_retries',
        ),
    ).order_by('queued_at')
    return CrawlBatch.objects.prefetch_related(
        Prefetch('runs', queryset=runs),
    ).order_by('-queued_at')


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
        if spider_name not in SPIDERS:
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
            unknown = sorted(set(spider_names) - set(SPIDERS))
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
