import json
import os
from pathlib import Path

import pytest

from scripts.deploy import local_full_runtime


def test_secret_store_creates_private_values_once_and_rejects_symlinks(tmp_path):
    root = tmp_path / 'runtime'
    store = local_full_runtime.SecretStore(root)

    first = store.ensure('project-key', lambda: 'sk-first-value')
    second = store.ensure('project-key', lambda: 'sk-rotated-value')

    assert first.read_text() == 'sk-first-value\n'
    assert second.read_text() == 'sk-first-value\n'
    assert root.stat().st_mode & 0o777 == 0o700
    assert first.stat().st_mode & 0o777 == 0o600

    unsafe = root / 'unsafe'
    unsafe.symlink_to(first)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='regular private file'):
        store.ensure('unsafe', lambda: 'unused')


def test_full_health_rejects_disabled_missing_or_unavailable_checks():
    ready = {
        'schema_version': 1,
        'ready': True,
        'checks': {
            name: {'enabled': True, 'ready': True, 'status': 'ready', 'code': ''}
            for name in local_full_runtime.REQUIRED_HEALTH_CHECKS
        },
    }
    assert local_full_runtime.require_full_health(ready) == ready

    for name, replacement in (
        ('rss_worker', {'enabled': False, 'ready': False, 'status': 'disabled', 'code': ''}),
        ('ai_gateway', {'enabled': True, 'ready': False, 'status': 'unavailable', 'code': 'service_unreachable'}),
    ):
        broken = json.loads(json.dumps(ready))
        broken['checks'][name] = replacement
        with pytest.raises(local_full_runtime.LocalRuntimeError, match=name):
            local_full_runtime.require_full_health(broken)

    missing = json.loads(json.dumps(ready))
    del missing['checks']['translation_redis']
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='translation_redis'):
        local_full_runtime.require_full_health(missing)


def test_activation_commands_start_every_service_and_restore_previous_runtime():
    plan = local_full_runtime.activation_commands(
        project='newshub-local-main',
        compose_files=(Path('/repo/compose.yaml'), Path('/repo/compose.local-full.yaml')),
        previous_compose=(Path('/repo/compose.yaml'), Path('/state/previous.yaml')),
        wait_timeout=300,
    )

    assert plan.infrastructure[-7:] == [
        'app', 'indexer', 'translation-redis', 'rss-db', 'miniflux',
        'ai-gateway-db', 'ai-gateway',
    ]
    assert '--pull' in plan.infrastructure and plan.infrastructure[plan.infrastructure.index('--pull') + 1] == 'never'
    assert plan.full[-9:] == [
        'app', 'indexer', 'translation-redis', 'rss-db', 'miniflux',
        'ai-gateway-db', 'ai-gateway', 'rss-sync', 'channel-worker',
    ]
    assert plan.verify[-3:] == ['python', '/app/backend/manage.py', 'runtime_health']
    assert plan.rollback[-2:] == ['app', 'indexer']
    assert '/state/previous.yaml' in plan.rollback
    assert all(name not in plan.rollback for name in ('rss-sync', 'channel-worker', 'ai-gateway'))


def test_dry_run_does_not_create_runtime_state(tmp_path, capsys):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'compose.yaml').write_text('services: {}\n')
    runtime = tmp_path / 'runtime'

    result = local_full_runtime.main([
        '--project', 'newshub-local-main',
        '--source-root', str(source),
        '--runtime-root', str(runtime),
        '--image', 'newshub:dev-' + 'a' * 40,
    ])

    assert result == 0
    assert not runtime.exists()
    output = json.loads(capsys.readouterr().out)
    assert output['execute'] is False
    assert output['required_services'] == list(local_full_runtime.REQUIRED_SERVICES)
    assert 'secret' not in json.dumps(output).lower()


@pytest.mark.parametrize('image', ['newshub:latest', 'newshub:dev-short', 'newshub:dev-' + 'A' * 40])
def test_preview_rejects_mutable_or_unbound_application_images(tmp_path, image):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'compose.yaml').write_text('services: {}\n')

    with pytest.raises(local_full_runtime.LocalRuntimeError, match='immutable'):
        local_full_runtime.main([
            '--project', 'newshub-local-main', '--source-root', str(source),
            '--runtime-root', str(tmp_path / 'runtime'), '--image', image,
        ])


def test_ai_bootstrap_grants_inference_and_discovery_once(tmp_path, monkeypatch):
    store = local_full_runtime.SecretStore(tmp_path / 'secrets')
    store.ensure('ai-project-key', lambda: local_full_runtime.PENDING)
    store.ensure('litellm-master-key', lambda: 'sk-' + 'm' * 32)
    requests = []

    def request(url, **kwargs):
        requests.append((url, kwargs))
        return {'key': 'sk-' + 'p' * 32}

    monkeypatch.setattr(local_full_runtime, '_request_json', request)
    local_full_runtime._bootstrap_ai_gateway(store)

    assert store.read('ai-project-key') == 'sk-' + 'p' * 32
    assert len(requests) == 1 and requests[0][0].endswith('/key/generate')
    payload = requests[0][1]['payload']
    assert payload['allowed_routes'] == ['llm_api_routes', '/newshub/models/discover']
    assert payload['models'] == list(local_full_runtime.MODEL_ALLOWLIST)


def test_activation_failure_stops_new_services_and_restores_previous_compose(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for directory in ('backend', 'chroma_data', 'logs'):
        (source / directory).mkdir(parents=True, exist_ok=True)
    previous = (Path('/previous/compose.yaml'), Path('/previous/runtime.yaml'))
    candidate = 'newshub:dev-' + 'a' * 40
    calls = []

    monkeypatch.setattr(local_full_runtime, '_local_docker', lambda: None)
    monkeypatch.setattr(local_full_runtime, '_previous_runtime',
                        lambda _project: (previous, candidate, source))
    monkeypatch.setattr(local_full_runtime, '_backup_sqlite', lambda *_args: None)
    monkeypatch.setattr(local_full_runtime, '_bootstrap_miniflux', lambda *_args: 2)
    monkeypatch.setattr(local_full_runtime, '_bootstrap_ai_gateway', lambda *_args: None)

    def command(arguments, **_kwargs):
        calls.append(arguments)
        if arguments[:3] == ['docker', 'image', 'inspect']:
            return type('Result', (), {'stdout': '[]', 'returncode': 0})()
        if arguments[-2:] == ['config', '--images']:
            return type('Result', (), {'stdout': candidate + '\n', 'returncode': 0})()
        if 'up' in arguments and arguments[-2:] == ['rss-sync', 'channel-worker']:
            raise local_full_runtime.LocalRuntimeError('synthetic full activation failure')
        return type('Result', (), {'stdout': '', 'returncode': 0})()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='synthetic'):
        local_full_runtime._execute(
            project='newshub-local-main', source_root=source,
            runtime_root=tmp_path / 'runtime', image=candidate, wait_timeout=300,
            complete_overlay=Path('/candidate/compose.local-full.yaml'),
        )

    assert any('stop' in call and 'ai-gateway' in call for call in calls)
    rollback = [call for call in calls if '/previous/runtime.yaml' in call and call[-2:] == ['app', 'indexer']]
    assert len(rollback) == 1


def test_partial_infrastructure_failure_also_restores_previous_compose(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for directory in ('backend', 'chroma_data', 'logs'):
        (source / directory).mkdir(parents=True, exist_ok=True)
    previous = (Path('/previous/compose.yaml'), Path('/previous/runtime.yaml'))
    candidate = 'newshub:dev-' + 'b' * 40
    calls = []

    monkeypatch.setattr(local_full_runtime, '_local_docker', lambda: None)
    monkeypatch.setattr(local_full_runtime, '_previous_runtime',
                        lambda _project: (previous, candidate, source))
    monkeypatch.setattr(local_full_runtime, '_backup_sqlite', lambda *_args: None)

    def command(arguments, **_kwargs):
        calls.append(arguments)
        if arguments[:3] == ['docker', 'image', 'inspect']:
            return type('Result', (), {'stdout': '[]', 'returncode': 0})()
        if arguments[-2:] == ['config', '--images']:
            return type('Result', (), {'stdout': candidate + '\n', 'returncode': 0})()
        if 'up' in arguments and arguments[-2:] == ['ai-gateway-db', 'ai-gateway']:
            raise local_full_runtime.LocalRuntimeError('synthetic partial infrastructure failure')
        return type('Result', (), {'stdout': '', 'returncode': 0})()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='partial infrastructure'):
        local_full_runtime._execute(
            project='newshub-local-main', source_root=source,
            runtime_root=tmp_path / 'runtime', image=candidate, wait_timeout=300,
            complete_overlay=Path('/candidate/compose.local-full.yaml'),
        )

    assert any('stop' in call and 'ai-gateway' in call for call in calls)
    assert len([call for call in calls
                if '/previous/runtime.yaml' in call and call[-2:] == ['app', 'indexer']]) == 1
