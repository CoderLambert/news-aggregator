import json
import os
from pathlib import Path

import pytest

from scripts.deploy import local_full_runtime
from scripts.deploy import ai_gateway_bootstrap


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
        current_env_file=Path('/state/candidate.env'),
        previous_env_file=Path('/state/previous.env'),
        previous_services=local_full_runtime.REQUIRED_SERVICES,
        project_directory=Path('/repo'),
        wait_timeout=300,
    )

    assert plan.infrastructure[-7:] == [
        'app', 'indexer', 'translation-redis', 'rss-db', 'miniflux',
        'ai-gateway-db', 'ai-gateway',
    ]
    assert plan.quiesce[-4:] == ['stop', 'miniflux', 'rss-sync', 'channel-worker']
    assert plan.preflight[-9:] == list(local_full_runtime.REQUIRED_SERVICES)
    assert '--pull' in plan.infrastructure and plan.infrastructure[plan.infrastructure.index('--pull') + 1] == 'never'
    assert plan.full[-9:] == [
        'app', 'indexer', 'translation-redis', 'rss-db', 'miniflux',
        'ai-gateway-db', 'ai-gateway', 'rss-sync', 'channel-worker',
    ]
    assert '--force-recreate' in plan.full
    assert plan.verify[-3:] == ['python', '/app/backend/manage.py', 'runtime_health']
    assert plan.rollback[-9:] == list(local_full_runtime.REQUIRED_SERVICES)
    assert '/state/previous.yaml' in plan.rollback
    assert plan.rollback[plan.rollback.index('--env-file') + 1] == '/state/previous.env'


def test_first_minimal_runtime_needs_no_business_io_quiesce():
    plan = local_full_runtime.activation_commands(
        project='newshub-local-main', compose_files=(Path('/repo/compose.yaml'),),
        previous_compose=(Path('/repo/compose.yaml'),),
        current_env_file=Path('/state/candidate.env'), previous_env_file=None,
        previous_services=('app', 'indexer'), project_directory=Path('/repo'),
        wait_timeout=300,
    )
    assert plan.quiesce is None


def test_rollback_stops_candidate_indexer_when_it_was_not_previously_running():
    plan = local_full_runtime.activation_commands(
        project='newshub-local-main', compose_files=(Path('/repo/compose.yaml'),),
        previous_compose=(Path('/previous/compose.yaml'),),
        current_env_file=Path('/state/candidate.env'), previous_env_file=None,
        previous_services=('app',), wait_timeout=300,
        project_directory=Path('/repo'),
    )
    assert plan.stop_new[-9:] == list(reversed(local_full_runtime.REQUIRED_SERVICES))
    assert plan.rollback[-1:] == ['app']


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


def test_ai_bootstrap_runs_inside_gateway_namespace_and_replaces_key(tmp_path, monkeypatch):
    store = local_full_runtime.SecretStore(tmp_path / 'secrets')
    store.ensure('ai-project-key', lambda: local_full_runtime.PENDING)
    calls = []

    def command(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return type('Result', (), {
            'stdout': json.dumps({'status': 'created', 'key': 'sk-' + 'p' * 32}),
            'returncode': 0,
        })()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    local_full_runtime._bootstrap_ai_gateway(
        store, ['docker', 'compose', '-p', 'newshub-local-main'], environment={},
    )

    assert store.read('ai-project-key') == 'sk-' + 'p' * 32
    assert len(calls) == 1
    command = calls[0][0]
    assert command[-5:] == ['exec', '-T', 'ai-gateway', 'python', '/app/local-bootstrap.py']
    assert '127.0.0.1:4000' not in json.dumps(calls[0][1])


def test_gateway_namespace_helper_grants_inference_and_discovery(monkeypatch, capsys):
    requests = []
    monkeypatch.setattr(ai_gateway_bootstrap, 'read_secret',
                        lambda path: local_full_runtime.PENDING if path.endswith('project_key') else 'sk-master')

    def request(path, **kwargs):
        requests.append((path, kwargs))
        return {'key': 'sk-' + 'p' * 32}

    monkeypatch.setattr(ai_gateway_bootstrap, 'request_json', request)
    ai_gateway_bootstrap.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'created'
    payload = requests[0][1]['payload']
    assert payload['allowed_routes'] == ['llm_api_routes', '/newshub/models/discover']
    assert payload['models'] == list(ai_gateway_bootstrap.MODELS)


def test_previous_complete_activation_restores_versioned_env_and_all_services(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    base = tmp_path / 'base.yaml'
    overlay = tmp_path / 'previous.yaml'
    env_file = tmp_path / 'previous.env'
    for path in (base, overlay, env_file):
        path.write_text('x\n')
        path.chmod(0o600)
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    receipt = {
        'schema_version': 3, 'project': 'newshub-local-main',
        'source_root': str(source), 'image': 'newshub:dev-' + 'a' * 40,
        'compose_files': [str(base), str(overlay)],
        'base_compose_files': [str(base)], 'base_source_files': [str(base)],
        'env_file': str(env_file),
        'services': list(local_full_runtime.REQUIRED_SERVICES),
    }
    path = runtime / 'last-activation.json'
    path.write_text(json.dumps(receipt))
    path.chmod(0o600)

    previous, previous_env, services, base_files = local_full_runtime._previous_activation(
        runtime, project='newshub-local-main', source_root=source,
        image=receipt['image'], detected_compose=(base, overlay),
        detected_services=local_full_runtime.REQUIRED_SERVICES,
    )

    assert previous == (base, overlay)
    assert previous_env == env_file
    assert services == local_full_runtime.REQUIRED_SERVICES
    assert base_files == (base,)


def test_frozen_base_compose_is_unchanged_when_source_is_edited(tmp_path):
    source = tmp_path / 'compose.yaml'
    source.write_text('services:\n  app:\n    ports: ["127.0.0.1:9527:9527"]\n')
    releases = tmp_path / 'releases'
    releases.mkdir(mode=0o700)

    frozen = local_full_runtime._freeze_compose_files((source,), releases, 'candidate')
    source.write_text('services:\n  app:\n    ports: ["127.0.0.1:9999:9527"]\n')

    assert '9527:9527' in frozen[0].read_text()
    assert '9999:9527' not in frozen[0].read_text()


def test_failed_rollback_is_reported_separately(monkeypatch):
    commands = local_full_runtime.ActivationCommands(
        quiesce=['quiesce'], infrastructure=['infra'], preflight=['preflight'], full=['full'], verify=['verify'],
        stop_new=['stop'], rollback=['rollback'],
    )
    calls = []

    def command(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return type('Result', (), {'returncode': 1 if arguments == ['rollback'] else 0,
                                   'stdout': ''})()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='restoration is incomplete'):
        local_full_runtime._restore_previous_runtime(
            commands, current_environment={'CURRENT': '1'},
            rollback_environment={'PREVIOUS': '1'}, wait_timeout=300,
        )
    assert calls[1][1]['environment'] == {'PREVIOUS': '1'}


@pytest.mark.parametrize('stop_result', ['nonzero', 'exception'])
def test_failed_candidate_stop_still_attempts_rollback_and_reports_incomplete(monkeypatch, stop_result):
    commands = local_full_runtime.ActivationCommands(
        quiesce=['quiesce'], infrastructure=['infra'], preflight=['preflight'],
        full=['full'], verify=['verify'], stop_new=['stop'], rollback=['rollback'],
    )
    calls = []

    def command(arguments, **kwargs):
        calls.append(arguments)
        if arguments == ['stop']:
            if stop_result == 'exception':
                raise local_full_runtime.LocalRuntimeError('synthetic stop timeout')
            return type('Result', (), {'returncode': 1, 'stdout': ''})()
        return type('Result', (), {'returncode': 0, 'stdout': ''})()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='restoration is incomplete'):
        local_full_runtime._restore_previous_runtime(
            commands, current_environment={}, rollback_environment={}, wait_timeout=300,
        )
    assert calls[-1] == ['rollback']


def test_activation_failure_stops_new_services_and_restores_previous_compose(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for directory in ('backend', 'chroma_data', 'logs'):
        (source / directory).mkdir(parents=True, exist_ok=True)
    previous = (source / 'compose.yaml', source / 'runtime.yaml')
    for path in previous:
        path.write_text('services: {}\n')
    candidate = 'newshub:dev-' + 'a' * 40
    calls = []
    overlay = tmp_path / 'compose.local-full.yaml'
    overlay.write_text('services: {}\n')

    monkeypatch.setattr(local_full_runtime, '_local_docker', lambda: None)
    monkeypatch.setattr(local_full_runtime, '_previous_runtime',
                        lambda _project: (previous, candidate, source))
    monkeypatch.setattr(local_full_runtime, '_running_services',
                        lambda _project: ('app', 'indexer'))
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
            complete_overlay=overlay,
        )

    assert any('stop' in call and 'ai-gateway' in call for call in calls)
    rollback = [call for call in calls if str(previous[1]) in call and call[-2:] == ['app', 'indexer']]
    assert len(rollback) == 1


def test_partial_infrastructure_failure_also_restores_previous_compose(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for directory in ('backend', 'chroma_data', 'logs'):
        (source / directory).mkdir(parents=True, exist_ok=True)
    previous = (source / 'compose.yaml', source / 'runtime.yaml')
    for path in previous:
        path.write_text('services: {}\n')
    candidate = 'newshub:dev-' + 'b' * 40
    calls = []
    overlay = tmp_path / 'compose.local-full.yaml'
    overlay.write_text('services: {}\n')

    monkeypatch.setattr(local_full_runtime, '_local_docker', lambda: None)
    monkeypatch.setattr(local_full_runtime, '_previous_runtime',
                        lambda _project: (previous, candidate, source))
    monkeypatch.setattr(local_full_runtime, '_running_services',
                        lambda _project: ('app', 'indexer'))
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
            complete_overlay=overlay,
        )

    assert any('stop' in call and 'ai-gateway' in call for call in calls)
    assert len([call for call in calls
                if str(previous[1]) in call and call[-2:] == ['app', 'indexer']]) == 1


def test_repeat_activation_quiesces_old_business_services_before_infrastructure(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for directory in ('backend', 'chroma_data', 'logs'):
        (source / directory).mkdir(parents=True, exist_ok=True)
    base = tmp_path / 'base.yaml'
    previous_overlay = tmp_path / 'previous.yaml'
    previous_env = tmp_path / 'previous.env'
    candidate_overlay = tmp_path / 'candidate.yaml'
    for path in (base, previous_overlay, previous_env, candidate_overlay):
        path.write_text('services: {}\n')
        path.chmod(0o600)
    candidate = 'newshub:dev-' + 'c' * 40
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    receipt = {
        'schema_version': 3, 'project': 'newshub-local-main',
        'source_root': str(source), 'image': candidate,
        'compose_files': [str(base), str(previous_overlay)],
        'base_compose_files': [str(base)], 'base_source_files': [str(base)],
        'env_file': str(previous_env),
        'services': list(local_full_runtime.REQUIRED_SERVICES),
    }
    receipt_path = runtime / 'last-activation.json'
    receipt_path.write_text(json.dumps(receipt))
    receipt_path.chmod(0o600)
    calls = []

    monkeypatch.setattr(local_full_runtime, '_local_docker', lambda: None)
    monkeypatch.setattr(local_full_runtime, '_previous_runtime',
                        lambda _project: ((base, previous_overlay), candidate, source))
    monkeypatch.setattr(local_full_runtime, '_running_services',
                        lambda _project: local_full_runtime.REQUIRED_SERVICES)
    monkeypatch.setattr(local_full_runtime, '_backup_sqlite', lambda *_args: None)

    def command(arguments, **_kwargs):
        calls.append(arguments)
        if arguments[:3] == ['docker', 'image', 'inspect']:
            return type('Result', (), {'stdout': '[]', 'returncode': 0})()
        if arguments[-2:] == ['config', '--images']:
            return type('Result', (), {'stdout': candidate + '\n', 'returncode': 0})()
        if 'up' in arguments and arguments[-7:] == list(local_full_runtime.INFRASTRUCTURE_SERVICES):
            raise local_full_runtime.LocalRuntimeError('synthetic infrastructure failure')
        return type('Result', (), {'stdout': '', 'returncode': 0})()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='infrastructure'):
        local_full_runtime._execute(
            project='newshub-local-main', source_root=source, runtime_root=runtime,
            image=candidate, wait_timeout=300, complete_overlay=candidate_overlay,
        )

    quiesce_index = next(index for index, call in enumerate(calls)
                          if call[-4:] == ['stop', 'miniflux', 'rss-sync', 'channel-worker'])
    infrastructure_index = next(index for index, call in enumerate(calls)
                                if 'up' in call and call[-7:] == list(local_full_runtime.INFRASTRUCTURE_SERVICES))
    assert quiesce_index < infrastructure_index


def test_receipt_publish_failure_rolls_back_and_stops_all_candidate_services(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for directory in ('backend', 'chroma_data', 'logs'):
        (source / directory).mkdir(parents=True, exist_ok=True)
    base = source / 'compose.yaml'
    base.write_text('services: {}\n')
    overlay = tmp_path / 'candidate.yaml'
    overlay.write_text('services: {}\n')
    candidate = 'newshub:dev-' + 'd' * 40
    calls = []
    ready = {
        'schema_version': 1, 'ready': True,
        'checks': {name: {'enabled': True, 'ready': True, 'status': 'ready', 'code': ''}
                   for name in local_full_runtime.REQUIRED_HEALTH_CHECKS},
    }

    monkeypatch.setattr(local_full_runtime, '_local_docker', lambda: None)
    monkeypatch.setattr(local_full_runtime, '_previous_runtime',
                        lambda _project: ((base,), candidate, source))
    monkeypatch.setattr(local_full_runtime, '_running_services', lambda _project: ('app',))
    monkeypatch.setattr(local_full_runtime, '_backup_sqlite', lambda *_args: None)
    monkeypatch.setattr(local_full_runtime, '_bootstrap_miniflux', lambda *_args: 2)
    monkeypatch.setattr(local_full_runtime, '_bootstrap_ai_gateway', lambda *_args: None)
    monkeypatch.setattr(local_full_runtime, '_write_receipt',
                        lambda *_args: (_ for _ in ()).throw(
                            local_full_runtime.LocalRuntimeError('synthetic receipt failure')))

    def command(arguments, **_kwargs):
        calls.append(arguments)
        if arguments[:3] == ['docker', 'image', 'inspect']:
            return type('Result', (), {'stdout': '[]', 'returncode': 0})()
        if arguments[-2:] == ['config', '--images']:
            return type('Result', (), {'stdout': candidate + '\n', 'returncode': 0})()
        if arguments[-1:] == ['runtime_health']:
            return type('Result', (), {'stdout': json.dumps(ready) + '\n', 'returncode': 0})()
        return type('Result', (), {'stdout': '', 'returncode': 0})()

    monkeypatch.setattr(local_full_runtime, '_run', command)
    with pytest.raises(local_full_runtime.LocalRuntimeError, match='receipt failure'):
        local_full_runtime._execute(
            project='newshub-local-main', source_root=source,
            runtime_root=tmp_path / 'runtime', image=candidate, wait_timeout=300,
            complete_overlay=overlay,
        )

    stop = next(call for call in calls if 'stop' in call and 'indexer' in call)
    assert stop[-9:] == list(reversed(local_full_runtime.REQUIRED_SERVICES))
    assert any('up' in call and call[-1:] == ['app'] for call in calls)
