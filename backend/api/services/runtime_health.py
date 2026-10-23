"""Read-only runtime health snapshot for operators and the administrator UI.

The probes intentionally avoid provider/model calls, engine mutations, expensive
index audits, and raw exception details. Optional services are disabled until
their deployment configuration enables them.
"""
from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import time

from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from django.conf import settings
from django.db import connection
from django.utils import timezone

from api.models import SearchIndexSettings


CHECK_NAMES = (
    'database',
    'rss_worker',
    'rss_engine',
    'channel_worker',
    'search_index',
    'translation_redis',
    'ai_gateway',
)


def _check(*, enabled: bool, ready: bool, code: str = '') -> dict[str, object]:
    status = 'disabled' if not enabled else ('ready' if ready else 'unavailable')
    return {'enabled': enabled, 'ready': ready, 'status': status, 'code': code}


def _database_check() -> dict[str, object]:
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return _check(enabled=True, ready=False, code='query_failed')
    return _check(enabled=True, ready=True)


def _rss_checks() -> dict[str, dict[str, object]]:
    identity_values = (
        os.environ.get('RSS_ENGINE_INSTANCE_UUID', ''),
        os.environ.get('RSS_ENGINE_ACCOUNT_ID', ''),
    )
    if not any(identity_values):
        disabled = _check(enabled=False, ready=False)
        return {'rss_worker': disabled.copy(), 'rss_engine': disabled.copy()}
    if not all(identity_values):
        unavailable = _check(enabled=True, ready=False, code='invalid_configuration')
        return {'rss_worker': unavailable.copy(), 'rss_engine': unavailable.copy()}

    try:
        from api.rss.health_http import current_runtime
        from api.rss.subscriptions import engine_identity

        instance, account = engine_identity()
        runtime = current_runtime(instance, account)
    except Exception:
        invalid = _check(enabled=True, ready=False, code='invalid_configuration')
        return {'rss_worker': invalid.copy(), 'rss_engine': invalid.copy()}

    if runtime is None:
        missing = _check(enabled=True, ready=False, code='heartbeat_unavailable')
        return {'rss_worker': missing.copy(), 'rss_engine': missing.copy()}
    return {
        'rss_worker': _check(enabled=True, ready=True),
        'rss_engine': _check(
            enabled=True,
            ready=runtime['engine_ready'] is True,
            code='' if runtime['engine_ready'] is True else 'service_unreachable',
        ),
    }


def _channel_worker_check() -> dict[str, object]:
    configured_path = os.environ.get('CHANNEL_WORKER_HEARTBEAT', '')
    if not configured_path:
        return _check(enabled=False, ready=False)
    try:
        with Path(configured_path).open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError
        state = json.loads(raw)
        age = time.time() - float(state['time'])
        if (
            not isinstance(state, dict)
            or type(state.get('pid')) is not int
            or state['pid'] <= 0
            or not 0 <= age < 180
        ):
            raise ValueError
    except Exception:
        return _check(enabled=True, ready=False, code='heartbeat_unavailable')
    return _check(enabled=True, ready=True)


def _search_index_check() -> dict[str, object]:
    configured = os.environ.get('SEARCH_INDEX_ENABLED')
    environment_enabled = configured is None or configured.strip().lower() in {'1', 'true', 'yes', 'on'}
    try:
        index_settings = SearchIndexSettings.objects.filter(pk=1).first()
    except Exception:
        return _check(enabled=True, ready=False, code='query_failed')
    if index_settings is None:
        if not environment_enabled:
            return _check(enabled=False, ready=False)
        return _check(enabled=True, ready=False, code='settings_missing')
    if not index_settings.enabled:
        return _check(enabled=False, ready=False)
    heartbeat = index_settings.worker_heartbeat_at
    if heartbeat is None or heartbeat < timezone.now() - timedelta(seconds=45):
        return _check(enabled=True, ready=False, code='heartbeat_unavailable')
    return _check(enabled=True, ready=True)


def _translation_redis_check() -> dict[str, object]:
    if not getattr(settings, 'TRANSLATION_REDIS_URL', ''):
        return _check(enabled=False, ready=False)
    try:
        from api.services.translation_channel import available

        available()
    except Exception:
        return _check(enabled=True, ready=False, code='service_unreachable')
    return _check(enabled=True, ready=True)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _ai_gateway_check() -> dict[str, object]:
    if not getattr(settings, 'AI_BYOK_ENABLED', False):
        return _check(enabled=False, ready=False)
    try:
        from api.services.ai_gateway import _gateway_configuration

        base_url, _project_key = _gateway_configuration()
        request = Request(f'{base_url}/health/readiness', headers={'Accept': 'application/json'}, method='GET')
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=2) as response:
            if response.status != 200:
                raise ValueError
    except Exception:
        return _check(enabled=True, ready=False, code='service_unreachable')
    return _check(enabled=True, ready=True)


def runtime_health_snapshot() -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {'database': _database_check()}
    checks.update(_rss_checks())
    checks['channel_worker'] = _channel_worker_check()
    checks['search_index'] = _search_index_check()
    checks['translation_redis'] = _translation_redis_check()
    checks['ai_gateway'] = _ai_gateway_check()
    ready = all(check['ready'] is True for check in checks.values() if check['enabled'] is True)
    return {
        'schema_version': 1,
        'status': 'ready' if ready else 'unavailable',
        'ready': ready,
        'checked_at': timezone.now().isoformat(),
        'checks': checks,
    }
