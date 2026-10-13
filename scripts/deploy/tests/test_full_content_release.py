"""Full-content release compatibility without a Docker daemon or live site."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml

from scripts.deploy import release_manifest as release


ROOT = Path(__file__).resolve().parents[3]
OLD_SHA = 'a' * 40
SHA = 'b' * 40
IMAGE = f'newshub:{SHA}'
MIGRATIONS = [{'app': 'api', 'name': '0001_initial'}]


def manifest(*, version=2, capability=True, sha=SHA, static_sha='c' * 64):
    result = dict(schema_version=version, release_sha=sha, image=f'newshub:{sha}',
                  migrations=copy.deepcopy(MIGRATIONS), static_sha=static_sha)
    if version == 2:
        result['capabilities'] = {'full_content_worker': capability}
    return result


def test_production_worker_uses_immutable_nonroot_image_shared_sqlite_logs_and_safe_flags():
    compose = yaml.safe_load((ROOT / 'compose.prod.yaml').read_text())
    services = compose['services']
    worker = services['full-content']
    assert worker['image'] == services['app']['image'] == services['crawler']['image']
    assert '${NEWSHUB_IMAGE:?' in worker['image']
    assert worker['command'] == ['python', '/app/backend/manage.py', 'auto_fetch_full_content', '--foreground']
    assert worker['volumes'] == ['db-data:/var/lib/newshub/db', 'logs-data:/var/lib/newshub/logs']
    assert worker['environment']['DJANGO_DB_PATH'] == '/var/lib/newshub/db/db.sqlite3'
    assert worker['environment']['FULL_CONTENT_WORKER_LOCK'] == services['app']['environment']['FULL_CONTENT_WORKER_LOCK']
    assert worker['environment']['FULL_CONTENT_WORKER_HEARTBEAT'] == services['app']['environment']['FULL_CONTENT_WORKER_HEARTBEAT']
    assert worker['environment']['NEWS_CRAWL_ONLY'] == '1'
    for flag in ('STRUCTURED_BODY_INGEST_ENABLED', 'FULL_CONTENT_WORKER_ENABLED', 'FULL_CONTENT_AUTO_ENQUEUE_ENABLED', 'TECHCRUNCH_WP_ENABLED'):
        assert worker['environment'][flag] == '${' + flag + ':-0}'
    assert worker['environment']['FULL_CONTENT_AUTO_SOURCE_KEYS'] == '${FULL_CONTENT_AUTO_SOURCE_KEYS:-}'
    assert worker['environment']['STRUCTURED_BODY_SOURCE_KEYS'] == '${STRUCTURED_BODY_SOURCE_KEYS:-}'
    assert worker['depends_on'] == {'migrate': {'condition': 'service_completed_successfully'}, 'app': {'condition': 'service_healthy'}}
    assert worker['env_file'] == services['app']['env_file']
    assert worker['init'] is True
    assert worker['stop_grace_period'] == '45s'
    assert worker['restart'] == 'unless-stopped'
    assert worker['healthcheck']['test'] == ['CMD', 'python', '/app/backend/manage.py', 'full_content_healthcheck']
    production_stage = (ROOT / 'Dockerfile').read_text().split('AS production', 1)[1].split('FROM ', 1)[0]
    assert 'USER 10001:10001' in production_stage
    assert release.PRODUCTION_USER == '10001:10001'


def test_development_worker_shares_app_database_directory_and_ownership_paths():
    services = yaml.safe_load((ROOT / 'compose.yaml').read_text())['services']
    worker = services['full-content']
    assert worker['image'] == services['app']['image']
    assert worker['build'] == services['app']['build']
    assert worker['volumes'] == ['./backend:/app/backend', './logs:/app/logs']
    assert './backend:/app/backend' in services['app']['volumes']
    assert './logs:/app/logs' in services['app']['volumes']
    assert worker['env_file'] == services['app']['env_file']
    for key in ('FULL_CONTENT_WORKER_LOCK', 'FULL_CONTENT_WORKER_HEARTBEAT'):
        assert worker['environment'][key] == services['app']['environment'][key] == services['crawler']['environment'][key]
    assert worker['environment']['RUN_MAIN'] == 'true'
    assert worker['environment']['NEWS_CRAWL_ONLY'] == '1'
    assert worker['init'] is True
    assert worker['stop_grace_period'] == '45s'
    assert worker['healthcheck']['test'][-1] == 'full_content_healthcheck'
    assert worker['depends_on']['app']['condition'] == 'service_healthy'


@pytest.mark.parametrize('version,capability', [(1, False), (2, False), (2, True)])
def test_manifest_schema_preserves_legacy_and_explicit_worker_capability(version, capability):
    value = manifest(version=version, capability=capability)
    assert release.validate_manifest(value) == value
    assert release.full_content_capability(value) is capability


@pytest.mark.parametrize('bad', [None, 0, 1, '', 'false', 'true', [], {}])
def test_manifest_capability_requires_actual_boolean(bad):
    value = manifest(capability=bad)
    with pytest.raises(release.ManifestError, match='capabilities'):
        release.validate_manifest(value)


@pytest.mark.parametrize('capabilities', [None, [], True, {}, {'full_content_worker': True, 'unknown': True}])
def test_v2_capability_object_is_strict(capabilities):
    value = manifest()
    value['capabilities'] = capabilities
    with pytest.raises(release.ManifestError):
        release.validate_manifest(value)


def test_v1_cannot_smuggle_new_worker_capability_and_version_boolean_is_not_integer():
    value = manifest(version=1)
    value['capabilities'] = {'full_content_worker': True}
    with pytest.raises(release.ManifestError):
        release.validate_manifest(value)
    value = manifest()
    value['schema_version'] = True
    with pytest.raises(release.ManifestError):
        release.validate_manifest(value)


def test_worker_probe_is_pinned_network_none_file_only_without_env_mount_or_database(monkeypatch):
    docker = Mock(return_value='{"full_content_worker":true}')
    monkeypatch.setattr(release, '_docker_text', docker)

    assert release.inspect_worker_capability(IMAGE) is True

    args = docker.call_args.args
    assert args == ('run', '--rm', '--pull=never', '--network', 'none', '--entrypoint', 'python', IMAGE, '-c', release._CAPABILITY_QUERY)
    assert not set(args).intersection({'--env', '-e', '--env-file', '--mount', '-v', '--volume'})
    assert 'Path(' in args[-1] and '.is_file()' in args[-1]
    for forbidden in ('django', 'sqlite', 'SECRET', 'os.environ', 'import api', 'socket', 'requests', 'urllib'):
        assert forbidden not in args[-1]


@pytest.mark.parametrize('missing', [None, 'auto_fetch_full_content.py', 'full_content_healthcheck.py', 'full_content_worker.py', 'article_content.py'])
def test_actual_file_capability_query_requires_every_compatibility_component(tmp_path, missing):
    files = (
        'api/management/commands/auto_fetch_full_content.py',
        'api/management/commands/full_content_healthcheck.py',
        'api/services/full_content_worker.py', 'api/services/article_content.py',
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.name != missing:
            path.write_text('raise AssertionError("metadata probe must not import implementation")')
    query = release._CAPABILITY_QUERY.replace('/app/backend/', str(tmp_path) + '/')
    result = subprocess.run([sys.executable, '-c', query], capture_output=True, text=True, timeout=5)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'full_content_worker': missing is None}


@pytest.mark.parametrize('output', ['null', '[]', 'true', '{}', '{"full_content_worker":1}', '{"full_content_worker":"false"}', '{"full_content_worker":true,"extra":true}', 'invalid-json'])
def test_image_capability_output_cannot_forge_boolean_or_add_metadata(output, monkeypatch):
    monkeypatch.setattr(release, '_docker_text', Mock(return_value=output))
    with pytest.raises(release.ManifestError, match='capability output'):
        release.inspect_worker_capability(IMAGE)


@pytest.mark.parametrize('version,manifest_cap,image_cap', [(1, False, True), (2, True, False), (2, False, True)])
def test_validate_image_rejects_forged_manifest_capability(tmp_path, version, manifest_cap, image_cap, monkeypatch, capsys):
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(manifest(version=version, capability=manifest_cap)))
    inspect = Mock()
    monkeypatch.setattr(release, 'inspect_production_image', inspect)
    monkeypatch.setattr(release, 'inspect_worker_capability', Mock(return_value=image_cap))

    assert release.main(['validate', '--manifest', str(path), '--image', IMAGE, '--sha', SHA]) == 2

    inspect.assert_called_once_with(IMAGE, SHA)
    assert 'image worker capability does not match manifest' in capsys.readouterr().err


@pytest.mark.parametrize('version,capability', [(1, False), (2, False), (2, True)])
def test_worker_services_is_local_read_only_and_never_runs_docker(tmp_path, version, capability):
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(manifest(version=version, capability=capability)))
    binary = tmp_path / 'docker'
    touched = tmp_path / 'docker-was-called'
    binary.write_text('#!/bin/sh\ntouch "' + str(touched) + '"\nexit 99\n')
    binary.chmod(0o700)
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/deploy/release_manifest.py'), 'worker-services', '--manifest', str(path)],
        env={**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']}, capture_output=True, text=True, timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['crawler', 'indexer'] + (['full-content'] if capability else [])
    assert not touched.exists()
    assert path.read_bytes() == before


FAKE_DOCKER = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['TEST_DOCKER_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
root = Path(os.environ['TEST_HARNESS_ROOT'])
target_sha = os.environ['TEST_TARGET_SHA']
old_sha = os.environ['TEST_OLD_SHA']
def fail():
    raise SystemExit('unexpected fake Docker command: ' + repr(args))
if args[0] == 'context':
    print('default' if args[1] == 'show' else 'unix:///var/run/docker.sock')
elif args[0] == 'image' and args[1] == 'inspect':
    print('10001:10001' if '.Config.User' in args[3] else args[-1].split(':')[-1])
elif args[0] == 'compose':
    assert args[args.index('--project-name') + 1] == 'test_worker_release'
    assert args[args.index('-f') + 1] == os.environ['TEST_COMPOSE_FILE']
    command = args[args.index('-f') + 2:]
    if command[0] in {'config', 'stop'}:
        pass
    elif command[0] == 'up':
        if command[-1] == 'app':
            (root / 'app-up').touch()
    elif command[0] == 'ps':
        service = command[-1]
        if service == 'app':
            print('app-new' if (root / 'app-up').exists() else 'app-old')
        elif service == 'full-content' and os.environ['TEST_WORKER_MODE'] == 'missing':
            pass
        else:
            print(service + '-new')
    else:
        fail()
elif args[0] == 'inspect':
    fmt, container = args[2], args[-1]
    sha = old_sha if container == 'app-old' else target_sha
    if fmt == '{{.State.Status}}':
        # Model an unhealthy container subsequently exiting, rather than spend
        # the real 300-second readiness deadline in this local shell test.
        print('exited' if container == 'full-content-new' and (root / 'unhealthy-observed').exists() else 'running')
    elif '.State.Health' in fmt:
        if container == 'full-content-new' and os.environ['TEST_WORKER_MODE'] == 'unhealthy':
            (root / 'unhealthy-observed').touch()
            print('unhealthy')
        else:
            print('healthy')
    elif fmt == '{{.Config.Image}}':
        print('newshub:' + sha)
    elif 'org.opencontainers.image.revision' in fmt:
        print(sha)
    elif '/var/lib/newshub/db' in fmt:
        print('volume|test_worker_release_db-data|true')
    else:
        fail()
elif args[0] == 'ps':
    assert '--filter' in args and 'volume=test_worker_release_db-data' in args
elif args[0] == 'run':
    if 'api/services/full_content_worker.py' in args[-1]:
        image = args[args.index('-c') - 1]
        capability = True if image.endswith(old_sha) else os.environ['TEST_TARGET_CAP'] == '1'
        print(json.dumps({'full_content_worker': capability}))
    elif 'sqlite_snapshot.py inspect --source' in args[-1]:
        print(json.dumps({'quick_check': 'ok', 'migrations': [{'app':'api','name':'0001_initial'}]}))
    else:
        fail()
else:
    fail()
'''


def rollback_harness(tmp_path, *, legacy, mode):
    static = tmp_path / 'static'
    assets = static / 'assets'
    assets.mkdir(parents=True)
    hashes = {}
    for sha in (OLD_SHA, SHA):
        directory = static / 'releases' / sha
        (directory / 'assets').mkdir(parents=True)
        (directory / 'index.html').write_text('<html>' + sha + '</html>')
        shared = assets / (sha + '.js')
        shared.write_text(sha)
        (directory / 'assets' / shared.name).hardlink_to(shared)
        hashes[sha] = release.sha256_exported_release(directory)
    (static / 'current').symlink_to('releases/' + OLD_SHA)
    old_manifest = tmp_path / 'old.json'
    target_manifest = tmp_path / 'target.json'
    old_manifest.write_text(json.dumps(manifest(sha=OLD_SHA, static_sha=hashes[OLD_SHA])))
    target_manifest.write_text(json.dumps(manifest(version=1 if legacy else 2, capability=not legacy, static_sha=hashes[SHA])))
    environment = tmp_path / 'deploy.env'
    environment.write_text('DJANGO_SECRET_KEY=synthetic-test-only\nWAITRESS_TRUSTED_PROXY=127.0.0.1\n')
    binary = tmp_path / 'bin'
    binary.mkdir()
    docker = binary / 'docker'
    docker.write_text('#!' + sys.executable + '\n' + FAKE_DOCKER)
    docker.chmod(0o700)
    sleep = binary / 'sleep'
    sleep.write_text('#!/bin/sh\nexit 0\n')
    sleep.chmod(0o700)
    log = tmp_path / 'docker.jsonl'
    result = subprocess.run([
        'bash', str(ROOT / 'scripts/deploy/rollback.sh'), '--execute',
        '--env-file', str(environment), '--project', 'test_worker_release',
        '--sha', SHA, '--image', IMAGE, '--root', str(static), '--manifest', str(target_manifest),
        '--current-manifest', str(old_manifest), '--db-volume', 'test_worker_release_db-data',
    ], env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'DOCKER_HOST': 'unix:///synthetic-test-only.sock',
            'TEST_DOCKER_LOG': str(log), 'TEST_HARNESS_ROOT': str(tmp_path),
            'TEST_TARGET_SHA': SHA, 'TEST_OLD_SHA': OLD_SHA, 'TEST_TARGET_CAP': str(int(not legacy)),
            'TEST_WORKER_MODE': mode, 'TEST_COMPOSE_FILE': str(ROOT / 'compose.prod.yaml')},
        capture_output=True, text=True, timeout=15)
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    return result, commands, static


@pytest.mark.parametrize('mode', ['missing', 'unhealthy'])
def test_new_worker_failure_stops_all_project_writers_without_switching_static(tmp_path, mode):
    result, commands, static = rollback_harness(tmp_path, legacy=False, mode=mode)

    assert result.returncode == 2, result.stdout + result.stderr
    assert 'full-content worker did not pass its health check' in result.stderr
    assert 'this project remains stopped after failure' in result.stderr
    assert (static / 'current').readlink() == Path('releases/' + OLD_SHA)
    stops = [call for call in commands if call[0] == 'compose' and 'stop' in call]
    assert len(stops) >= 2  # Planned stop and fail-closed cleanup.
    assert all(call[-4:] == ['full-content', 'crawler', 'indexer', 'app'] for call in stops)
    assert all(call[call.index('--project-name') + 1] == 'test_worker_release' for call in stops)
    assert not any(call[0] == 'compose' and 'down' in call for call in commands)
    worker_up = next(call for call in commands if call[0] == 'compose' and 'up' in call and 'crawler' in call)
    assert worker_up[-3:] == ['crawler', 'indexer', 'full-content']
    if mode == 'unhealthy':
        assert (tmp_path / 'unhealthy-observed').exists()


def test_legacy_rollback_stops_new_worker_but_only_starts_old_supported_workers(tmp_path):
    result, commands, static = rollback_harness(tmp_path, legacy=True, mode='missing')

    assert result.returncode == 0, result.stdout + result.stderr
    assert (static / 'current').readlink() == Path('releases/' + SHA)
    stops = [call for call in commands if call[0] == 'compose' and 'stop' in call]
    assert stops and all(call[-4:] == ['full-content', 'crawler', 'indexer', 'app'] for call in stops)
    starts = [call for call in commands if call[0] == 'compose' and 'up' in call]
    assert len(starts) == 2
    assert starts[0][-1] == 'app'
    assert starts[1][-2:] == ['crawler', 'indexer']
    assert not any('full-content' in call for call in starts)
    assert not any('full-content' in call and 'ps' in call for call in commands)
