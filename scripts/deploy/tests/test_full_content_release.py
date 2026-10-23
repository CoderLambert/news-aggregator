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


def manifest(*, version=2, capability=True, channel_capability=False, crawler_capability=True, sha=SHA, static_sha='c' * 64):
    result = dict(schema_version=version, release_sha=sha, image=f'newshub:{sha}',
                  migrations=copy.deepcopy(MIGRATIONS), static_sha=static_sha)
    if version == 2:
        result['capabilities'] = {'full_content_worker': capability}
    elif version in {3, 4}:
        result['capabilities'] = {
            'full_content_worker': capability,
            'channel_worker': channel_capability,
        }
    if version == 4:
        result['capabilities']['crawler_worker'] = crawler_capability
    return result


def test_default_production_retires_collectors_but_explicit_historical_overlay_is_scoped():
    prod = yaml.safe_load((ROOT / 'compose.prod.yaml').read_text())
    assert set(prod['services']) == {'app', 'migrate', 'indexer'}
    overlay = yaml.safe_load((ROOT / 'compose.legacy-workers.prod.yaml').read_text())
    assert set(overlay['services']) == {'crawler', 'full-content'}
    for role, worker in overlay['services'].items():
        assert worker['profiles'] == ['legacy-rollback']
        assert worker['image'].startswith('${NEWSHUB_IMAGE:?')
        assert worker['volumes'] == ['db-data:/var/lib/newshub/db', 'logs-data:/var/lib/newshub/logs']
        assert worker['environment']['DJANGO_DB_PATH'] == '/var/lib/newshub/db/db.sqlite3'
        assert worker['environment']['NEWS_CRAWL_ONLY'] == '1'
        assert not {'env_file', 'ports', 'secrets'} & worker.keys()
        assert not {'AI_BYOK_GATEWAY_PROJECT_KEY_FILE', 'CHATGPT_ACCESS_TOKEN', 'OPENAI_API_KEY'} & worker['environment'].keys()
        assert worker['init'] is True and worker['stop_grace_period'] == '45s'
        assert worker['depends_on']['app']['condition'] == 'service_healthy'
    assert overlay['services']['full-content']['healthcheck']['test'][-1] == 'full_content_healthcheck'
    assert overlay['services']['crawler']['healthcheck']['test'][-1] == 'crawler_healthcheck'
    production_stage = (ROOT / 'Dockerfile').read_text().split('AS production', 1)[1].split('FROM ', 1)[0]
    assert 'USER 10001:10001' in production_stage and release.PRODUCTION_USER == '10001:10001'


def test_development_starts_only_app_and_retained_indexer_with_existing_data_binds():
    services = yaml.safe_load((ROOT / 'compose.yaml').read_text())['services']
    assert set(services) == {'app', 'indexer'}
    assert './backend:/app/backend' in services['app']['volumes']
    assert './logs:/app/logs' in services['app']['volumes']
    assert services['indexer']['image'] == services['app']['image']
    assert services['indexer']['healthcheck']['test'][-1] == 'embedding_healthcheck'


@pytest.mark.parametrize('version,capability,channel', [
    (1, False, False), (2, False, False), (2, True, False),
    (3, False, False), (3, True, True),
])
def test_manifest_schema_preserves_legacy_and_explicit_worker_capability(version, capability, channel):
    value = manifest(version=version, capability=capability, channel_capability=channel)
    assert release.validate_manifest(value) == value
    assert release.full_content_capability(value) is capability
    assert release.channel_worker_capability(value) is channel


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


@pytest.mark.parametrize('capabilities', [
    None, [], True, {},
    {'full_content_worker': True},
    {'channel_worker': True},
    {'full_content_worker': True, 'channel_worker': True, 'unknown': True},
])
def test_v3_capability_object_is_strict(capabilities):
    value = manifest(version=3)
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
    docker = Mock(return_value='{"channel_worker":true,"full_content_worker":true,"crawler_worker":true}')
    monkeypatch.setattr(release, '_docker_text', docker)

    assert release.inspect_worker_capabilities(IMAGE) == {
        'full_content_worker': True,
        'channel_worker': True,
        'crawler_worker': True,
    }

    args = docker.call_args.args
    assert args == ('run', '--rm', '--pull=never', '--network', 'none', '--entrypoint', 'python', IMAGE, '-c', release._CAPABILITY_QUERY)
    assert not set(args).intersection({'--env', '-e', '--env-file', '--mount', '-v', '--volume'})
    assert 'Path(' in args[-1] and '.is_file()' in args[-1]
    for forbidden in ('django', 'sqlite', 'SECRET', 'os.environ', 'import api', 'socket', 'requests', 'urllib'):
        assert forbidden not in args[-1]


@pytest.mark.parametrize('missing', [
    None,
    'api/management/commands/auto_fetch_full_content.py',
    'api/management/commands/full_content_healthcheck.py',
    'api/services/full_content_worker.py',
    'api/services/article_content.py',
    'api/management/commands/channel_worker.py',
    'api/management/commands/channel_worker_healthcheck.py',
    'api/management/commands/crawl_worker.py',
    'api/management/commands/crawler_healthcheck.py',
])
def test_actual_file_capability_query_requires_every_compatibility_component(tmp_path, missing):
    files = (
        'api/management/commands/auto_fetch_full_content.py',
        'api/management/commands/full_content_healthcheck.py',
        'api/services/full_content_worker.py', 'api/services/article_content.py',
        'api/management/commands/channel_worker.py',
        'api/management/commands/channel_worker_healthcheck.py',
        'api/management/commands/crawl_worker.py',
        'api/management/commands/crawler_healthcheck.py',
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name != missing:
            path.write_text('raise AssertionError("metadata probe must not import implementation")')
    query = release._CAPABILITY_QUERY.replace('/app/backend', str(tmp_path))
    result = subprocess.run([sys.executable, '-c', query], capture_output=True, text=True, timeout=5)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        'full_content_worker': missing not in files[:4],
        'channel_worker': missing not in files[4:6],
        'crawler_worker': missing not in files[6:],
    }


@pytest.mark.parametrize('output', ['null', '[]', 'true', '{}', '{"full_content_worker":true}', '{"full_content_worker":1,"channel_worker":true}', '{"full_content_worker":true,"channel_worker":"false"}', '{"full_content_worker":true,"channel_worker":true,"extra":true}', 'invalid-json'])
def test_image_capability_output_cannot_forge_boolean_or_add_metadata(output, monkeypatch):
    monkeypatch.setattr(release, '_docker_text', Mock(return_value=output))
    with pytest.raises(release.ManifestError, match='capability output'):
        release.inspect_worker_capabilities(IMAGE)


@pytest.mark.parametrize('version,manifest_cap,image_cap', [(1, False, True), (2, True, False), (2, False, True)])
def test_validate_image_rejects_forged_manifest_capability(tmp_path, version, manifest_cap, image_cap, monkeypatch, capsys):
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(manifest(version=version, capability=manifest_cap)))
    inspect = Mock()
    monkeypatch.setattr(release, 'inspect_production_image', inspect)
    monkeypatch.setattr(release, 'inspect_worker_capabilities', Mock(return_value={
        'full_content_worker': image_cap,
        'channel_worker': False,
        'crawler_worker': True,
    }))

    assert release.main(['validate', '--manifest', str(path), '--image', IMAGE, '--sha', SHA]) == 2

    inspect.assert_called_once_with(IMAGE, SHA)
    assert 'image worker capability does not match manifest' in capsys.readouterr().err


def test_validate_v3_rejects_channel_worker_capability_mismatch(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(manifest(version=3, channel_capability=True)))
    monkeypatch.setattr(release, 'inspect_production_image', Mock())
    monkeypatch.setattr(release, 'inspect_worker_capabilities', Mock(return_value={
        'full_content_worker': True,
        'channel_worker': False,
        'crawler_worker': True,
    }))

    assert release.main(['validate', '--manifest', str(path), '--image', IMAGE, '--sha', SHA]) == 2
    assert 'image worker capability does not match manifest' in capsys.readouterr().err


@pytest.mark.parametrize('version,capability,channel', [
    (1, False, False), (2, False, False), (2, True, False),
    (3, False, True), (3, True, True),
])
def test_worker_services_is_local_read_only_and_never_runs_docker(tmp_path, version, capability, channel):
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(manifest(version=version, capability=capability, channel_capability=channel)))
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
    expected = ['crawler', 'indexer']
    if capability:
        expected.append('full-content')
    if channel:
        expected.append('channel-worker')
    assert result.stdout.splitlines() == expected
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
    file_positions = [index for index, value in enumerate(args) if value == '-f']
    compose_files = [args[index + 1] for index in file_positions]
    expected_files = [os.environ['TEST_COMPOSE_FILE']]
    if os.environ.get('TEST_WORKSPACE_OVERLAY') == '1':
        expected_files.append(os.environ['TEST_WORKSPACE_COMPOSE_FILE'])
    if os.environ.get('TEST_LEGACY_OVERLAY') == '1':
        expected_files.append(os.environ['TEST_LEGACY_COMPOSE_FILE'])
    if os.environ.get('TEST_WITH_RSS') == '1':
        expected_files.append(os.environ['TEST_RSS_COMPOSE_FILE'])
        assert args[args.index('--profile') + 1] == 'rss'
    assert compose_files == expected_files
    command = args[file_positions[-1] + 2:]
    if command[0] == 'config' and '--format' in command:
        image = 'newshub-rss:' + (old_sha if os.environ.get('TEST_RSS_MODE') == 'stale-image' else target_sha)
        print(json.dumps({'services': {'rss-sync': {'image': image}, 'miniflux': {'image': 'miniflux:synthetic-pinned'}}}))
    elif command[0] in {'config', 'stop'}:
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
    identities={'a'*12:'crawler','b'*12:'full-content','c'*12:'indexer','d'*12:'app','e'*12:'channel-worker','f'*12:'rss-sync','1'*12:'miniflux'}
    if fmt == '{{json .Config.Labels}}':
        print(json.dumps({'com.docker.compose.project':('foreign-project' if container == '1'*12 and os.environ.get('TEST_RSS_MODE') == 'foreign-engine' else 'test_worker_release'),'com.docker.compose.service':identities[container]}))
    elif fmt == '{{.State.Running}}':
        print('false' if (root / ('stopped-' + container)).exists() or (container == 'f'*12 and os.environ.get('TEST_RSS_RUNNING') == '0') else 'true')
    elif fmt == '{{.State.Status}}':
        # Model an unhealthy container subsequently exiting, rather than spend
        # the real 300-second readiness deadline in this local shell test.
        print('exited' if container in {'full-content-new','rss-sync-new'} and (root / 'unhealthy-observed').exists() else 'running')
    elif '.State.Health' in fmt:
        if container == '1'*12 and os.environ.get('TEST_RSS_MODE') == 'unhealthy-engine':
            print('unhealthy')
        elif (container == 'full-content-new' and os.environ['TEST_WORKER_MODE'] == 'unhealthy') or (container == 'rss-sync-new' and os.environ.get('TEST_RSS_MODE') == 'unhealthy'):
            (root / 'unhealthy-observed').touch()
            print('unhealthy')
        else:
            print('healthy')
    elif fmt == '{{.Config.Image}}':
        if container == '1'*12:
            print('miniflux:wrong' if os.environ.get('TEST_RSS_MODE') == 'wrong-engine-image' else 'miniflux:synthetic-pinned')
        elif container == 'rss-sync-new':
            print('newshub-rss:' + (old_sha if os.environ.get('TEST_RSS_MODE') == 'wrong-started-image' else sha))
        else:
            print('newshub:' + sha)
    elif 'org.opencontainers.image.revision' in fmt:
        print(sha)
    elif '/var/lib/newshub/db' in fmt:
        print('volume|test_worker_release_db-data|true')
    else:
        fail()
elif args[0] == 'ps':
    assert '--filter' in args
    if 'volume=test_worker_release_db-data' not in args:
        assert 'label=com.docker.compose.project=test_worker_release' in args
        service=args[-1].rsplit('=',1)[-1]
        identities={'crawler':'a'*12,'full-content':'b'*12,'indexer':'c'*12,'app':'d'*12,'channel-worker':'e'*12}
        if service == 'miniflux' and os.environ.get('TEST_WITH_RSS') == '1' and os.environ.get('TEST_RSS_MODE') != 'missing-engine': print('1'*12)
        elif service == 'rss-sync' and os.environ.get('TEST_HAS_RSS') == '1': print('f'*12)
        elif service in identities: print(identities[service])
elif args[0] == 'stop':
    (root / ('stopped-' + args[-1])).touch()
    print(args[-1])
elif args[0] == 'run':
    if 'api/services/full_content_worker.py' in args[-1]:
        image = args[args.index('-c') - 1]
        capability = True if image.endswith(old_sha) else os.environ['TEST_TARGET_CAP'] == '1'
        channel_capability = os.environ.get('TEST_TARGET_CHANNEL_CAP') == '1' and not image.endswith(old_sha)
        print(json.dumps({'full_content_worker': capability, 'channel_worker': channel_capability, 'crawler_worker': image.endswith(old_sha) or os.environ.get('TEST_TARGET_CRAWLER_CAP') == '1'}))
    elif 'rss_sync_worker.py' in args[-1]:
        print('False' if os.environ.get('TEST_RSS_MODE') == 'missing-command' else 'True')
    elif 'sqlite_snapshot.py inspect --source' in args[-1]:
        print(json.dumps({'quick_check': 'ok', 'migrations': [{'app':'api','name':'0001_initial'}]}))
    else:
        fail()
else:
    fail()
'''


def rollback_harness(tmp_path, *, legacy, mode, workspace=False, worker_services=None, retired=False, has_rss=False, with_rss=False, rss_mode='healthy', action='rollback', leave_rss_stopped=False, rss_running=True):
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
    target_manifest.write_text(json.dumps(manifest(
        version=4 if retired else (1 if legacy else (3 if workspace else 2)),
        capability=not legacy and not retired,
        crawler_capability=not retired,
        channel_capability=workspace,
        static_sha=hashes[SHA],
    )))
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
        'bash', str(ROOT / f'scripts/deploy/{action}.sh'), '--execute',
        '--env-file', str(environment), '--project', 'test_worker_release',
        '--sha', SHA, '--image', IMAGE, '--root', str(static), '--manifest', str(target_manifest),
        '--current-manifest', str(old_manifest), '--db-volume', 'test_worker_release_db-data',
    ] + (['--backup-output', str(tmp_path / 'before.sqlite3')] if action == 'deploy' else []) + (['--with-rss'] if with_rss else []) + (['--leave-rss-stopped'] if leave_rss_stopped else []) + ([] if worker_services is None else ['--worker-services', worker_services]), env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'DOCKER_HOST': 'unix:///synthetic-test-only.sock',
            'TEST_DOCKER_LOG': str(log), 'TEST_HARNESS_ROOT': str(tmp_path),
            'TEST_TARGET_SHA': SHA, 'TEST_OLD_SHA': OLD_SHA, 'TEST_TARGET_CAP': str(int(not legacy and not retired)),
            'TEST_TARGET_CRAWLER_CAP': str(int(not retired)),
            'TEST_TARGET_CHANNEL_CAP': str(int(workspace)), 'TEST_WORKER_MODE': mode,
            'TEST_COMPOSE_FILE': str(ROOT / 'compose.prod.yaml'),
            'TEST_WORKSPACE_COMPOSE_FILE': str(ROOT / 'compose.workspace.prod.yaml'),
            'TEST_HAS_RSS': str(int(has_rss)),
            'TEST_WITH_RSS': str(int(with_rss)), 'TEST_RSS_RUNNING': str(int(rss_running)), 'TEST_RSS_MODE': rss_mode,
            'TEST_RSS_COMPOSE_FILE': str(ROOT / 'compose.rss.prod.yaml'),
            'TEST_WORKSPACE_OVERLAY': str(int(workspace)),
            'TEST_LEGACY_OVERLAY': str(int(not retired and (worker_services is None or any(role in worker_services.split(',') for role in ('crawler', 'full-content'))))),
            'TEST_LEGACY_COMPOSE_FILE': str(ROOT / 'compose.legacy-workers.prod.yaml')},
        capture_output=True, text=True, timeout=15)
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, commands, static


@pytest.mark.parametrize('workers', ['', 'indexer', 'indexer,channel-worker'])
def test_rss_rollback_explicit_subset_does_not_start_legacy_collectors(tmp_path, workers):
    result, commands, _ = rollback_harness(tmp_path, legacy=False, mode='healthy', workspace=True,
                                         worker_services=workers)
    assert result.returncode == 0, result.stdout + result.stderr
    starts = [call for call in commands if call[0] == 'compose' and 'up' in call]
    assert starts and starts[0][-1] == 'app'
    assert not any('crawler' in call or 'full-content' in call for call in starts)
    assert len(starts) == (2 if workers else 1)


@pytest.mark.parametrize('workers', ['channel-worker', 'rss-sync', 'indexer,indexer', ',indexer', 'indexer,'])
def test_rss_rollback_rejects_unsupported_or_ambiguous_subset_before_docker(tmp_path, workers):
    result, commands, static = rollback_harness(tmp_path, legacy=False, mode='healthy', worker_services=workers)
    assert result.returncode == 2 and '--worker-services' in result.stderr
    assert not commands and (static / 'current').readlink() == Path('releases/' + OLD_SHA)


@pytest.mark.parametrize('mode', ['missing', 'unhealthy'])
def test_new_worker_failure_stops_all_project_writers_without_switching_static(tmp_path, mode):
    result, commands, static = rollback_harness(tmp_path, legacy=False, mode=mode)

    assert result.returncode == 2, result.stdout + result.stderr
    assert 'full-content worker did not pass its health check' in result.stderr
    assert 'this project remains stopped after failure' in result.stderr
    assert (static / 'current').readlink() == Path('releases/' + OLD_SHA)
    stops = [call for call in commands if call[0] == 'stop']
    assert len(stops) >= 2  # Planned stop and fail-closed cleanup.
    assert {'a'*12, 'b'*12, 'c'*12, 'd'*12} <= {call[-1] for call in stops}
    assert all(call[1:3] == ['--time', '45'] for call in stops)
    assert not any(call[0] == 'compose' and 'down' in call for call in commands)
    worker_up = next(call for call in commands if call[0] == 'compose' and 'up' in call and 'crawler' in call)
    assert worker_up[-3:] == ['crawler', 'indexer', 'full-content']
    if mode == 'unhealthy':
        assert (tmp_path / 'unhealthy-observed').exists()


def test_legacy_rollback_stops_new_worker_but_only_starts_old_supported_workers(tmp_path):
    result, commands, static = rollback_harness(tmp_path, legacy=True, mode='missing')

    assert result.returncode == 0, result.stdout + result.stderr
    assert (static / 'current').readlink() == Path('releases/' + SHA)
    stops = [call for call in commands if call[0] == 'stop']
    assert stops and {'a'*12, 'b'*12, 'c'*12, 'd'*12} <= {call[-1] for call in stops}
    starts = [call for call in commands if call[0] == 'compose' and 'up' in call]
    assert len(starts) == 2
    assert starts[0][-1] == 'app'
    assert starts[1][-2:] == ['crawler', 'indexer']
    assert not any('full-content' in call for call in starts)
    assert not any('full-content' in call and 'ps' in call for call in commands)


def test_workspace_rollback_loads_overlay_and_manages_channel_worker(tmp_path):
    result, commands, static = rollback_harness(tmp_path, legacy=False, mode='healthy', workspace=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (static / 'current').readlink() == Path('releases/' + SHA)
    compose_calls = [call for call in commands if call[0] == 'compose']
    assert compose_calls
    for call in compose_calls:
        compose_files = [call[index + 1] for index, value in enumerate(call) if value == '-f']
        assert compose_files == [str(ROOT / 'compose.prod.yaml'), str(ROOT / 'compose.workspace.prod.yaml'), str(ROOT / 'compose.legacy-workers.prod.yaml')]
    stops = [call for call in commands if call[0] == 'stop']
    assert stops and {'a'*12, 'b'*12, 'c'*12, 'd'*12, 'e'*12} <= {call[-1] for call in stops}
    worker_up = next(call for call in compose_calls if 'up' in call and 'crawler' in call)
    assert worker_up[-4:] == ['crawler', 'indexer', 'full-content', 'channel-worker']
    assert any('ps' in call and call[-1] == 'channel-worker' for call in compose_calls)


def test_channel_worker_minimal_permissions_and_real_gateway_compatibility():
    """Overlay is combined with compose.prod.yaml, not inherited from app."""
    overlay = yaml.safe_load((ROOT / 'compose.workspace.prod.yaml').read_text())
    worker = overlay['services']['channel-worker']
    prod = yaml.safe_load((ROOT / 'compose.prod.yaml').read_text())
    web = prod['services']['app']

    assert 'extends' not in worker and 'env_file' not in worker
    assert worker['image'] == web['image']
    assert worker['command'][-1] == 'channel_worker'
    assert worker['volumes'] == ['db-data:/var/lib/newshub/db', 'logs-data:/var/lib/newshub/logs']
    assert worker['secrets'] == ['ai_byok_gateway_project_key']
    assert worker['network_mode'] == 'host'  # existing gateway only accepts loopback
    assert worker['read_only'] is True
    assert worker['cap_drop'] == ['ALL']
    assert worker['security_opt'] == ['no-new-privileges:true']
    assert worker['pids_limit'] <= 128
    assert worker['mem_limit'] == '512m'
    assert worker['tmpfs'] == ['/tmp:rw,nosuid,nodev,noexec,size=16m']
    assert worker['depends_on']['migrate']['condition'] == 'service_completed_successfully'
    assert worker['depends_on']['app']['condition'] == 'service_healthy'

    environment = worker['environment']
    assert environment['DJANGO_ENV'] == 'production'
    assert environment['PUBLIC_SITE_MODE'] == '${PUBLIC_SITE_MODE:-read_only}'
    assert environment['PUBLIC_AI_ENABLED'] == '${PUBLIC_AI_ENABLED:-0}'
    assert environment['AI_BYOK_GATEWAY_PROJECT_KEY_FILE'] == '/run/secrets/ai_byok_gateway_project_key'
    assert environment['CHANNEL_WORKER_HEARTBEAT'].startswith('/var/lib/newshub/logs/')
    app_health_environment = overlay['services']['app']['environment']
    assert app_health_environment['CHANNEL_WORKER_HEARTBEAT'] == environment['CHANNEL_WORKER_HEARTBEAT']
    assert 'logs-data:/var/lib/newshub/logs' in web['volumes']
    for web_only in ('WAITRESS_THREADS', 'WAITRESS_PORT', 'WAITRESS_CONN_LIMIT',
                     'CHATGPT_AUTH_MODE', 'CHATGPT_PLAN_USAGE_ENABLED',
                     'EDGE_TTS_ENDPOINT', 'TTS_CACHE_DIR', 'HF_HOME',
                     'SEARCH_INDEX_WORKER_LOCK', 'CHROMA_DATA_DIR'):
        assert web_only not in environment
    assert 'chroma-data' not in repr(worker) and 'tts-data' not in repr(worker)
    assert 'model-cache' not in repr(worker) and 'runtime-data' not in repr(worker)


def test_channel_worker_runtime_settings_are_explicit_and_production_valid():
    from newsaggregator.runtime_config import parse_runtime_config
    import secrets as _secrets
    overlay = yaml.safe_load((ROOT / 'compose.workspace.prod.yaml').read_text())
    env = {
        'DJANGO_ENV': 'production',
        'DJANGO_DEBUG': '0',
        'DJANGO_SECRET_KEY': 'A1b2C3d4E5f6' + _secrets.token_urlsafe(48),
        'WAITRESS_TRUSTED_PROXY': '127.0.0.1',
        'PUBLIC_SITE_MODE': 'full',
        'PUBLIC_AI_ENABLED': '1',
    }
    runtime = parse_runtime_config(env, environment='production')
    assert runtime.public_site_mode == 'full'
    assert runtime.public_ai_enabled is True
    assert set(('DJANGO_SECRET_KEY', 'WAITRESS_TRUSTED_PROXY')).issubset(
        overlay['services']['channel-worker']['environment'])


def test_retired_image_rollback_stops_previous_collectors_without_reviving_them(tmp_path):
    result, commands, static = rollback_harness(tmp_path, legacy=False, retired=True, mode='healthy')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (static / 'current').readlink() == Path('releases/' + SHA)
    starts = [call for call in commands if call[0] == 'compose' and 'up' in call]
    assert len(starts) == 2 and starts[0][-1] == 'app' and starts[1][-1] == 'indexer'
    assert not any('crawler' in call or 'full-content' in call for call in starts)
    assert not any(str(ROOT / 'compose.legacy-workers.prod.yaml') in call for call in commands)
    stopped = {call[-1] for call in commands if call[0] == 'stop'}
    assert {'a'*12, 'b'*12, 'c'*12, 'd'*12} <= stopped


@pytest.mark.parametrize('action', ['deploy', 'rollback'])
def test_existing_rss_runtime_is_not_silently_stopped_by_app_only_release(tmp_path, action):
    result, commands, static = rollback_harness(tmp_path, legacy=False, retired=True,
        mode='healthy', has_rss=True, action=action)
    assert result.returncode == 2, result.stdout + result.stderr
    assert '--with-rss' in result.stderr
    assert not any(call[0] == 'stop' for call in commands)
    assert (static / 'current').readlink() == Path('releases/' + OLD_SHA)


@pytest.mark.parametrize('workers', [None, 'indexer,rss-sync'])
def test_managed_rss_rollback_resumes_independent_same_sha_image(tmp_path, workers):
    result, commands, static = rollback_harness(tmp_path, legacy=False, retired=True,
        mode='healthy', has_rss=True, with_rss=True, worker_services=workers)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (static / 'current').readlink() == Path('releases/' + SHA)
    starts = [call for call in commands if call[0] == 'compose' and 'up' in call]
    assert starts[-1][-2:] == ['indexer', 'rss-sync']
    assert not any('crawler' in call or 'full-content' in call or 'miniflux' in call or 'rss-db' in call for call in starts)
    assert 'f'*12 in {call[-1] for call in commands if call[0] == 'stop'}
    assert any(call[0] == 'inspect' and call[-1] == 'rss-sync-new' and '{{.Config.Image}}' in call for call in commands)


@pytest.mark.parametrize('action', ['deploy', 'rollback'])
@pytest.mark.parametrize('rss_mode', ['stale-image', 'missing-engine', 'wrong-engine-image', 'missing-command', 'foreign-engine', 'unhealthy-engine'])
def test_rss_release_preflight_failure_never_stops_writers(tmp_path, action, rss_mode):
    result, commands, static = rollback_harness(tmp_path, legacy=False, retired=True,
        mode='healthy', has_rss=True, with_rss=True, rss_mode=rss_mode, action=action)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'preflight failed' in result.stderr
    assert not any(call[0] == 'stop' or (call[0] == 'compose' and 'up' in call) for call in commands)
    assert (static / 'current').readlink() == Path('releases/' + OLD_SHA)


@pytest.mark.parametrize('rss_mode', ['unhealthy', 'wrong-started-image'])
def test_rss_resume_failure_stops_project_and_preserves_static(tmp_path, rss_mode):
    result, commands, static = rollback_harness(tmp_path, legacy=False, retired=True,
        mode='healthy', has_rss=True, with_rss=True, rss_mode=rss_mode)
    assert result.returncode == 2 and 'rss-sync worker did not pass' in result.stderr
    assert (static / 'current').readlink() == Path('releases/' + OLD_SHA)
    assert len([call for call in commands if call[0] == 'stop' and call[-1] == 'f'*12]) == 2
    assert not any(call[0] == 'compose' and 'down' in call for call in commands)


def test_managed_rss_cannot_be_omitted_from_explicit_worker_subset(tmp_path):
    result, commands, _ = rollback_harness(tmp_path, legacy=False, retired=True,
        mode='healthy', with_rss=True, worker_services='indexer')
    assert result.returncode == 2 and '--with-rss requires rss-sync' in result.stderr
    assert not commands


@pytest.mark.parametrize('running', [False, True])
def test_explicit_rss_recovery_requires_already_stopped_sync(tmp_path, running):
    result, commands, static = rollback_harness(tmp_path, legacy=False, retired=True,
        mode='healthy', has_rss=True, leave_rss_stopped=True, rss_running=running, worker_services='indexer')
    if running:
        assert result.returncode == 2 and 'already stopped' in result.stderr
        assert not any(call[0] == 'stop' for call in commands)
        assert (static / 'current').readlink() == Path('releases/' + OLD_SHA)
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        starts = [call for call in commands if call[0] == 'compose' and 'up' in call]
        assert starts[-1][-1] == 'indexer'
        assert not any('rss-sync' in call or 'crawler' in call or 'full-content' in call for call in starts)


@pytest.mark.parametrize('with_rss,workers', [(True, 'indexer,rss-sync'), (False, None)])
def test_leave_rss_stopped_requires_unambiguous_explicit_recovery(tmp_path, with_rss, workers):
    result, commands, _ = rollback_harness(tmp_path, legacy=False, retired=True, mode='healthy',
        leave_rss_stopped=True, with_rss=with_rss, worker_services=workers)
    assert result.returncode == 2 and '--leave-rss-stopped' in result.stderr
    assert not commands
