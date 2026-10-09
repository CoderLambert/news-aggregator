from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.crawler_views import IsActiveSuperuser, error_response
from api.models import SearchIndexRun
from api.search_index_serializers import (
    SearchIndexRunSerializer,
    SearchIndexSettingsSerializer,
)
from api.services.search_index import audit_search_index
from api.services.search_index_control import (
    ACTIVE_INDEX_STATUSES,
    get_search_index_settings,
    index_worker_is_online,
    queue_search_index_run,
    request_index_run_cancel,
    update_mutable_search_index_settings,
)


class SearchIndexDashboardView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        settings = get_search_index_settings()
        settings_data = SearchIndexSettingsSerializer(settings).data
        settings_data['worker_online'] = index_worker_is_online(settings)
        active_run = (
            SearchIndexRun.objects.filter(status__in=ACTIVE_INDEX_STATUSES)
            .order_by('queued_at')
            .first()
        )
        audit = audit_search_index(include_changed=True)
        recent_runs = SearchIndexRun.objects.order_by('-queued_at')[:8]
        return Response({
            'settings': settings_data,
            'audit': {
                'available': audit.available,
                'news_count': audit.news_count,
                'vector_count': audit.vector_count,
                'missing_count': audit.missing_count,
                'changed_count': audit.changed_count,
                'orphaned_count': audit.orphaned_count,
                'error_code': audit.error_code,
            },
            'active_run': SearchIndexRunSerializer(active_run).data if active_run else None,
            'recent_runs': SearchIndexRunSerializer(recent_runs, many=True).data,
            'server_time': timezone.now(),
        })


class SearchIndexSettingsView(APIView):
    permission_classes = [IsActiveSuperuser]

    def patch(self, request):
        allowed = {'enabled', 'interval_seconds', 'batch_size'}
        if set(request.data) - allowed:
            return error_response('invalid_settings', '包含不允许修改的索引设置。')
        serializer = SearchIndexSettingsSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return error_response('invalid_settings', '索引设置无效。', fields=serializer.errors)
        updated = update_mutable_search_index_settings(
            serializer.validated_data,
            updated_by=request.user,
        )
        data = SearchIndexSettingsSerializer(updated).data
        data['worker_online'] = index_worker_is_online(updated)
        return Response(data)


class SearchIndexRunListCreateView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        runs = SearchIndexRun.objects.order_by('-queued_at')[:50]
        return Response(SearchIndexRunSerializer(runs, many=True).data)

    def post(self, request):
        if set(request.data) - {'mode'}:
            return error_response('invalid_run', '只允许设置 mode。')
        mode = request.data.get('mode', 'sync')
        if mode not in {'sync', 'rebuild'}:
            return error_response('invalid_mode', 'mode 必须是 sync 或 rebuild。')
        run, created = queue_search_index_run(
            trigger='manual',
            mode=mode,
            requested_by=request.user,
        )
        if run is None:
            return error_response('run_create_failed', '无法创建索引任务。', status.HTTP_409_CONFLICT)
        payload = SearchIndexRunSerializer(run).data
        if not created:
            return Response({
                'code': 'already_active',
                'message': '已有索引任务正在排队或运行。',
                'run': payload,
            }, status=status.HTTP_409_CONFLICT)
        return Response(payload, status=status.HTTP_201_CREATED)


class SearchIndexRunDetailView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request, run_id):
        try:
            run = SearchIndexRun.objects.get(pk=run_id)
        except (SearchIndexRun.DoesNotExist, ValueError):
            return error_response('run_not_found', '索引任务不存在。', status.HTTP_404_NOT_FOUND)
        return Response(SearchIndexRunSerializer(run).data)


class SearchIndexRunCancelView(APIView):
    permission_classes = [IsActiveSuperuser]

    def post(self, request, run_id):
        try:
            run = SearchIndexRun.objects.get(pk=run_id)
        except (SearchIndexRun.DoesNotExist, ValueError):
            return error_response('run_not_found', '索引任务不存在。', status.HTTP_404_NOT_FOUND)
        if run.status not in ACTIVE_INDEX_STATUSES:
            return error_response('run_not_active', '该任务已经结束。', status.HTTP_409_CONFLICT)
        run = request_index_run_cancel(run.pk, request.user)
        return Response(SearchIndexRunSerializer(run).data)
