"""Removal responses for bookmarked legacy collector administration URLs."""
from rest_framework.response import Response
from rest_framework.views import APIView
from api.admin_api import IsActiveSuperuser


class RetiredIngestionAdminView(APIView):
    permission_classes = [IsActiveSuperuser]

    def _gone(self, request, *args, **kwargs):
        return Response({
            'error_code': 'legacy_ingestion_retired',
            'error': '旧采集管理已停用，请使用 RSS 管理。',
        }, status=410)

    get = post = patch = put = delete = _gone
