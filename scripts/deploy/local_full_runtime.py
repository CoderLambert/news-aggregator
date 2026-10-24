#!/usr/bin/env python3
"""Activate the complete local NewsHub manual-acceptance runtime.

Preview is the default. Execution targets one explicit local Compose project,
keeps existing data and secrets, and pauses business I/O until preflight passes.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


REQUIRED_SERVICES = (
    'app', 'indexer', 'translation-redis', 'rss-db', 'miniflux',
    'ai-gateway-db', 'ai-gateway', 'rss-sync', 'channel-worker',
)
INFRASTRUCTURE_SERVICES = REQUIRED_SERVICES[:7]
REQUIRED_HEALTH_CHECKS = (
    'database', 'rss_worker', 'rss_engine', 'channel_worker', 'search_index',
    'translation_redis', 'ai_gateway',
)
PROJECT_RE = re.compile(r'^newshub-local-[a-z0-9][a-z0-9_-]{0,48}$')
IMAGE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:@-]*$')
IMAGE_DIGEST_RE = re.compile(r'^.+@sha256:[0-9a-f]{64}$')
IMAGE_SHA_TAG_RE = re.compile(r'^.+(?:[-_.])[0-9a-f]{40}$')
PENDING = 'pending-local-bootstrap'


class LocalRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActivationCommands:
    quiesce: list[str] | None
    infrastructure: list[str]
    preflight: list[str]
    full: list[str]
    verify: list[str]
    stop_new: list[str]
    rollback: list[str]


def _compose(project: str, files: tuple[Path, ...], env_file: Path | None = None) -> list[str]:
    command = ['docker', 'compose', '-p', project]
    for path in files:
        command += ['-f', str(path)]
    if env_file is not None:
        command += ['--env-file', str(env_file)]
    return command


def activation_commands(*, project: str, compose_files: tuple[Path, ...],
                        previous_compose: tuple[Path, ...], current_env_file: Path,
                        previous_env_file: Path | None,
                        previous_services: tuple[str, ...], wait_timeout: int) -> ActivationCommands:
    current = _compose(project, compose_files, current_env_file)
    old = _compose(project, previous_compose, previous_env_file)
    up = ['up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', str(wait_timeout)]
    replace = [*up, '--force-recreate']
    quiesce_targets = [name for name in ('miniflux', 'rss-sync', 'channel-worker')
                       if name in previous_services]
    return ActivationCommands(
        quiesce=old + ['stop', *quiesce_targets] if quiesce_targets else None,
        infrastructure=current + up + list(INFRASTRUCTURE_SERVICES),
        preflight=current + replace + list(REQUIRED_SERVICES),
        full=current + replace + list(REQUIRED_SERVICES),
        verify=current + ['exec', '-T', 'app', 'python', '/app/backend/manage.py', 'runtime_health'],
        stop_new=current + ['stop', '--timeout', '45', *reversed(REQUIRED_SERVICES[2:])],
        rollback=old + up + list(previous_services),
    )


class SecretStore:
    def __init__(self, root: Path):
        self.root = root

    def _prepare(self) -> None:
        if self.root.is_symlink():
            raise LocalRuntimeError('runtime secret directory must be a real private directory')
        if not self.root.exists():
            self.root.mkdir(parents=True, mode=0o700)
        try:
            info = self.root.stat()
        except OSError:
            raise LocalRuntimeError('runtime secret directory is unavailable') from None
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise LocalRuntimeError('runtime secret directory must be owner-only mode 0700')

    def _validate(self, path: Path) -> None:
        try:
            info = path.lstat()
        except OSError:
            raise LocalRuntimeError('runtime secret must be a regular private file') from None
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size < 1 or info.st_size > 65536):
            raise LocalRuntimeError('runtime secret must be a regular private file')

    def ensure(self, name: str, factory) -> Path:
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name):
            raise LocalRuntimeError('invalid runtime secret name')
        self._prepare()
        path = self.root / name
        if path.exists() or path.is_symlink():
            self._validate(path)
            return path
        value = factory()
        if not isinstance(value, str) or not value or '\n' in value or '\r' in value:
            raise LocalRuntimeError('generated runtime secret is invalid')
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(value + '\n')
        except OSError:
            raise LocalRuntimeError('could not create runtime secret') from None
        self._validate(path)
        return path

    def read(self, name: str) -> str:
        path = self.root / name
        self._validate(path)
        try:
            value = path.read_text(encoding='utf-8').strip()
        except OSError:
            raise LocalRuntimeError('could not read runtime secret') from None
        if not value:
            raise LocalRuntimeError('runtime secret is empty')
        return value

    def replace_pending(self, name: str, value: str) -> Path:
        if self.read(name) != PENDING:
            raise LocalRuntimeError('refusing to rotate an existing runtime secret')
        if not value or '\n' in value or '\r' in value:
            raise LocalRuntimeError('replacement runtime secret is invalid')
        path = self.root / name
        temporary = self.root / ('.' + name + '.new')
        if temporary.exists() or temporary.is_symlink():
            raise LocalRuntimeError('runtime secret staging path is occupied')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(value + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError:
            raise LocalRuntimeError('could not replace pending runtime secret') from None
        self._validate(path)
        return path


def require_full_health(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 1:
        raise LocalRuntimeError('runtime health response is invalid')
    checks = snapshot.get('checks')
    if not isinstance(checks, dict):
        raise LocalRuntimeError('runtime health response has no checks')
    for name in REQUIRED_HEALTH_CHECKS:
        check = checks.get(name)
        if (not isinstance(check, dict) or check.get('enabled') is not True
                or check.get('ready') is not True or check.get('status') != 'ready'):
            raise LocalRuntimeError(f'runtime health check is not ready: {name}')
    if snapshot.get('ready') is not True:
        raise LocalRuntimeError('runtime health summary is not ready')
    return snapshot


def require_immutable_image(image: str) -> str:
    if (not isinstance(image, str) or not IMAGE_RE.fullmatch(image)
            or not (IMAGE_DIGEST_RE.fullmatch(image) or IMAGE_SHA_TAG_RE.fullmatch(image))):
        raise LocalRuntimeError('local image must be an explicit immutable SHA tag or digest')
    return image


def _run(arguments: list[str], *, environment=None, input_text=None, timeout=300, check=True):
    try:
        result = subprocess.run(arguments, env=environment, input=input_text, text=True,
                                capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise LocalRuntimeError('local runtime command could not be executed') from None
    if check and result.returncode != 0:
        raise LocalRuntimeError('local runtime command failed; inspect protected Docker logs')
    return result


def _local_docker() -> None:
    result = _run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'])
    if not result.stdout.strip().startswith('unix://'):
        raise LocalRuntimeError('complete local runtime requires the local Docker Unix socket')


def _request_json(url: str, *, method='GET', payload=None, headers=None):
    request_headers = {'Accept': 'application/json', **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(',', ':')).encode()
        request_headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
            if response.status < 200 or response.status >= 300 or len(raw) > 1024 * 1024:
                raise LocalRuntimeError('local bootstrap endpoint returned an invalid response')
    except urllib.error.HTTPError as error:
        raise LocalRuntimeError(f'local bootstrap endpoint rejected the request ({error.code})') from None
    except (OSError, urllib.error.URLError, TimeoutError):
        raise LocalRuntimeError('local bootstrap endpoint is unavailable') from None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise LocalRuntimeError('local bootstrap endpoint returned invalid JSON') from None
    return value


def _basic(username: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': 'Basic ' + encoded}


def _bootstrap_miniflux(store: SecretStore, port: int) -> int:
    base = f'http://127.0.0.1:{port}/v1/'
    admin_password = store.read('rss-engine-admin-password')
    collector_password = store.read('rss-collector-password')
    admin = _basic('newshub-engine-admin', admin_password)
    users = _request_json(base + 'users', headers=admin)
    if not isinstance(users, list):
        raise LocalRuntimeError('Miniflux user inventory is invalid')
    matches = [row for row in users if isinstance(row, dict) and row.get('username') == 'newshub-collector']
    if len(matches) > 1:
        raise LocalRuntimeError('Miniflux collector identity is ambiguous')
    if matches:
        collector = matches[0]
    else:
        collector = _request_json(base + 'users', method='POST', headers=admin, payload={
            'username': 'newshub-collector', 'password': collector_password, 'is_admin': False,
        })
    account = collector.get('id') if isinstance(collector, dict) else None
    if type(account) is not int or account <= 1 or collector.get('is_admin') is not False:
        raise LocalRuntimeError('Miniflux collector identity is invalid')

    existing = store.read('rss-engine-token')
    if existing != PENDING:
        me = _request_json(base + 'me', headers={'X-Auth-Token': existing})
        if not isinstance(me, dict) or me.get('id') != account or me.get('is_admin') is not False:
            raise LocalRuntimeError('existing Miniflux collector token is invalid')
        return account
    token = _request_json(base + 'api-keys', method='POST',
                          headers=_basic('newshub-collector', collector_password),
                          payload={'description': 'NewsHub local RSS collector'})
    value = token.get('token') if isinstance(token, dict) else None
    if not isinstance(value, str) or not value or len(value) > 65536:
        raise LocalRuntimeError('Miniflux did not return a valid collector token')
    store.replace_pending('rss-engine-token', value)
    return account


def _bootstrap_ai_gateway(store: SecretStore, compose: list[str], environment) -> None:
    result = _run(compose + ['exec', '-T', 'ai-gateway', 'python', '/app/local-bootstrap.py'],
                  environment=environment, timeout=60)
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise LocalRuntimeError('AI gateway bootstrap returned invalid JSON') from None
    if not isinstance(payload, dict) or payload.get('status') not in {'created', 'reused'}:
        raise LocalRuntimeError('AI gateway bootstrap returned an invalid status')
    if payload['status'] == 'created':
        key = payload.get('key')
        if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,256}', key):
            raise LocalRuntimeError('AI gateway did not return a valid project key')
        store.replace_pending('ai-project-key', key)


def _write_runtime_env(path: Path, *, values: dict[str, str]) -> None:
    if path.is_symlink():
        raise LocalRuntimeError('runtime environment file must not be a symlink')
    lines = []
    for name, value in sorted(values.items()):
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name) or any(char in value for char in '\r\n'):
            raise LocalRuntimeError('runtime environment value is invalid')
        lines.append(name + '=' + value)
    temporary = path.with_name('.' + path.name + '.new')
    if temporary.exists() or temporary.is_symlink():
        raise LocalRuntimeError('runtime environment staging path is occupied')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise LocalRuntimeError('could not write runtime environment') from None


def _previous_runtime(project: str):
    identities = _run(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}',
                       '--filter', 'label=com.docker.compose.service=app']).stdout.split()
    if len(identities) != 1 or not re.fullmatch(r'[0-9a-f]{12,64}', identities[0]):
        raise LocalRuntimeError('expected exactly one existing local app container')
    try:
        inspected = json.loads(_run(['docker', 'inspect', identities[0]]).stdout)[0]
        labels = inspected['Config']['Labels']
        files = tuple(Path(item).resolve(strict=True)
                      for item in labels['com.docker.compose.project.config_files'].split(','))
        image = inspected['Config']['Image']
        backend = next(Path(item['Source']) for item in inspected['Mounts']
                       if item['Destination'] == '/app/backend' and item['Type'] == 'bind')
    except (ValueError, KeyError, IndexError, StopIteration, OSError, TypeError):
        raise LocalRuntimeError('existing local app metadata is invalid') from None
    source = backend.parent.resolve(strict=True)
    if backend != source / 'backend' or any(not path.is_absolute() or path.is_symlink() for path in files):
        raise LocalRuntimeError('existing local app paths are unsafe')
    return files, image, source


def _running_services(project: str) -> tuple[str, ...]:
    result = _run([
        'docker', 'ps', '--filter', f'label=com.docker.compose.project={project}',
        '--format', '{{.Label "com.docker.compose.service"}}',
    ])
    names = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    if ('app' not in names or len(set(names)) != len(names)
            or any(name not in REQUIRED_SERVICES for name in names)):
        raise LocalRuntimeError('existing local running service set is invalid')
    return tuple(name for name in REQUIRED_SERVICES if name in names)


def _backup_sqlite(source_root: Path, backup_root: Path) -> Path | None:
    source = source_root / 'backend/db.sqlite3'
    if not source.is_file() or source.is_symlink():
        return None
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_root.is_symlink() or backup_root.stat().st_mode & 0o077:
        raise LocalRuntimeError('backup directory must be a private real directory')
    target = backup_root / ('db-before-full-runtime-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.sqlite3')
    try:
        with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as original, sqlite3.connect(target) as copy:
            original.execute('PRAGMA query_only=ON')
            original.backup(copy)
        target.chmod(0o600)
    except (OSError, sqlite3.Error):
        raise LocalRuntimeError('could not create the SQLite rollback backup') from None
    return target


def _seed_secrets(store: SecretStore) -> dict[str, Path]:
    paths = {
        'translation': store.ensure('translation-redis-password', lambda: secrets.token_hex(32)),
        'rss_pg': store.ensure('rss-pg-password', lambda: secrets.token_hex(32)),
        'rss_admin': store.ensure('rss-engine-admin-password', lambda: secrets.token_hex(32)),
        'rss_collector': store.ensure('rss-collector-password', lambda: secrets.token_hex(32)),
        'rss_token': store.ensure('rss-engine-token', lambda: PENDING),
        'ai_pg': store.ensure('ai-gateway-postgres-password', lambda: secrets.token_hex(32)),
        'master': store.ensure('litellm-master-key', lambda: 'sk-' + secrets.token_hex(32)),
        'salt': store.ensure('litellm-salt-key', lambda: secrets.token_hex(32)),
        'project': store.ensure('ai-project-key', lambda: PENDING),
        'instance': store.ensure('rss-engine-instance', lambda: str(uuid.uuid4())),
    }
    rss_url = 'postgres://miniflux:' + urllib.parse.quote(store.read('rss-pg-password'), safe='') + '@rss-db/miniflux?sslmode=disable'
    paths['rss_url'] = store.ensure('rss-database-url', lambda: rss_url)
    return paths


def _environment(*, source_root: Path, image: str, store: SecretStore,
                 paths: dict[str, Path], account: int, activation_paused: bool) -> dict[str, str]:
    password = urllib.parse.quote(store.read('translation-redis-password'), safe='')
    return {
        'NEWSHUB_IMAGE': image,
        'NEWSHUB_SOURCE_ROOT': str(source_root),
        'RSS_ENGINE_INSTANCE_UUID': store.read('rss-engine-instance'),
        'RSS_ENGINE_ACCOUNT_ID': str(account),
        'RSS_ENGINE_PORT': '18080',
        'TRANSLATION_REDIS_URL': f'redis://:{password}@127.0.0.1:6379/0',
        'TRANSLATION_REDIS_PASSWORD_FILE': str(paths['translation']),
        'RSS_PG_PASSWORD_FILE': str(paths['rss_pg']),
        'RSS_DATABASE_URL_FILE': str(paths['rss_url']),
        'RSS_ENGINE_ADMIN_PASSWORD_FILE': str(paths['rss_admin']),
        'RSS_ENGINE_TOKEN_FILE': str(paths['rss_token']),
        'AI_GATEWAY_POSTGRES_PASSWORD_FILE': str(paths['ai_pg']),
        'LITELLM_MASTER_KEY_FILE': str(paths['master']),
        'LITELLM_SALT_KEY_FILE': str(paths['salt']),
        'AI_BYOK_GATEWAY_PROJECT_KEY_FILE': str(paths['project']),
        'NEWSHUB_ACTIVATION_PAUSED': '1' if activation_paused else '0',
        'MINIFLUX_DISABLE_SCHEDULER': '1' if activation_paused else '0',
    }


def _private_directory(path: Path) -> None:
    if path.is_symlink():
        raise LocalRuntimeError('runtime state directory must be a real private directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise LocalRuntimeError('runtime state directory must be owner-controlled')
        path.chmod(0o700)
    except OSError:
        raise LocalRuntimeError('runtime state directory is unavailable') from None


def _copy_release_file(source: Path, target: Path) -> Path:
    if not source.is_file() or source.is_symlink():
        raise LocalRuntimeError('release source must be a regular file')
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with source.open('rb') as incoming, os.fdopen(descriptor, 'wb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except OSError:
        raise LocalRuntimeError('could not preserve the candidate runtime definition') from None
    return target


def _previous_activation(runtime_root: Path, *, project: str, source_root: Path,
                         image: str, detected_compose: tuple[Path, ...],
                         detected_services: tuple[str, ...]):
    path = runtime_root / 'last-activation.json'
    if not path.exists() and not path.is_symlink():
        return detected_compose, None, detected_services, detected_compose
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 1024 * 1024):
            raise ValueError
        value = json.loads(path.read_text(encoding='utf-8'))
        if (value.get('schema_version') != 2 or value.get('project') != project
                or value.get('source_root') != str(source_root)
                or value.get('image') != image):
            raise ValueError
        compose_files = tuple(Path(item) for item in value['compose_files'])
        base_files = tuple(Path(item) for item in value['base_compose_files'])
        env_file = Path(value['env_file'])
        services = tuple(value['services'])
        env_info = env_file.stat()
        if (not compose_files or not base_files or not services
                or compose_files != detected_compose
                or any(not item.is_absolute() or not item.is_file() or item.is_symlink()
                       for item in (*compose_files, *base_files, env_file))
                or env_info.st_uid != os.getuid() or env_info.st_mode & 0o077
                or len(set(services)) != len(services)
                or not {'app', 'indexer'}.issubset(services)
                or any(item not in services for item in detected_services)
                or any(item not in REQUIRED_SERVICES for item in services)):
            raise ValueError
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        raise LocalRuntimeError('previous activation receipt is invalid; refusing unsafe replacement') from None
    return compose_files, env_file, detected_services, base_files


def _restore_previous_runtime(commands: ActivationCommands, *, current_environment,
                              rollback_environment, wait_timeout: int) -> None:
    stop_failed = False
    try:
        stopped = _run(commands.stop_new, environment=current_environment,
                       timeout=180, check=False)
        stop_failed = stopped.returncode != 0
    except LocalRuntimeError:
        stop_failed = True
    rollback_failed = False
    try:
        rollback = _run(commands.rollback, environment=rollback_environment,
                        timeout=wait_timeout + 180, check=False)
        rollback_failed = rollback.returncode != 0
    except LocalRuntimeError:
        rollback_failed = True
    if stop_failed or rollback_failed:
        raise LocalRuntimeError(
            'activation failed and previous runtime restoration is incomplete; inspect protected Docker logs'
        )


def _write_receipt(path: Path, value: dict[str, object]) -> None:
    if path.is_symlink():
        raise LocalRuntimeError('activation receipt must not be a symlink')
    temporary = path.with_name('.' + path.name + '.new')
    if temporary.exists() or temporary.is_symlink():
        raise LocalRuntimeError('activation receipt staging path is occupied')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise LocalRuntimeError('could not write the activation receipt') from None


def _execute(*, project: str, source_root: Path, runtime_root: Path, image: str,
             wait_timeout: int, complete_overlay: Path) -> dict[str, object]:
    _local_docker()
    detected_compose, current_image, current_source = _previous_runtime(project)
    detected_services = _running_services(project)
    if source_root != current_source:
        raise LocalRuntimeError('source root differs from the running local database owner')
    require_immutable_image(image)
    _run(['docker', 'image', 'inspect', image])
    _private_directory(runtime_root)
    releases = runtime_root / 'releases'
    _private_directory(releases)
    previous, previous_env_file, previous_services, base_compose = _previous_activation(
        runtime_root, project=project, source_root=source_root, image=current_image,
        detected_compose=detected_compose, detected_services=detected_services,
    )
    release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex
    release_overlay = _copy_release_file(
        complete_overlay, releases / ('compose-local-full-' + release_id + '.yaml'))
    store = SecretStore(runtime_root / 'secrets')
    paths = _seed_secrets(store)
    env_file = releases / ('runtime-' + release_id + '.env')
    values = _environment(source_root=source_root, image=image, store=store, paths=paths,
                          account=2, activation_paused=True)
    _write_runtime_env(env_file, values=values)
    compose_files = (*base_compose, release_overlay)
    commands = activation_commands(project=project, compose_files=compose_files,
                                  previous_compose=previous, current_env_file=env_file,
                                  previous_env_file=previous_env_file,
                                  previous_services=previous_services,
                                  wait_timeout=wait_timeout)
    compose = _compose(project, compose_files, env_file)
    environment = {**os.environ, **values}
    _run(compose + ['config', '--quiet'], environment=environment)
    images = _run(compose + ['config', '--images'], environment=environment).stdout.splitlines()
    for candidate in sorted(set(filter(None, images))):
        _run(['docker', 'image', 'inspect', candidate])
    backup = _backup_sqlite(source_root, runtime_root / 'backups')
    previous_environment = os.environ.copy()
    if previous_env_file is not None:
        for name in values:
            previous_environment.pop(name, None)
    changed = False
    try:
        # `compose up --wait` may have replaced some containers before it
        # reports a later health failure, so rollback authority begins before
        # the first mutating Docker command is dispatched.
        changed = True
        if commands.quiesce is not None:
            _run(commands.quiesce, environment=previous_environment, timeout=180)
        _run(commands.infrastructure, environment=environment, timeout=wait_timeout + 180)
        account = _bootstrap_miniflux(store, 18080)
        _bootstrap_ai_gateway(store, compose, environment)
        values = _environment(source_root=source_root, image=image, store=store, paths=paths,
                              account=account, activation_paused=True)
        _write_runtime_env(env_file, values=values)
        environment = {**os.environ, **values}
        _run(commands.preflight, environment=environment, timeout=wait_timeout + 180)
        values = _environment(source_root=source_root, image=image, store=store, paths=paths,
                              account=account, activation_paused=False)
        _write_runtime_env(env_file, values=values)
        environment = {**os.environ, **values}
        _run(commands.full, environment=environment, timeout=wait_timeout + 180)
        health_result = _run(commands.verify, environment=environment, timeout=60)
        snapshot = require_full_health(json.loads(health_result.stdout.splitlines()[-1]))
    except Exception as activation_error:
        if changed:
            try:
                _restore_previous_runtime(
                    commands, current_environment=environment,
                    rollback_environment=previous_environment, wait_timeout=wait_timeout)
            except LocalRuntimeError as rollback_error:
                raise rollback_error from activation_error
        raise
    receipt = {
        'schema_version': 2,
        'project': project,
        'image': image,
        'previous_image': current_image,
        'source_root': str(source_root),
        'services': list(REQUIRED_SERVICES),
        'compose_files': [str(path) for path in compose_files],
        'base_compose_files': [str(path) for path in base_compose],
        'env_file': str(env_file),
        'business_io_released': True,
        'health': {name: snapshot['checks'][name]['status'] for name in REQUIRED_HEALTH_CHECKS},
        'backup': str(backup) if backup else '',
        'activated_at': datetime.now(timezone.utc).isoformat(),
    }
    receipt_path = runtime_root / 'last-activation.json'
    _write_receipt(receipt_path, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--project', default='newshub-local-main')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--image')
    parser.add_argument('--wait-timeout', type=int, default=300)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if not PROJECT_RE.fullmatch(args.project):
        raise LocalRuntimeError('project must be an explicit newshub-local-* name')
    if not 30 <= args.wait_timeout <= 1200:
        raise LocalRuntimeError('wait timeout must be between 30 and 1200 seconds')
    script_root = Path(__file__).resolve().parents[2]
    source_root = (args.source_root or script_root).resolve(strict=True)
    runtime_root = (args.runtime_root or Path.home() / '.local/share' / args.project).absolute()
    image = args.image
    if image is None:
        if not args.execute:
            raise LocalRuntimeError('--image is required for a side-effect-free preview')
        _previous, image, detected = _previous_runtime(args.project)
        if args.source_root is None:
            source_root = detected
    base_compose = source_root / 'compose.yaml'
    complete_overlay = script_root / 'compose.local-full.yaml'
    if not base_compose.is_file() or base_compose.is_symlink():
        raise LocalRuntimeError('source root is missing compose.yaml')
    if not complete_overlay.is_file() or complete_overlay.is_symlink():
        raise LocalRuntimeError('implementation is missing compose.local-full.yaml')
    require_immutable_image(image)
    preview = {
        'execute': args.execute,
        'project': args.project,
        'image': image,
        'source_root': str(source_root),
        'runtime_root': str(runtime_root),
        'required_services': list(REQUIRED_SERVICES),
    }
    if not args.execute:
        print(json.dumps(preview, sort_keys=True))
        return 0
    receipt = _execute(project=args.project, source_root=source_root, runtime_root=runtime_root,
                       image=image, wait_timeout=args.wait_timeout,
                       complete_overlay=complete_overlay)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except LocalRuntimeError as error:
        print('local-full-runtime: ' + str(error), file=sys.stderr)
        raise SystemExit(2) from None
