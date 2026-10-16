"""Administrative stored synchronization health, with a bounded local heartbeat."""
import json
import os
from pathlib import Path
import time
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from api.rss.http import RssAPIView
from api.rss.models import FeedBinding
from api.rss.subscriptions import engine_identity


def current_runtime(instance, account):
    path = Path(os.environ.get('RSS_RUNTIME_DIR', '/var/lib/newshub/rss-runtime')) / 'heartbeat.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            return None
        state = json.loads(raw)
        if (not isinstance(state, dict) or state.get('engine_instance_uuid') != str(instance) or state.get('account_id') != account
                or state.get('mode') != 'sync_worker' or not 0 <= time.time() - state['timestamp'] <= 60):
            return None
        return {'engine_ready': state.get('engine_ready') is True, 'error_class': state.get('error_class')}
    except (OSError, ValueError, TypeError, KeyError):
        return None


class RssHealthView(RssAPIView):
    def get(self, request):
        if not request.user.is_staff:
            raise PermissionDenied('需要管理权限。')
        from api.rss.reconciliation import health_snapshot
        instance, account = engine_identity()
        health = health_snapshot(instance, account, current_runtime(instance, account))
        health['connections'] = list(FeedBinding.objects.filter(engine_instance_uuid=instance, account_id=account)
            .order_by('canonical_feed_url').values('id', 'canonical_feed_url', 'connection_state', 'desired_mode', 'desired_enabled')[:500])
        return Response(health)
