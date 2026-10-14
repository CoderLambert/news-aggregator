"""Intake review endpoints, isolated from crawler enablement and model calls."""
from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from api.models import Source
from api.smart_channel_models import ChannelIntakeRequest
from api.smart_channel_views import PrivateWorkspaceView, SiteClassifierView
from api.services.channel_grouping import lock_user
from api.services.channel_topics import profile_data
from api.services.channel_intake import normalize_intake_url, intake_data, review_intake


class IntakeView(PrivateWorkspaceView):
    authentication_classes = [SessionAuthentication]

    def get(self, request):
        rows = ChannelIntakeRequest.objects.filter(user=request.user).order_by('-created_at', '-id')[:30]
        return Response([intake_data(item) for item in rows])

    @transaction.atomic
    def post(self, request):
        lock_user(request.user)
        url = normalize_intake_url(request.data.get('url'))[0]
        previous = ChannelIntakeRequest.objects.filter(user=request.user, url=url).first()
        if previous:
            return Response(intake_data(previous))
        if ChannelIntakeRequest.objects.filter(user=request.user, created_at__date=timezone.localdate()).count() >= 10:
            raise Throttled(3600, '已达到今日接入申请上限。')
        item = ChannelIntakeRequest.objects.create(user=request.user, url=url)
        return Response(intake_data(item), status=201)


class ResolveChannelView(PrivateWorkspaceView):
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        value, host, path, query = normalize_intake_url(request.data.get('url'))
        exact, publisher = [], []
        for source in Source.objects.all():
            data = profile_data(source)
            for address in (source.url, data['feed_url']):
                if not address:
                    continue
                try:
                    _, candidate_host, candidate_path, candidate_query = normalize_intake_url(address)
                except ValidationError:
                    continue
                if candidate_host == host:
                    publisher.append(data)
                    if candidate_path == path and candidate_query == query:
                        exact.append(data)
        matches = exact or (publisher if not path and not query else [])
        unique = {item['id']: item for item in matches}
        return Response({'matches': list(unique.values()), 'supported': bool(unique), 'url': value,
            'message': '请选择要订阅的已登记频道。' if unique else '尚未登记，可提交接入申请；审核不会自动开启抓取。'})


class AdminIntakeView(PrivateWorkspaceView):
    authentication_classes = [SessionAuthentication]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied()

    def get(self, request):
        rows = ChannelIntakeRequest.objects.order_by('-created_at', '-id')
        status = request.query_params.get('status', '')
        if status:
            if status not in {'pending', 'approved', 'rejected'}:
                raise ValidationError('无效审核状态。')
            rows = rows.filter(status=status)
        pagination = PageNumberPagination()
        pagination.page_size = 20
        page = pagination.paginate_queryset(rows, request, view=self)
        return pagination.get_paginated_response([intake_data(item) for item in page])


class ReviewIntakeView(AdminIntakeView):
    def patch(self, request, pk):
        return Response(intake_data(review_intake(request.user, pk, request.data)))

    def get(self, request, pk):
        from django.shortcuts import get_object_or_404
        return Response(intake_data(get_object_or_404(ChannelIntakeRequest, pk=pk)))


class SafeSiteClassifierView(SiteClassifierView):
    def get(self, request):
        response = super().get(request)
        rows = ChannelIntakeRequest.objects.order_by('-created_at', '-id')[:30]
        response.data['intake_requests'] = [intake_data(item) for item in rows]
        return response
