import json
import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


_PRODUCTION_FLAG_DEFAULTS = {
    'PUBLIC_SITE_MODE': 'read_only',
    'PUBLIC_SIGNUP_ENABLED': '0',
    'PUBLIC_AI_ENABLED': '0',
    'CHATGPT_PLAN_USAGE_ENABLED': '0',
    'CHATGPT_AUTH_MODE': 'disabled',
    'CRAWLER_SCHEDULER_ENABLED': '0',
    'CRAWL_RUN_ON_START': '0',
    'SEARCH_INDEX_ENABLED': '0',
}


def _production_compose_config(project, tmp_path, explicit_values):
    compose_project = tmp_path / 'compose-project'
    compose_project.mkdir(parents=True)
    app_env = compose_project / 'app.env'
    app_env.write_text('DJANGO_ENV=production\n', encoding='utf-8')

    # A local .env must not silently override the explicit --env-file or defaults.
    (compose_project / '.env').write_text(
        '\n'.join(f'{key}=root-dotenv-value' for key in _PRODUCTION_FLAG_DEFAULTS),
        encoding='utf-8',
    )

    values = {
        'NEWSHUB_IMAGE': 'newshub:compose-test',
        'DJANGO_SECRET_KEY': 'compose-test-key-never-used-for-authentication-0123456789',
        'WAITRESS_TRUSTED_PROXY': '127.0.0.1',
        'NEWSHUB_ENV_FILE': str(app_env),
        **explicit_values,
    }
    env_file = compose_project / 'compose.env'
    env_file.write_text(
        '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n',
        encoding='utf-8',
    )

    environment = os.environ.copy()
    for key in (*values, *_PRODUCTION_FLAG_DEFAULTS):
        environment.pop(key, None)
    result = subprocess.run(
        [
            'docker', 'compose',
            '--project-directory', str(compose_project),
            '--env-file', str(env_file),
            '-f', str(project / 'compose.prod.yaml'),
            'config', '--format', 'json',
        ],
        cwd=compose_project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, 'production Compose config must parse successfully'
    return json.loads(result.stdout)


def _docker_inspect(resource_type, resource_name):
    return subprocess.run(
        ['docker', resource_type, 'inspect', resource_name],
        check=False,
        capture_output=True,
        text=True,
    )


def _docker_checked(*arguments):
    result = subprocess.run(
        ['docker', *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Docker command failed: {' '.join(arguments[:2])}"
    return result


def test_dockerignore_excludes_data_and_common_credentials():
    project = Path(__file__).resolve().parents[2]
    patterns = {
        line.strip()
        for line in (project / '.dockerignore').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    }

    assert {'.env', '.env.*', '**/*.sqlite3', '**/*.sqlite3-wal', '**/*.sqlite3-shm'} <= patterns
    assert {'*.pem', '*.key', '*.p12', '*.pfx', '*.crt', '*.cer'} <= patterns
    assert {
        '**/.env', '**/.env.*', '**/*.pem', '**/*.key', '**/*.p12', '**/*.pfx',
        '**/*.crt', '**/*.cer', '**/auth.json', '**/.runtime/', '**/.cache/',
        '**/logs/', '**/*.log', 'backend/media/',
    } <= patterns


def test_real_docker_context_excludes_nested_private_files_but_keeps_source(tmp_path):
    project = Path(__file__).resolve().parents[2]
    context = tmp_path / 'context'
    context.mkdir()
    (context / '.dockerignore').write_text(
        (project / '.dockerignore').read_text(encoding='utf-8'),
        encoding='utf-8',
    )
    (context / 'Dockerfile').write_text(
        'FROM scratch\nCOPY . /context/\n',
        encoding='utf-8',
    )

    excluded_paths = (
        '.env',
        '.env.production',
        'backend/.env',
        'backend/.env.local',
        'frontend/.env.local',
        'backend/credentials/key.pem',
        'backend/credentials/signing.key',
        'backend/credentials/session.p12',
        'backend/credentials/keystore.pfx',
        'frontend/certs/server.crt',
        'frontend/certs/ca.cer',
        'backend/auth.json',
        'frontend/assets/auth.json',
        'backend/.runtime/deployment-id',
        'frontend/src/.cache/bundle.bin',
        'backend/logs/crawler.log',
        'backend/var/debug.log',
        'backend/db.sqlite3',
        'backend/data/cache.sqlite3-wal',
        'backend/media/tts_cache/private.mp3',
        'backend/media/uploads/avatar.bin',
    )
    for relative_path in excluded_paths:
        path = context / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic dummy content only\n')

    included_paths = (
        'backend/source.py',
        'backend/api/token_manager.py',
        'frontend/src/App.tsx',
    )
    for relative_path in included_paths:
        path = context / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic source marker\n', encoding='utf-8')

    suffix = uuid.uuid4().hex[:12]
    image_tag = f'newshub-context-test:{suffix}'
    container_name = f'newshub-context-test-{suffix}'
    assert _docker_inspect('image', image_tag).returncode != 0
    assert _docker_inspect('container', container_name).returncode != 0

    try:
        _docker_checked('build', '--tag', image_tag, '--file', str(context / 'Dockerfile'), str(context))
        _docker_checked('create', '--name', container_name, image_tag, '/not-started')
        copied = tmp_path / 'copied'
        copied.mkdir()
        _docker_checked('cp', f'{container_name}:/context/.', str(copied))

        for relative_path in excluded_paths:
            assert not (copied / relative_path).exists(), relative_path
        for relative_path in included_paths:
            assert (copied / relative_path).read_text(encoding='utf-8') == (
                'synthetic source marker\n'
            )
    finally:
        if _docker_inspect('container', container_name).returncode == 0:
            _docker_checked('rm', '--force', container_name)
        if _docker_inspect('image', image_tag).returncode == 0:
            _docker_checked('image', 'rm', '--force', image_tag)


def test_dockerfile_keeps_development_default_and_has_explicit_production_target():
    project = Path(__file__).resolve().parents[2]
    dockerfile = (project / 'Dockerfile').read_text(encoding='utf-8')
    assert 'FROM python:3.12-slim AS runtime-base' in dockerfile
    assert 'FROM runtime-base AS production' in dockerfile
    assert 'FROM runtime-base AS development' in dockerfile
    assert dockerfile.rfind('FROM runtime-base AS development') > dockerfile.index(
        'FROM runtime-base AS production'
    )
    assert 'ARG RELEASE_SHA' in dockerfile
    assert "grep -Eq '^[0-9a-f]{40}$'" in dockerfile
    assert 'org.opencontainers.image.revision' in dockerfile
    assert 'USER 10001:10001' in dockerfile
    assert 'HF_HOME=/var/lib/newshub/model-cache' in dockerfile
    assert 'HF_HOME=/root/.cache/huggingface' in dockerfile
    assert 'COPY --chown=' not in dockerfile


def test_production_compose_uses_only_named_volumes_and_separate_migration():
    project = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load(
        (project / 'compose.prod.yaml').read_text(encoding='utf-8')
    )
    services = compose['services']
    declared_volumes = set(compose['volumes'])

    assert set(services) == {'app', 'migrate', 'crawler', 'indexer'}
    assert all('build' not in service for service in services.values())
    assert all('ports' not in service for service in services.values())
    assert all(service['image'].startswith('${NEWSHUB_IMAGE:?') for service in services.values())

    app = services['app']
    migrate = services['migrate']
    assert app['network_mode'] == 'host'
    assert app['depends_on']['migrate']['condition'] == 'service_completed_successfully'
    assert app['env_file'][0]['path'] == '${NEWSHUB_ENV_FILE:-.env.production}'
    assert "'Host': 'news.lambert.host'" in app['healthcheck']['test'][-1]
    assert migrate['command'] == ['python', '/app/scripts/docker-migrate.py']
    assert migrate['restart'] == 'no'
    assert migrate['volumes'] == ['db-data:/var/lib/newshub/db']

    for service_name, service in services.items():
        assert all(
            volume.split(':', 1)[0] in declared_volumes
            for volume in service.get('volumes', [])
        ), service_name
    assert declared_volumes == {
        'db-data',
        'chroma-data',
        'tts-data',
        'runtime-data',
        'model-cache',
        'logs-data',
    }

    for service_name in ('crawler', 'indexer'):
        assert 'env_file' not in services[service_name]
        assert services[service_name]['depends_on']['migrate']['condition'] == (
            'service_completed_successfully'
        )
        assert services[service_name]['depends_on']['app']['condition'] == 'service_healthy'

    for service_name, command in (
        ('crawler', 'crawler_healthcheck'),
        ('indexer', 'embedding_healthcheck'),
    ):
        healthcheck = services[service_name]['healthcheck']
        assert healthcheck['test'] == [
            'CMD', 'python', '/app/backend/manage.py', command,
        ]
        assert healthcheck['interval'] == '30s'
        assert healthcheck['timeout'] == '8s'
        assert healthcheck['retries'] == 3
        assert healthcheck['start_period'] == '30s'

    runtime_environment = compose['x-runtime-environment']
    assert runtime_environment['DJANGO_DB_PATH'] == '/var/lib/newshub/db/db.sqlite3'
    assert runtime_environment['CHROMA_DATA_DIR'] == '/var/lib/newshub/chroma'
    assert runtime_environment['TTS_CACHE_DIR'] == '/var/lib/newshub/tts'
    assert runtime_environment['PUBLIC_SITE_MODE'] == '${PUBLIC_SITE_MODE:-read_only}'
    assert runtime_environment['PUBLIC_AI_ENABLED'] == '${PUBLIC_AI_ENABLED:-0}'
    assert runtime_environment['CHATGPT_AUTH_MODE'] == '${CHATGPT_AUTH_MODE:-disabled}'
    assert runtime_environment['CRAWLER_SCHEDULER_ENABLED'] == '${CRAWLER_SCHEDULER_ENABLED:-0}'
    assert runtime_environment['SEARCH_INDEX_ENABLED'] == '${SEARCH_INDEX_ENABLED:-0}'
    forbidden_worker_secrets = {'OPENAI_API_KEY', 'DASHSCOPE_API_KEY', 'CHATGPT_ACCESS_TOKEN'}
    assert forbidden_worker_secrets.isdisjoint(runtime_environment)


def test_production_compose_flag_defaults_ignore_dotenv_and_allow_explicit_values(tmp_path):
    project = Path(__file__).resolve().parents[2]

    default_config = _production_compose_config(project, tmp_path / 'defaults', {})
    for service_name in ('app', 'migrate', 'crawler', 'indexer'):
        environment = default_config['services'][service_name]['environment']
        assert {key: environment[key] for key in _PRODUCTION_FLAG_DEFAULTS} == (
            _PRODUCTION_FLAG_DEFAULTS
        )

    explicit_values = {
        'PUBLIC_SITE_MODE': 'full',
        'PUBLIC_SIGNUP_ENABLED': '1',
        'PUBLIC_AI_ENABLED': '1',
        'CHATGPT_PLAN_USAGE_ENABLED': '1',
        'CHATGPT_AUTH_MODE': 'website',
        'CRAWLER_SCHEDULER_ENABLED': '1',
        'CRAWL_RUN_ON_START': '1',
        'SEARCH_INDEX_ENABLED': '1',
    }
    explicit_config = _production_compose_config(
        project,
        tmp_path / 'explicit',
        explicit_values,
    )
    for service_name in ('app', 'migrate', 'crawler', 'indexer'):
        environment = explicit_config['services'][service_name]['environment']
        assert {key: environment[key] for key in explicit_values} == explicit_values


def test_worker_healthcheck_commands_fail_when_heartbeat_is_missing(monkeypatch):
    from django.core.management.base import CommandError

    from api.management.commands import crawler_healthcheck, embedding_healthcheck

    missing_crawler_settings = SimpleNamespace(
        first=lambda: SimpleNamespace(worker_heartbeat_at=None)
    )
    monkeypatch.setattr(
        crawler_healthcheck.CrawlerSettings.objects,
        'filter',
        lambda **_kwargs: missing_crawler_settings,
    )
    with pytest.raises(CommandError):
        crawler_healthcheck.Command().handle()

    monkeypatch.setattr(
        embedding_healthcheck,
        'get_search_index_settings',
        lambda: SimpleNamespace(worker_heartbeat_at=None),
    )
    with pytest.raises(CommandError):
        embedding_healthcheck.Command().handle()


def test_development_compose_keeps_existing_source_and_database_bind_mount():
    project = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((project / 'compose.yaml').read_text(encoding='utf-8'))
    app_volumes = compose['services']['app']['volumes']
    assert './backend:/app/backend' in app_volumes


def test_production_environment_template_has_absolute_data_paths_and_no_secret():
    project = Path(__file__).resolve().parents[2]
    template = (project / '.env.production.example').read_text(encoding='utf-8')
    assert 'DJANGO_SECRET_KEY=\n' in template
    for assignment in (
        'DJANGO_DB_PATH=/var/lib/newshub/db/db.sqlite3',
        'CHROMA_DATA_DIR=/var/lib/newshub/chroma',
        'TTS_CACHE_DIR=/var/lib/newshub/tts',
        'CHATGPT_DEPLOYMENT_INSTANCE_FILE=/var/lib/newshub/runtime/chatgpt-deployment-id',
        'HF_HOME=/var/lib/newshub/model-cache',
        'CRAWLER_LOG_DIR=/var/lib/newshub/logs/crawler',
        'CRAWLER_WORKER_LOCK=/var/lib/newshub/logs/crawler-worker.lock',
        'SEARCH_INDEX_WORKER_LOCK=/var/lib/newshub/logs/search-index-worker.lock',
    ):
        assert assignment in template


def test_production_entrypoint_skips_implicit_migrations_but_dev_keeps_them():
    project = Path(__file__).resolve().parents[2]
    entrypoint = (project / 'scripts' / 'docker-entrypoint.sh').read_text(encoding='utf-8')
    production_branch = entrypoint.split('production)', 1)[1].split('development)', 1)[0]
    development_branch = entrypoint.split('development)', 1)[1].split('*)', 1)[0]
    assert 'manage.py migrate' not in production_branch
    assert 'python /app/backend/manage.py migrate --noinput' in development_branch
