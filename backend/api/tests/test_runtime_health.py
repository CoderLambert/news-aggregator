from __future__ import annotations

from io import StringIO
import json
import time
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework.test import APIClient

from api.models import SearchIndexSettings
from api.services import runtime_health


READY_SNAPSHOT = {
    'schema_version': 1,
    'status': 'ready',
    'ready': True,
    'checked_at': '2026-10-24T10:00:00+00:00',
    'checks': {
        name: {'enabled': True, 'ready': True, 'status': 'ready', 'code': ''}
        for name in runtime_health.CHECK_NAMES
    },
}


@pytest.mark.django_db
def test_runtime_health_endpoint_is_active_superuser_only_and_not_cached(django_user_model, monkeypatch):
    snapshot = Mock(return_value=READY_SNAPSHOT)
    monkeypatch.setattr('api.runtime_health_views.runtime_health_snapshot', snapshot)
    client = APIClient()

    assert client.get(reverse('runtime-health')).status_code == 403
    for user in (
        django_user_model.objects.create_user('ordinary'),
        django_user_model.objects.create_user('reviewer', is_staff=True),
        django_user_model.objects.create_user('inactive-admin', is_staff=True, is_superuser=True, is_active=False),
    ):
        client.force_authenticate(user)
        assert client.get(reverse('runtime-health')).status_code == 403
    snapshot.assert_not_called()

    admin = django_user_model.objects.create_user('active-admin', is_staff=True, is_superuser=True)
    client.force_authenticate(admin)
    response = client.get(reverse('runtime-health'))
    assert response.status_code == 200
    assert response.json() == READY_SNAPSHOT
    assert response.headers['Cache-Control'] == 'private, no-store'
    snapshot.assert_called_once_with()


@pytest.mark.django_db
def test_missing_search_index_settings_is_reported_without_creating_a_row(monkeypatch):
    monkeypatch.setenv('SEARCH_INDEX_ENABLED', '1')
    SearchIndexSettings.objects.all().delete()

    result = runtime_health._search_index_check()

    assert result == {
        'enabled': True,
        'ready': False,
        'status': 'unavailable',
        'code': 'settings_missing',
    }
    assert not SearchIndexSettings.objects.exists()


def test_channel_worker_uses_bounded_shared_heartbeat_without_cross_namespace_pid_check(tmp_path, monkeypatch):
    heartbeat = tmp_path / 'channel.json'
    heartbeat.write_text(json.dumps({'pid': 999999, 'time': time.time()}), encoding='utf-8')
    monkeypatch.setenv('CHANNEL_WORKER_HEARTBEAT', str(heartbeat))
    monkeypatch.setattr(runtime_health.os, 'kill', Mock(side_effect=AssertionError('must not inspect another PID namespace')))

    assert runtime_health._channel_worker_check()['status'] == 'ready'


def test_gateway_probe_is_loopback_readiness_only_without_credentials(monkeypatch, settings):
    settings.AI_BYOK_ENABLED = True
    observed = {}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None

    class Opener:
        def open(self, request, timeout):
            observed.update(url=request.full_url, headers=dict(request.header_items()), timeout=timeout)
            return Response()

    monkeypatch.setattr('api.services.ai_gateway._gateway_configuration', lambda: ('http://127.0.0.1:4000', 'secret-marker'))
    monkeypatch.setattr(runtime_health, 'build_opener', lambda *_handlers: Opener())

    assert runtime_health._ai_gateway_check()['status'] == 'ready'
    assert observed['url'] == 'http://127.0.0.1:4000/health/readiness'
    assert observed['timeout'] == 2
    assert all(name.lower() != 'authorization' for name in observed['headers'])
    assert 'secret-marker' not in json.dumps(observed)


def test_snapshot_ignores_disabled_components_but_fails_enabled_unavailable(monkeypatch):
    ready = {'enabled': True, 'ready': True, 'status': 'ready', 'code': ''}
    disabled = {'enabled': False, 'ready': False, 'status': 'disabled', 'code': ''}
    unavailable = {'enabled': True, 'ready': False, 'status': 'unavailable', 'code': 'service_unreachable'}
    monkeypatch.setattr(runtime_health, '_database_check', lambda: ready.copy())
    monkeypatch.setattr(runtime_health, '_rss_checks', lambda: {'rss_worker': disabled.copy(), 'rss_engine': disabled.copy()})
    monkeypatch.setattr(runtime_health, '_channel_worker_check', lambda: disabled.copy())
    monkeypatch.setattr(runtime_health, '_search_index_check', lambda: ready.copy())
    monkeypatch.setattr(runtime_health, '_translation_redis_check', lambda: disabled.copy())
    monkeypatch.setattr(runtime_health, '_ai_gateway_check', lambda: disabled.copy())

    assert runtime_health.runtime_health_snapshot()['ready'] is True
    monkeypatch.setattr(runtime_health, '_ai_gateway_check', lambda: unavailable.copy())
    snapshot = runtime_health.runtime_health_snapshot()
    assert snapshot['ready'] is False
    assert snapshot['status'] == 'unavailable'


def test_runtime_health_command_prints_same_json_and_exits_nonzero_when_unavailable(monkeypatch):
    output = StringIO()
    monkeypatch.setattr('api.management.commands.runtime_health.runtime_health_snapshot', lambda: READY_SNAPSHOT)
    call_command('runtime_health', stdout=output)
    assert json.loads(output.getvalue()) == READY_SNAPSHOT

    unavailable = {**READY_SNAPSHOT, 'ready': False, 'status': 'unavailable'}
    output = StringIO()
    monkeypatch.setattr('api.management.commands.runtime_health.runtime_health_snapshot', lambda: unavailable)
    with pytest.raises(CommandError, match='configured runtime services'):
        call_command('runtime_health', stdout=output)
    assert json.loads(output.getvalue()) == unavailable
