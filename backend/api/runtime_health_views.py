"""Active-superuser runtime health endpoint with no operational mutations."""
from rest_framework.response import Response
from rest_framework.views import APIView

from api.admin_api import IsActiveSuperuser
from api.services.runtime_health import runtime_health_snapshot


class RuntimeHealthView(APIView):
    permission_classes = [IsActiveSuperuser]

    def get(self, request):
        response = Response(runtime_health_snapshot())
        response['Cache-Control'] = 'private, no-store'
        return response
