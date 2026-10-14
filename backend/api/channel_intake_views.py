"""Owner history and administrator review of inert channel applications."""
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from api.smart_channel_models import ChannelIntakeRequest
from api.smart_channel_views import PrivateWorkspaceView
from api.services.channel_intake import intake_data, review_intake


class IntakeHistoryView(PrivateWorkspaceView):
    admin_only = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.admin_only and (not request.user.is_active or not request.user.is_superuser):
            raise PermissionDenied()

    def get(self, request):
        rows = ChannelIntakeRequest.objects.all()
        if not self.admin_only:
            rows = rows.filter(user=request.user)
        status = request.query_params.get('status', '')
        if status not in {'', 'pending', 'approved', 'rejected'}:
            raise ValidationError('无效的申请状态。')
        if status:
            rows = rows.filter(status=status)
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(rows.order_by('-created_at', '-pk'), request, view=self)
        return paginator.get_paginated_response([intake_data(row) for row in page])


class AdminIntakeHistoryView(IntakeHistoryView):
    admin_only = True


class IntakeReviewView(PrivateWorkspaceView):
    def post(self, request, pk):
        result = review_intake(request.user, pk, request.data.get('decision'), request.data.get('reason'))
        return Response(intake_data(result))
