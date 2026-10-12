"""Minimal HTTP probes that do not invoke application services or providers."""

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def health_live(_request):
    """Report process responsiveness without consulting external dependencies."""
    return JsonResponse({"status": "ok"})


@require_safe
def health_ready(_request):
    """Check only that the configured database can execute a trivial query."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
