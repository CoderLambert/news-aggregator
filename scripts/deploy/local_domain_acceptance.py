#!/usr/bin/env python3
"""G1/G2 acceptance checks for the isolated news.lambert.host smoke stack."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import importlib.metadata
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


HOST = 'news.lambert.host'
PLAYWRIGHT_VERSION = '1.62.0'
STATUS_MARKER = '\n__NEWSHUB_HTTP_STATUS__='
CONTAINER_ID_PATTERN = re.compile(r'[a-f0-9]{64}')
IMAGE_ID_PATTERN = re.compile(r'sha256:[a-f0-9]{64}')
FORWARDED_SPOOF_HEADERS = (
    'X-Forwarded-Proto: http',
    'X-Forwarded-For: 198.51.100.44',
    'Forwarded: proto=http;host=spoof.invalid',
    'X-Forwarded-Host: spoof.invalid',
    'X-Forwarded-Port: 80',
)
SSE_PROXY_HEADER_MARKER = b'data: proxy-headers='
FIXTURE_MODULE_PATH = Path(__file__).with_name('local_domain_fixtures.py')
FIXTURE_SPEC = importlib.util.spec_from_file_location('local_domain_fixtures', FIXTURE_MODULE_PATH)
_fixtures = importlib.util.module_from_spec(FIXTURE_SPEC)
assert FIXTURE_SPEC.loader is not None
FIXTURE_SPEC.loader.exec_module(_fixtures)


class AcceptanceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        source_check_name: str | None = None,
        expected_http_status: int | None = None,
        actual_http_status: int | None = None,
    ):
        super().__init__(message)
        self.source_check_name = source_check_name
        self.expected_http_status = expected_http_status
        self.actual_http_status = actual_http_status


class CleanupAcceptanceError(AcceptanceError):
    """An acceptance failure that must remain visible as a cleanup failure."""

    cleanup_status = 'FAIL'


SAFE_FIXTURE_EXCEPTION_TYPES = frozenset({
    'ImproperlyConfigured', 'OperationalError', 'IntegrityError',
    'ValueError', 'TypeError', 'KeyError', 'FixtureExecutionError',
    'AcceptanceError', 'OSError', 'JSONDecodeError',
})


class FixtureProgramError(AcceptanceError):
    """Safe summary of a failed in-container fixture program."""

    def __init__(self, safe_exception_type: str):
        self.safe_exception_type = (
            safe_exception_type
            if isinstance(safe_exception_type, str)
            and safe_exception_type in SAFE_FIXTURE_EXCEPTION_TYPES
            else 'FixtureExecutionError'
        )
        super().__init__('private G2 fixture program failed')


def _safe_exception_type(exc: BaseException) -> str:
    supplied = getattr(exc, 'safe_exception_type', None)
    if isinstance(supplied, str) and supplied in SAFE_FIXTURE_EXCEPTION_TYPES:
        return supplied
    name = type(exc).__name__
    return name if name in SAFE_FIXTURE_EXCEPTION_TYPES else 'AcceptanceError'


def _g2_failure_report(check: str, exc: BaseException) -> dict:
    failure = {
        'stage': 'g2', 'check': check,
        'exception_type': _safe_exception_type(exc),
    }
    child_type = getattr(exc, 'safe_exception_type', None)
    if isinstance(child_type, str) and child_type in SAFE_FIXTURE_EXCEPTION_TYPES:
        failure['child_exception_type'] = child_type
    failure.update(_safe_http_failure_details(exc))
    return {'stage': 'g2', 'status': 'FAIL', 'failure': failure}


def _safe_http_failure_details(exc: BaseException) -> dict[str, str | int]:
    check_name = getattr(exc, 'source_check_name', None)
    expected = getattr(exc, 'expected_http_status', None)
    actual = getattr(exc, 'actual_http_status', None)
    if (
        isinstance(check_name, str)
        and re.fullmatch(r'[a-z0-9_.]{1,80}', check_name) is not None
        and type(expected) is int and 0 <= expected <= 599
        and type(actual) is int and 0 <= actual <= 599
    ):
        return {
            'source_check_name': check_name,
            'expected_http_status': expected,
            'actual_http_status': actual,
        }
    return {}


def _write_safe_report(path: Path | None, payload: dict) -> None:
    if path is None:
        raise AcceptanceError('G2 setup and seed reports are required')
    _private_write(path, json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _load_fixture_bundle(path: Path) -> dict:
    try:
        return _fixtures.load_bundle(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AcceptanceError('private G2 fixture bundle failed validation') from exc


def _read_fixture_state(args: argparse.Namespace) -> dict:
    _require(args.fixture_state.is_file() and not args.fixture_state.is_symlink(), 'private fixture state is missing')
    info = args.fixture_state.stat(follow_symlinks=False)
    _require(stat.S_IMODE(info.st_mode) == 0o600, 'private fixture state must remain mode 0600')
    _require(info.st_uid == os.getuid(), 'private fixture state must be owned by the smoke user')
    try:
        state = json.loads(args.fixture_state.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError('private G2 fixture state is invalid') from exc
    _require(state.get('ok') is True and isinstance(state.get('news_id'), int), 'private G2 fixture state is incomplete')
    return state


def _docker_compose_container_id(args: argparse.Namespace, service: str) -> str:
    command = [
        'docker', 'compose', '--project-name', args.compose_project,
        '--file', str(args.compose_file), '--env-file', str(args.compose_env),
        'ps', '-q', service,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    _require(result.returncode == 0, f'could not resolve the G2 {service} container')
    ids = [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]
    _require(
        len(ids) == 1 and CONTAINER_ID_PATTERN.fullmatch(ids[0]) is not None,
        f'G2 Compose project did not resolve exactly one {service} container ID',
    )
    return ids[0]


def _docker_inspect_object(command: list[str], description: str) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    _require(result.returncode == 0, f'could not inspect the G2 {description}')
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f'G2 {description} inspection returned invalid JSON') from exc
    _require(
        isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict),
        f'G2 {description} inspection did not return one object',
    )
    return payload[0]


def _inspect_g2_container(container_id: str, description: str) -> dict:
    return _docker_inspect_object(
        ['docker', 'inspect', '--type', 'container', container_id], description,
    )


def _require_compose_identity(container: dict, container_id: str, args: argparse.Namespace, service: str) -> None:
    _require(
        str(container.get('Id', '')).lower() == container_id,
        f'G2 {service} inspection returned a different container ID',
    )
    config = container.get('Config')
    labels = config.get('Labels') if isinstance(config, dict) else None
    _require(
        isinstance(labels, dict)
        and labels.get('com.docker.compose.project') == args.compose_project
        and labels.get('com.docker.compose.service') == service,
        f'G2 {service} Compose ownership labels do not match this smoke project',
    )
    _require(
        isinstance(container.get('State'), dict) and container['State'].get('Running') is True,
        f'G2 {service} container is not running',
    )


def _inspect_g2_gateway(args: argparse.Namespace) -> dict[str, str]:
    gateway_id = _docker_compose_container_id(args, 'gateway')
    if args.gateway_container_id is not None:
        _require(
            args.gateway_container_id.lower() == gateway_id,
            'G2 gateway ID does not match this Compose project',
        )
    gateway = _inspect_g2_container(gateway_id, 'gateway container')
    _require_compose_identity(gateway, gateway_id, args, 'gateway')
    _require(
        gateway.get('Image') == args.gateway_image_id,
        'G2 gateway is not running the expected immutable image ID',
    )
    network_settings = gateway.get('NetworkSettings')
    _require(isinstance(network_settings, dict), 'G2 gateway network settings are invalid')
    ports = network_settings.get('Ports') or {}
    _require(
        isinstance(ports, dict) and all(not bindings for bindings in ports.values()),
        'G2 gateway has a published host port',
    )
    expected_network = f'{args.compose_project}_isolated'
    networks = network_settings.get('Networks')
    _require(
        isinstance(networks, dict)
        and set(networks) == {expected_network}
        and isinstance(networks.get(expected_network), dict),
        'G2 gateway is not attached only to this smoke internal network',
    )
    network_id = networks[expected_network].get('NetworkID')
    _require(
        isinstance(network_id, str)
        and CONTAINER_ID_PATTERN.fullmatch(network_id.lower()) is not None,
        'G2 gateway network ID is invalid',
    )
    network = _docker_inspect_object(
        ['docker', 'network', 'inspect', network_id], 'internal network',
    )
    labels = network.get('Labels')
    _require(
        network.get('Id') == network_id.lower()
        and network.get('Name') == expected_network
        and network.get('Internal') is True
        and isinstance(labels, dict)
        and labels.get('com.docker.compose.project') == args.compose_project
        and labels.get('com.docker.compose.network') == 'isolated',
        'G2 gateway network is not the owned internal Compose network',
    )
    _require(
        isinstance(gateway.get('HostConfig'), dict)
        and gateway['HostConfig'].get('NetworkMode') == expected_network,
        'G2 gateway is not using its owned internal network mode',
    )
    address = networks[expected_network].get('IPAddress')
    try:
        parsed_address = ipaddress.ip_address(address)
    except (TypeError, ValueError) as exc:
        raise AcceptanceError('G2 gateway has no valid internal IPv4 address') from exc
    _require(
        isinstance(parsed_address, ipaddress.IPv4Address),
        'G2 gateway address must be IPv4',
    )
    return {
        'container_id': gateway_id,
        'network_id': network_id.lower(),
        'ip': str(parsed_address),
    }


def _inspect_g2_app(args: argparse.Namespace, gateway_id: str) -> str:
    app_id = _docker_compose_container_id(args, 'app')
    app = _inspect_g2_container(app_id, 'app container')
    _require_compose_identity(app, app_id, args, 'app')
    app_config = app.get('Config')
    host_config = app.get('HostConfig')
    _require(
        app.get('Image') == args.app_image_id,
        'G2 app is not running the expected immutable image ID',
    )
    _require(
        isinstance(app_config, dict) and app_config.get('User') == '10001:10001',
        'G2 app does not run as UID:GID 10001:10001',
    )
    _require(
        isinstance(host_config, dict) and host_config.get('NetworkMode') == f'container:{gateway_id}',
        'G2 app does not share the exact owned gateway network namespace',
    )
    db_root = Path('/var/lib/newshub/db')
    mounts = app.get('Mounts')
    _require(
        isinstance(mounts, list) and len(mounts) == 1
        and all(isinstance(mount, dict) for mount in mounts),
        'G2 app mount list is invalid',
    )
    db_mount = mounts[0]
    _require(
        db_mount.get('Destination') == str(db_root)
        and db_mount.get('Type') == 'volume'
        and db_mount.get('Name') == f'{args.compose_project}_db-data'
        and db_mount.get('RW') is True,
        'G2 app database mount is not the unique owned named volume',
    )
    volume_name = f'{args.compose_project}_db-data'
    volume = _docker_inspect_object(
        ['docker', 'volume', 'inspect', volume_name], 'database volume',
    )
    volume_labels = volume.get('Labels')
    _require(
        volume.get('Name') == volume_name
        and volume.get('Driver') == 'local'
        and volume.get('Scope') == 'local'
        and volume.get('Options') in (None, {})
        and isinstance(volume_labels, dict)
        and volume_labels.get('com.docker.compose.project') == args.compose_project
        and volume_labels.get('com.docker.compose.volume') == 'db-data',
        'G2 database volume is not the owned local Compose volume',
    )
    return app_id


def _inspect_g2_parents(args: argparse.Namespace) -> dict[str, str]:
    _require(
        IMAGE_ID_PATTERN.fullmatch(args.app_image_id or '') is not None,
        'G2 expected app image ID is invalid',
    )
    _require(
        IMAGE_ID_PATTERN.fullmatch(args.gateway_image_id or '') is not None,
        'G2 expected gateway image ID is invalid',
    )
    gateway = _inspect_g2_gateway(args)
    app_id = _inspect_g2_app(args, gateway['container_id'])
    return {
        'app_container_id': app_id,
        'gateway_container_id': gateway['container_id'],
        'gateway_network_id': gateway['network_id'],
        'gateway_ip': gateway['ip'],
    }


def _store_fixture_state(path: Path, state: dict) -> None:
    if path.is_symlink():
        raise AcceptanceError('refusing to replace a symlink fixture state')
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(temporary, flags, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(state, stream, sort_keys=True)
            stream.write('\n')
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise AcceptanceError('could not update private G2 fixture state') from exc


def _run_fixture_program(args: argparse.Namespace, bundle: dict, phase: str) -> dict:
    program = _fixtures.render_app_program(bundle, phase)
    parents = _inspect_g2_parents(args)
    command = ['docker', 'exec', '-i', parents['app_container_id'], 'python', '-']
    result = subprocess.run(command, input=program, capture_output=True, text=True, check=False)
    nonce = secrets.token_hex(6)
    _private_write(args.private_root / f'fixture-{phase}-{nonce}.stdout', result.stdout)
    _private_write(args.private_root / f'fixture-{phase}-{nonce}.stderr', result.stderr)
    if result.returncode != 0:
        # The source fed on stdin contains private fixture material. Do not
        # include Docker stdout/stderr in the exception, report, or terminal.
        try:
            failure = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            failure = None
        safe_type = (
            failure.get('error_type')
            if isinstance(failure, dict)
            and set(failure) == {'ok', 'error_type'}
            and failure.get('ok') is False
            else 'FixtureExecutionError'
        )
        raise FixtureProgramError(safe_type)
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f'private G2 fixture phase {phase} returned invalid JSON') from exc
    _require(isinstance(payload, dict) and payload.get('ok') is True, f'private G2 fixture phase {phase} was refused')
    return payload


def _run_checked(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        raise AcceptanceError(f"command failed: {Path(command[0]).name} (exit {result.returncode})")
    return result


def _curl_command(args: argparse.Namespace, path: str, *, scheme: str = 'https', port: int | None = None,
                  method: str = 'GET', headers: tuple[str, ...] = (), body: str | None = None,
                  header_file: Path | None = None, request_target: str | None = None) -> list[str]:
    resolved_port = port or (443 if scheme == 'https' else 80)
    curl = shutil.which('curl')
    _require(curl is not None, 'curl is required for local G1 HTTP checks')
    command = [
        curl,
        '--disable',
        '--noproxy', '*',
        '--silent',
        '--show-error',
        '--connect-timeout', '3',
        '--max-time', '12',
        '--resolve', f'{HOST}:{resolved_port}:{args.gateway_ip}',
        '--write-out', STATUS_MARKER + '%{http_code}',
    ]
    if scheme == 'https':
        command.extend(['--cacert', str(args.ca_cert)])
    if header_file is not None:
        command.extend(['--dump-header', str(header_file)])
    if method != 'GET':
        command.extend(['--request', method])
    for header in headers:
        command.extend(['--header', header])
    if body is not None:
        command.extend(['--data-binary', body])
    if request_target is not None:
        command.extend(['--request-target', request_target])
    command.append(f'{scheme}://{HOST}:{resolved_port}{path}')
    return command


def _curl(args: argparse.Namespace, path: str, **kwargs) -> tuple[int, str, subprocess.CompletedProcess]:
    result = subprocess.run(
        _curl_command(args, path, **kwargs),
        capture_output=True,
        text=True,
        check=False,
    )
    body, marker, raw_status = result.stdout.rpartition(STATUS_MARKER)
    _require(bool(marker), 'curl did not return an HTTP status code')
    try:
        status = int(raw_status)
    except ValueError as exc:
        raise AcceptanceError('curl returned an invalid HTTP status code') from exc
    if result.returncode != 0 and status != 0:
        raise AcceptanceError(f'curl request failed (exit {result.returncode})')
    return status, body, result


def _curl_closed_without_http_response(result: subprocess.CompletedProcess, *, scheme: str) -> bool:
    """Accept only the expected connection-close curl codes with no HTTP response."""
    allowed_exit_codes = {'http': {52}, 'https': {52, 56}}
    if result.returncode not in allowed_exit_codes.get(scheme, set()):
        return False
    output_body, marker, status = result.stdout.rpartition(STATUS_MARKER)
    if not marker or status != '000' or output_body:
        return False
    if re.search(r'(?m)^HTTP/\d(?:\.\d)?\s+\d{3}\b', result.stdout):
        return False
    return True


def _headers(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding='iso-8859-1').splitlines():
        if ':' not in line:
            continue
        name, value = line.split(':', 1)
        result.setdefault(name.strip().lower(), []).append(value.strip())
    return result


def _expect_status(args: argparse.Namespace, checks: dict[str, str], name: str, path: str,
                   expected: int, **kwargs) -> tuple[str, dict[str, list[str]]]:
    header_file = kwargs.pop('header_file', None)
    status, body, _ = _curl(args, path, header_file=header_file, **kwargs)
    if status != expected:
        raise AcceptanceError(
            f'{name} expected HTTP {expected}, got {status}',
            source_check_name=name,
            expected_http_status=expected,
            actual_http_status=status,
        )
    checks[name] = f'HTTP {status}'
    return body, _headers(header_file) if header_file is not None else {}


def _require_secure_csrf_cookie(response_headers: dict[str, list[str]]) -> None:
    cookie_values = response_headers.get('set-cookie', [])
    csrf_cookie = next((value for value in cookie_values if value.lower().startswith('csrftoken=')), None)
    _require(csrf_cookie is not None, 'CSRF cookie was not set')
    cookie_attributes = {part.strip().lower() for part in csrf_cookie.split(';')[1:]}
    _require('secure' in cookie_attributes, 'CSRF cookie is missing Secure')
    _require('httponly' not in cookie_attributes, 'CSRF cookie must remain readable by the SPA')
    _require(not any(part.startswith('domain=') for part in cookie_attributes), 'CSRF cookie must be host-only')
    _require('samesite=lax' in cookie_attributes, 'CSRF cookie must use SameSite=Lax')


def _check_forwarded_header_secure_request(
    args: argparse.Namespace,
    checks: dict[str, str],
    work_dir: Path,
) -> None:
    csrf_body, response_headers = _expect_status(
        args,
        checks,
        'real_django_secure_request',
        '/api/auth/csrf/',
        200,
        headers=FORWARDED_SPOOF_HEADERS,
        header_file=work_dir / 'csrf-forwarded.headers',
    )
    _require('csrfToken' in csrf_body, 'spoofed-forwarding CSRF response is missing its token')
    _require_secure_csrf_cookie(response_headers)
    checks['real_django_secure_request'] = (
        'HTTP 200 on non-exempt CSRF path; no HTTPS redirect; Secure host-only CSRF cookie'
    )
    checks['real_client_address_observation'] = (
        'NOT_RUN: this Django endpoint does not expose WSGI REMOTE_ADDR'
    )


def _private_write(path: Path, content: str | bytes) -> None:
    if path.exists() or path.is_symlink():
        raise AcceptanceError('refusing to overwrite an existing private rate fixture')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        if isinstance(content, bytes):
            stream_context = os.fdopen(fd, 'wb')
        else:
            stream_context = os.fdopen(fd, 'w', encoding='utf-8')
        with stream_context as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
    except OSError as exc:
        raise AcceptanceError('could not create private rate fixture') from exc


def _curl_config_quote(value: str) -> str:
    return json.dumps(value)


def _read_rate_sidecar_cidfile(cidfile: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(cidfile, flags)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.getuid(),
                'G2 sidecar CID ledger is not a private smoke-owned regular file',
            )
            raw = stream.read(130)
    except OSError as exc:
        raise AcceptanceError('G2 sidecar CID ledger is missing or unsafe') from exc
    try:
        content = raw.decode('ascii')
    except UnicodeDecodeError as exc:
        raise AcceptanceError('G2 sidecar CID ledger is invalid') from exc
    candidate = content[:-1] if content.endswith('\n') else content
    _require(
        candidate == candidate.strip()
        and CONTAINER_ID_PATTERN.fullmatch(candidate) is not None,
        'G2 sidecar CID ledger does not contain one full container ID',
    )
    return candidate


def _write_rate_request(
    root: Path,
    name: str,
    *,
    interface: str,
    path: str,
    cookie_path: str,
    body: dict | None = None,
    csrf_token: str | None = None,
    origin: str = f'https://{HOST}',
    spoof_xff: bool = False,
) -> Path:
    output = f'/smoke/output/{name}.body'
    headers = f'/smoke/output/{name}.headers'
    lines = [
        'silent', 'show-error', 'connect-timeout = 3', 'max-time = 10',
        f'resolve = {_curl_config_quote(f"{HOST}:443:127.0.0.1")}',
        f'interface = {_curl_config_quote(interface)}',
        'cacert = "/smoke/ca.crt"',
        f'cookie = {_curl_config_quote(f"/smoke/output/{cookie_path}")}',
        f'cookie-jar = {_curl_config_quote(f"/smoke/output/{cookie_path}")}',
        f'dump-header = {_curl_config_quote(headers)}',
        f'output = {_curl_config_quote(output)}',
        f'url = {_curl_config_quote(f"https://{HOST}{path}")}',
    ]
    if body is not None:
        body_path = root / f'{name}.json'
        _private_write(body_path, json.dumps(body, ensure_ascii=False, separators=(',', ':')))
        lines.extend([
            'request = "POST"',
            'header = "Content-Type: application/json"',
            f'header = {_curl_config_quote(f"Origin: {origin}")}',
            f'data-binary = {_curl_config_quote(f"@/smoke/rate/{name}.json")}',
        ])
        if csrf_token is not None:
            lines.append(f'header = {_curl_config_quote(f"X-CSRFToken: {csrf_token}")}')
        if spoof_xff:
            lines.append('header = "X-Forwarded-For: 198.51.100.44"')
    config_path = root / f'{name}.curlrc'
    _private_write(config_path, '\n'.join(lines) + '\n')
    return config_path


def _run_rate_sidecar(args: argparse.Namespace, interface: str, requests: list[tuple[str, Path]]) -> dict[str, int]:
    rate_root = args.private_root / 'rate'
    output_root = rate_root / 'output'
    _require(
        rate_root.is_dir() and stat.S_IMODE(rate_root.stat().st_mode) == 0o700,
        'G2 rate fixture root must remain mode 0700',
    )
    _require(
        output_root.is_dir() and stat.S_IMODE(output_root.stat().st_mode) == 0o700,
        'G2 rate output root must remain mode 0700',
    )
    gateway = _inspect_g2_gateway(args)
    owner = f'org.newshub.local-domain.owner={args.compose_project}'
    suffix = secrets.token_hex(5)
    safe_ip = interface.rsplit('.', 1)[-1]
    name = f'nhsmoke-rate-{safe_ip}-{suffix}'
    cidfile = rate_root / f'{name}.cid'
    exists = subprocess.run(
        ['docker', 'inspect', '--type', 'container', name],
        capture_output=True, check=False,
    )
    _require(exists.returncode != 0, 'random G2 sidecar container name is already in use')
    for _marker, config_path in requests:
        _require(
            not config_path.is_symlink()
            and config_path.resolve(strict=True).is_relative_to(rate_root.resolve(strict=True))
            and stat.S_IMODE(config_path.stat(follow_symlinks=False).st_mode) == 0o600,
            'G2 sidecar request config must be a private smoke-owned file',
        )
    script = ['set -eu', 'umask 077']
    for marker, config_path in requests:
        relative = config_path.name
        script.append(
            f"status=\"$(curl --config /smoke/rate/{shlex.quote(relative)} --write-out '%{{http_code}}')\""
        )
        script.append(f"printf '%s=%s\\n' {shlex.quote(marker)} \"$status\"")
    script_path = rate_root / f'run-{safe_ip}-{suffix}.sh'
    _private_write(script_path, '\n'.join(script) + '\n')
    command = [
        'docker', 'create', '--pull=never', '--name', name,
        '--label', owner,
        '--cidfile', str(cidfile),
        '--network', f'container:{gateway["container_id"]}',
        '--user', f'{os.getuid()}:{os.getgid()}',
        '--read-only', '--tmpfs', '/tmp:rw,nosuid,noexec,size=16m',
        '--mount', f'type=bind,source={args.ca_cert.resolve(strict=True)},target=/smoke/ca.crt,readonly',
        '--mount', f'type=bind,source={rate_root.resolve(strict=True)},target=/smoke/rate,readonly',
        '--mount', f'type=bind,source={output_root.resolve(strict=True)},target=/smoke/output',
        '--entrypoint', '/bin/sh', args.curl_image_id,
        f'/smoke/rate/{script_path.name}',
    ]
    # Keep a validated CID in memory once its exact container identity has
    # passed inspect. Later cleanup never depends on the mutable CID file.
    container_id: str | None = None
    statuses: dict[str, int] | None = None
    failure: AcceptanceError | None = None
    cleanup_failure: AcceptanceError | None = None
    ledger_failure: AcceptanceError | None = None
    create_may_have_created = False
    active_operation = 'create'
    try:
        old_umask = os.umask(0o077)
        try:
            create_result = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False,
            )
        finally:
            os.umask(old_umask)
        if create_result.returncode != 0:
            create_may_have_created = cidfile.exists() or cidfile.is_symlink()
            raise AcceptanceError(f'G2 rate sidecar create failed (exit {create_result.returncode})')
        create_may_have_created = True
        _require(
            cidfile.exists() or cidfile.is_symlink(),
            'G2 sidecar CID ledger is missing',
        )
        ledger_id = _read_rate_sidecar_cidfile(cidfile)
        stdout_ids = [line.strip().lower() for line in create_result.stdout.splitlines() if line.strip()]
        container = _inspect_g2_container(ledger_id, 'rate sidecar container')
        _validate_rate_sidecar_identity(container, ledger_id, args, gateway['container_id'], require_stopped=True)
        container_id = ledger_id
        _require(stdout_ids == [container_id], 'G2 sidecar create ID did not match its CID ledger')
        active_operation = 'start'
        start_result = subprocess.run(
            ['docker', 'start', '--attach', container_id],
            capture_output=True, text=True, timeout=120, check=False,
        )
        _require(
            start_result.returncode == 0,
            f'G2 source-IP rate sidecar failed (exit {start_result.returncode})',
        )
        statuses = {}
        for line in start_result.stdout.splitlines():
            marker, sep, raw_status = line.partition('=')
            _require(
                bool(sep) and marker not in statuses and raw_status.isdigit(),
                'G2 sidecar returned invalid status markers',
            )
            statuses[marker] = int(raw_status)
        expected_markers = {marker for marker, _path in requests}
        _require(set(statuses) == expected_markers, 'G2 sidecar did not return every expected status marker')
    except subprocess.TimeoutExpired as exc:
        failure = AcceptanceError('G2 rate sidecar exceeded its bounded runtime')
        failure.__cause__ = exc
        if active_operation == 'create':
            create_may_have_created = True
    except AcceptanceError as exc:
        failure = exc
    except OSError as exc:
        failure = AcceptanceError('G2 rate sidecar could not be started')
        failure.__cause__ = exc
    finally:
        if container_id is None and create_may_have_created:
            try:
                candidate_id = _read_rate_sidecar_cidfile(cidfile)
                cleanup_container = _inspect_g2_container(candidate_id, 'rate sidecar recovery container')
                _validate_rate_sidecar_identity(
                    cleanup_container, candidate_id, args, gateway['container_id'],
                )
                container_id = candidate_id
            except (AcceptanceError, OSError, subprocess.TimeoutExpired) as exc:
                cleanup_failure = CleanupAcceptanceError('G2 rate sidecar cleanup identity could not be verified')
                cleanup_failure.__cause__ = exc

        if container_id is not None:
            try:
                try:
                    ledger_id = _read_rate_sidecar_cidfile(cidfile)
                    _require(ledger_id == container_id, 'G2 sidecar CID ledger changed after inspection')
                except (AcceptanceError, OSError) as exc:
                    ledger_failure = AcceptanceError('G2 sidecar CID ledger changed after container inspection')
                    ledger_failure.__cause__ = exc

                cleanup_container = _inspect_g2_container(container_id, 'rate sidecar cleanup container')
                _validate_rate_sidecar_identity(
                    cleanup_container, container_id, args, gateway['container_id'],
                )
                cleanup_result = subprocess.run(
                    ['docker', 'rm', '-f', container_id],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                _require(cleanup_result.returncode == 0, 'G2 rate sidecar exact-ID cleanup failed')
            except (AcceptanceError, OSError, subprocess.TimeoutExpired) as exc:
                cleanup_failure = CleanupAcceptanceError('G2 rate sidecar exact-ID cleanup failed')
                cleanup_failure.__cause__ = exc
        elif create_may_have_created and cleanup_failure is None:
            cleanup_failure = CleanupAcceptanceError('G2 rate sidecar cleanup has no verified container ID')

        if failure is None and ledger_failure is not None:
            failure = ledger_failure
        if cidfile.exists() and not cidfile.is_symlink():
            cidfile.chmod(0o600)
        for private_file in output_root.iterdir():
            if private_file.is_file() and not private_file.is_symlink():
                private_file.chmod(0o600)

    if cleanup_failure is not None:
        raise cleanup_failure from failure
    if failure is not None:
        raise failure
    _require(statuses is not None, 'G2 sidecar completed without status results')
    return statuses


def _validate_rate_sidecar_identity(
    container: dict,
    container_id: str,
    args: argparse.Namespace,
    gateway_id: str,
    *,
    require_stopped: bool = False,
) -> None:
    config = container.get('Config')
    host_config = container.get('HostConfig')
    labels = config.get('Labels') if isinstance(config, dict) else None
    _require(
        str(container.get('Id', '')).lower() == container_id
        and container.get('Image') == args.curl_image_id
        and isinstance(labels, dict)
        and labels.get('org.newshub.local-domain.owner') == args.compose_project
        and config.get('User') == f'{os.getuid()}:{os.getgid()}'
        and isinstance(host_config, dict)
        and host_config.get('NetworkMode') == f'container:{gateway_id}',
        'G2 rate sidecar identity does not match its private owner, image, user, or namespace',
    )
    if require_stopped:
        _require(
            container.get('State', {}).get('Running') is False,
            'G2 rate sidecar must be inspected before it starts',
        )


def _csrf_from_body(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError('G2 sidecar CSRF response was invalid') from exc
    token = payload.get('csrfToken') if isinstance(payload, dict) else None
    _require(isinstance(token, str) and len(token) >= 32, 'G2 sidecar CSRF token is missing')
    return token


def _retry_after(path: Path) -> int:
    value = _headers(path).get('retry-after', [None])[-1]
    _require(value is not None and value.isdigit() and int(value) > 0, 'rate-limit response is missing a positive Retry-After')
    return int(value)


def _run_g2_rate_limit_checks(args: argparse.Namespace, checks: dict[str, str], bundle: dict) -> None:
    rate_root = args.private_root / 'rate'
    rate_root.mkdir(mode=0o700)
    _require(stat.S_IMODE(rate_root.stat().st_mode) == 0o700, 'G2 rate fixture directory must be mode 0700')
    output_root = rate_root / 'output'
    output_root.mkdir(mode=0o700)
    _require(stat.S_IMODE(output_root.stat().st_mode) == 0o700, 'G2 rate output directory must be mode 0700')
    # The sidecar sees only the CA certificate and its own private cookie/body files.
    _require(args.ca_cert.is_file(), 'G2 sidecar CA certificate is missing')

    login_ip = '127.0.0.70'
    login_cookie = 'login.cookies'
    login_csrf_config = _write_rate_request(
        rate_root, 'login-csrf', interface=login_ip, path='/api/auth/csrf/',
        cookie_path=login_cookie,
    )
    statuses = _run_rate_sidecar(args, login_ip, [('csrf', login_csrf_config)])
    _require(statuses['csrf'] == 200, 'login rate sidecar could not initialize CSRF')
    csrf_token = _csrf_from_body(output_root / 'login-csrf.body')
    # Prove invalid CSRF and hostile Origin do not consume the login bucket.
    bad_csrf = _write_rate_request(
        rate_root, 'login-bad-csrf', interface=login_ip, path='/api/auth/login/',
        cookie_path=login_cookie,
        body={'username': bundle['users']['rate']['username'], 'password': 'wrong-password-for-smoke'},
        csrf_token='invalid-csrf-token',
    )
    hostile_origin = _write_rate_request(
        rate_root, 'login-hostile-origin', interface=login_ip, path='/api/auth/login/',
        cookie_path=login_cookie,
        body={'username': bundle['users']['rate']['username'], 'password': 'wrong-password-for-smoke'},
        csrf_token=csrf_token, origin='https://spoof.invalid',
    )
    before = _run_fixture_program(args, bundle, 'login-rate-count')
    _require(before.get('count') == 0, 'login rate bucket was not initially empty')
    invalid_statuses = _run_rate_sidecar(
        args, login_ip, [('bad_csrf', bad_csrf), ('hostile_origin', hostile_origin)],
    )
    _require(invalid_statuses['bad_csrf'] == 403, 'invalid CSRF did not fail with HTTP 403')
    _require(invalid_statuses['hostile_origin'] == 403, 'hostile Origin did not fail with HTTP 403')
    after_invalid = _run_fixture_program(args, bundle, 'login-rate-count')
    _require(after_invalid.get('count') == 0, 'invalid CSRF or hostile Origin consumed the login rate bucket')
    sidecar_requests: list[tuple[str, Path]] = []
    for attempt in range(1, 7):
        body = {'username': bundle['users']['rate']['username'], 'password': 'wrong-password-for-smoke'}
        config = _write_rate_request(
            rate_root, f'login-password-{attempt}', interface=login_ip,
            path='/api/auth/login/', cookie_path=login_cookie, body=body,
            csrf_token=csrf_token, spoof_xff=(attempt == 6),
        )
        sidecar_requests.append((f'login_{attempt}', config))
    statuses = _run_rate_sidecar(args, login_ip, sidecar_requests)
    _require([statuses[f'login_{attempt}'] for attempt in range(1, 6)] == [401] * 5, 'five bad-password login attempts did not reach authentication')
    _require(statuses['login_6'] == 429, 'spoofed XFF bypassed the sixth login rate limit')
    retry_after = _retry_after(output_root / 'login-password-6.headers')
    after = _run_fixture_program(args, bundle, 'login-rate-count')
    _require(after.get('count') == 5, 'invalid CSRF/Origin changed the login bucket or the five-attempt limit was not exact')
    checks['g2_login_rate_limit'] = f'127.0.0.70: bad CSRF/Origin uncounted; five 401, sixth spoofed-XFF 429 Retry-After={retry_after}; bucket=5'

    registration_ips = [f'127.0.0.{octet}' for octet in range(61, 66)]
    special_roles = ('wrong_email', 'expired', 'weak', 'reused', 'missing')
    for index, (interface, role) in enumerate(zip(registration_ips, special_roles, strict=True)):
        cookie_path = f'register-{index}.cookies'
        csrf_config = _write_rate_request(
            rate_root, f'register-{index}-csrf', interface=interface,
            path='/api/auth/csrf/', cookie_path=cookie_path,
        )
        statuses = _run_rate_sidecar(args, interface, [('csrf', csrf_config)])
        _require(statuses['csrf'] == 200, 'registration sidecar could not initialize CSRF')
        csrf = _csrf_from_body(output_root / f'register-{index}-csrf.body')
        negative = bundle['negative_registrations'][role]
        body = dict(negative)
        if role in ('wrong_email', 'expired'):
            body['invite_token'] = bundle['invitations'][role]['token']
        elif role == 'reused':
            body['invite_token'] = bundle['invitations']['a']['token']
        elif role == 'weak':
            body['invite_token'] = bundle['invitations']['weak']['token']
        first_config = _write_rate_request(
            rate_root, f'register-{index}-special', interface=interface,
            path='/api/auth/register/', cookie_path=cookie_path,
            body=body, csrf_token=csrf,
        )
        request_set: list[tuple[str, Path]] = [('special', first_config)]
        probe_group = bundle['registration_probes'][index * 4:(index + 1) * 4]
        for attempt, probe in enumerate(probe_group, start=1):
            missing_invite = dict(probe)
            config = _write_rate_request(
                rate_root, f'register-{index}-missing-{attempt}', interface=interface,
                path='/api/auth/register/', cookie_path=cookie_path,
                body=missing_invite, csrf_token=csrf,
            )
            request_set.append((f'missing_{attempt}', config))
        final_probe = dict(probe_group[-1])
        final_probe['email'] = f'limited-{bundle["run_id"]}-{index}@example.invalid'
        final_config = _write_rate_request(
            rate_root, f'register-{index}-sixth', interface=interface,
            path='/api/auth/register/', cookie_path=cookie_path,
            body=final_probe, csrf_token=csrf, spoof_xff=True,
        )
        request_set.append(('sixth', final_config))
        statuses = _run_rate_sidecar(args, interface, request_set)
        expected_first = 400 if role == 'weak' else 403
        _require(statuses['special'] == expected_first, f'{role} invitation/password negative returned an unexpected status')
        _require([statuses[f'missing_{attempt}'] for attempt in range(1, 5)] == [403] * 4, 'missing invitation requests were not rejected')
        _require(statuses['sixth'] == 429, f'{interface} spoofed XFF bypassed the registration rate limit')
        retry_after = _retry_after(output_root / f'register-{index}-sixth.headers')
        checks[f'g2_registration_rate_{role}'] = f'{interface}: negative registration rejected; five requests then spoofed-XFF 429 Retry-After={retry_after}'

    counts = _run_fixture_program(args, bundle, 'registration-rate-counts')
    _require(counts.get('per_ip_counts') == [5] * 5, 'registration buckets do not contain exactly five attempts per source IP')
    _require(isinstance(counts.get('global_count'), int) and 0 < counts['global_count'] < 100, 'registration global bucket reached or exceeded its fixed limit')
    checks['g2_registration_rate_sources'] = 'five true loopback source IPs each reserved exactly five attempts; XFF spoof did not create a sixth bucket'
    checks['g2_registration_global_bucket'] = f'{counts["global_count"]}/100 within the fixed limit'
    _run_fixture_program(args, bundle, 'audit')


def _check_http_api(args: argparse.Namespace, checks: dict[str, str], work_dir: Path) -> None:
    redirect_headers = work_dir / 'http-redirect.headers'
    _expect_status(
        args, checks, 'http_redirect', '/news/1?from=smoke', 301,
        scheme='http', header_file=redirect_headers,
    )
    locations = _headers(redirect_headers).get('location', [])
    _require(
        locations == ['https://news.lambert.host/news/1?from=smoke'],
        'HTTP redirect did not use the fixed HTTPS host and request URI',
    )

    challenge_body, _ = _expect_status(
        args, checks, 'acme_fixture', '/.well-known/acme-challenge/newshub-local-test',
        200, scheme='http',
    )
    _require(challenge_body == 'newshub-local-acme-fixture\n', 'ACME challenge fixture body mismatch')

    headers_file = work_dir / 'csrf.headers'
    csrf_body, response_headers = _expect_status(
        args, checks, 'csrf_initialization', '/api/auth/csrf/', 200,
        header_file=headers_file,
    )
    _require('csrfToken' in csrf_body, 'CSRF initialization response is missing its token')
    _require_secure_csrf_cookie(response_headers)
    checks['csrf_cookie'] = 'Secure, host-only, readable, SameSite=Lax'

    _check_forwarded_header_secure_request(args, checks, work_dir)

    capabilities_body, capability_headers = _expect_status(
        args, checks, 'capabilities', '/api/capabilities/', 200,
        header_file=work_dir / 'capabilities.headers',
    )
    capabilities = json.loads(capabilities_body)
    if args.stage == 'g1':
        _require(capabilities.get('site_mode') == 'read_only', 'production smoke did not stay in read_only mode')
    else:
        _require(capabilities.get('site_mode') == 'full', 'G2 smoke did not use full site mode')
        features = capabilities.get('features', {})
        for name in ('accounts', 'signup', 'favorites', 'blocked_news', 'chat_history'):
            _require(
                isinstance(features.get(name), dict) and features[name].get('enabled') is True,
                f'G2 capability {name} was not enabled',
            )
        for name in ('chat', 'research', 'provider_comparisons', 'translation', 'tts'):
            _require(
                isinstance(features.get(name), dict)
                and features[name].get('enabled') is False
                and features[name].get('reason') == 'ai_disabled',
                f'G2 AI capability {name} was not explicitly disabled',
            )
        _require(capabilities.get('chatgpt_auth_mode') == 'disabled', 'G2 smoke enabled ChatGPT authorization')
        checks['g2_capabilities'] = 'full site, accounts/signup/favorites/chat history enabled; AI features disabled'
    _require(
        any('no-store' in value.lower() for value in capability_headers.get('cache-control', [])),
        'capabilities response is missing Cache-Control: no-store',
    )

    if args.stage == 'g2':
        fixture_bundle = _load_fixture_bundle(args.fixture_bundle)
        fixture_title = fixture_bundle['news']['title']
        search_term = fixture_title
    else:
        search_term = 'NewshubLocalDomainG1Fixture'
    search_body, _ = _expect_status(
        args,
        checks,
        'keyword_search',
        f'/api/news/?search={search_term}',
        200,
    )
    _require(search_term in search_body, 'keyword search did not return the seeded fixture')

    if args.stage == 'g1':
        blocked_requests = (
        ('translation_post', '/api/news/1/translate/', 'POST'),
        ('chat_get', '/api/news/1/chat/', 'GET'),
        ('chat_delete', '/api/news/1/chat/', 'DELETE'),
        ('research_create', '/api/research/', 'POST'),
        ('tts_get', '/api/news/1/tts/', 'GET'),
        ('subscription_get', '/api/chatgpt-subscription/', 'GET'),
        ('admin_get', '/api/admin/crawler/dashboard/', 'GET'),
        )
        for name, path, method in blocked_requests:
            _expect_status(
                args,
                checks,
                name,
                path,
                403,
                method=method,
                headers=('Content-Type: application/json',),
                body='{}' if method == 'POST' else None,
            )

        preflight_headers = (
            'Origin: https://news.lambert.host',
            'Access-Control-Request-Method: POST',
            'Access-Control-Request-Headers: content-type,x-csrftoken',
        )
        _expect_status(
            args, checks, 'known_route_preflight', '/api/news/1/chat/', 403,
            method='OPTIONS', headers=preflight_headers,
        )
        _expect_status(
            args, checks, 'unknown_route_preflight', '/api/not-a-real-route/', 404,
            method='OPTIONS', headers=preflight_headers,
        )
    else:
        news_path = f'/api/news/{args.news_id}'
        for name, path in (
            ('anonymous_favorites', '/api/favorites/?type=bookmark'),
            ('anonymous_chat_history', f'{news_path}/chat/'),
            ('anonymous_research_history', '/api/research/sessions/'),
            ('anonymous_admin', '/api/admin/crawler/dashboard/'),
        ):
            _expect_status(args, checks, name, path, 403)
        disabled_chat_body, _ = _expect_status(
            args, checks, 'anonymous_ai_chat_disabled', f'{news_path}/chat/', 403,
            method='POST', headers=('Content-Type: application/json',),
            body='{"question":"synthetic smoke question"}',
        )
        _require('ai_disabled' in disabled_chat_body, 'G2 anonymous chat POST did not report ai_disabled')
        checks['g2_ai_post'] = 'HTTP 403 ai_disabled; no provider call made'

    _expect_status(args, checks, 'unknown_api', '/api/not-a-real-route/', 404)
    _expect_status(args, checks, 'missing_asset', '/assets/not-present-12345678.js', 404)
    missing_headers = work_dir / 'missing-hash.headers'
    missing_status, _, _ = _curl(
        args, '/assets/not-present-12345678.js', header_file=missing_headers,
    )
    _require(missing_status == 404, 'missing hashed asset was not a 404')
    missing_cache = ','.join(_headers(missing_headers).get('cache-control', []))
    _require('immutable' not in missing_cache.lower(), '404 response must not receive immutable caching')

    legacy_path = '/assets/local-domain-legacy-12345678.js'
    legacy_headers = work_dir / 'legacy-asset.headers'
    legacy_body, legacy_response_headers = _expect_status(
        args, checks, 'legacy_hash_asset', legacy_path, 200,
        header_file=legacy_headers,
    )
    _require(legacy_body == 'legacy-asset-fixture\n', 'old hash asset fixture body mismatch')
    legacy_cache = ','.join(legacy_response_headers.get('cache-control', []))
    _require('immutable' in legacy_cache.lower() and '31536000' in legacy_cache, 'old hash asset is not immutable for one year')

    index_headers = work_dir / 'index.headers'
    _expect_status(args, checks, 'index_no_store', '/', 200, header_file=index_headers)
    index_cache = ','.join(_headers(index_headers).get('cache-control', []))
    _require('no-store' in index_cache.lower(), 'SPA index is missing no-store')

    favicon_status, favicon_body, _ = _curl(args, '/favicon.svg')
    _require(favicon_status == 200 and '<svg' in favicon_body, 'the deployed favicon was not served as a static SVG')
    missing_icon_status, _, _ = _curl(args, '/favicon-32x32.png')
    _require(missing_icon_status == 404, 'missing exact icon path unexpectedly fell through to the SPA')
    checks['favicon_static'] = 'HTTP 200; missing exact icon HTTP 404'

    unknown_host_command = _curl_command(
        args,
        '/',
        headers=('Host: unknown.invalid',),
    )
    unknown_host = subprocess.run(
        unknown_host_command,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(
        _curl_closed_without_http_response(unknown_host, scheme='https'),
        'unknown HTTPS Host was not closed with 444',
    )
    checks['unknown_host'] = 'connection closed by Nginx 444'
    _check_absolute_uri_unknown_host(args, checks, scheme='https')

    unknown_http_command = _curl_command(
        args,
        '/',
        scheme='http',
        headers=('Host: unknown.invalid',),
    )
    unknown_http = subprocess.run(
        unknown_http_command,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(
        _curl_closed_without_http_response(unknown_http, scheme='http'),
        'unknown HTTP Host was not closed with 444',
    )
    checks['unknown_http_host'] = 'connection closed by Nginx 444'
    _check_absolute_uri_unknown_host(args, checks, scheme='http')


def _check_absolute_uri_unknown_host(
    args: argparse.Namespace,
    checks: dict[str, str],
    *,
    scheme: str,
) -> None:
    request_target = f'{scheme}://{HOST}/'
    result = subprocess.run(
        _curl_command(
            args,
            '/',
            scheme=scheme,
            headers=('Host: evil.invalid',),
            request_target=request_target,
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    _require(
        _curl_closed_without_http_response(result, scheme=scheme),
        f'absolute-URI {scheme.upper()} request with an unknown Host was not closed with 444',
    )
    checks[f'absolute_uri_unknown_{scheme}_host'] = 'connection closed by Nginx 444'


def _browser_arguments(gateway_ip: str) -> list[str]:
    return [
        f'--host-resolver-rules=MAP {HOST} {gateway_ip},MAP * ~NOTFOUND,EXCLUDE localhost',
        '--disable-background-networking',
        '--disable-component-update',
        '--disable-sync',
        '--no-first-run',
        '--no-default-browser-check',
    ]


def _local_tool_environment(task_browser_home: Path) -> dict[str, str]:
    task_browser_home.mkdir(parents=True, exist_ok=True)
    task_tmp = task_browser_home / 'tmp'
    task_tmp.mkdir(parents=True, exist_ok=True)
    child_environment = {
        name: os.environ[name]
        for name in ('PATH', 'LANG', 'LC_ALL', 'TZ')
        if name in os.environ
    }
    child_environment.update({
        'HOME': str(task_browser_home),
        'TMPDIR': str(task_tmp),
        'XDG_CONFIG_HOME': str(task_browser_home / '.config'),
        'XDG_CACHE_HOME': str(task_browser_home / '.cache'),
    })
    return child_environment


def _new_nss_database(task_browser_home: Path, ca_cert: Path | None) -> None:
    database = task_browser_home / '.pki' / 'nssdb'
    database.mkdir(parents=True)
    child_environment = _local_tool_environment(task_browser_home)
    _run_checked(
        ['certutil', '-N', '-d', f'sql:{database}', '--empty-password'],
        env=child_environment,
    )
    if ca_cert is not None:
        _run_checked([
            'certutil', '-A', '-d', f'sql:{database}',
            '-n', 'NewsHub isolated local test CA',
            '-t', 'C,,',
            '-i', str(ca_cert),
        ], env=child_environment)


def _browser_environment(task_browser_home: Path) -> dict[str, str]:
    return _local_tool_environment(task_browser_home)


def _run_browser_checks(args: argparse.Namespace, checks: dict[str, str], work_dir: Path) -> None:
    try:
        installed_version = importlib.metadata.version('playwright')
    except importlib.metadata.PackageNotFoundError as exc:
        raise AcceptanceError('Python Playwright is not installed in the selected interpreter') from exc
    _require(installed_version == PLAYWRIGHT_VERSION, f'Python Playwright must be {PLAYWRIGHT_VERSION}')

    executable = args.chromium_executable or os.environ.get('CHROMIUM_EXECUTABLE', '/usr/bin/chromium')
    executable_path = Path(executable)
    _require(executable_path.is_absolute() and executable_path.is_file(), 'Chromium executable path must be an existing absolute file')
    _require(os.access(executable_path, os.X_OK), 'Chromium executable is not executable')

    ca_cert = args.ca_cert.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='nb-', dir='/tmp') as temp_name:
        profile_root = Path(temp_name)
        os.chmod(profile_root, 0o700)
        task_browser_home = profile_root / 'u'
        task_browser_home.mkdir(mode=0o700)
        _new_nss_database(task_browser_home, None)

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise AcceptanceError('Python Playwright 1.62.0 is unavailable to the selected interpreter') from exc

        with sync_playwright() as playwright:
            untrusted_context = playwright.chromium.launch_persistent_context(
                str(task_browser_home / 'profile'),
                executable_path=str(executable_path),
                headless=True,
                ignore_https_errors=False,
                service_workers='block',
                args=_browser_arguments(args.gateway_ip),
                env=_browser_environment(task_browser_home),
            )
            try:
                untrusted_page = untrusted_context.new_page()
                try:
                    untrusted_page.goto(f'https://{HOST}/', wait_until='domcontentloaded', timeout=15000)
                except PlaywrightError as exc:
                    _require('ERR_CERT_AUTHORITY_INVALID' in str(exc), 'untrusted CA failed for an unexpected reason')
                    checks['browser_untrusted_ca'] = 'rejected with ERR_CERT_AUTHORITY_INVALID'
                else:
                    raise AcceptanceError('fresh browser profile unexpectedly trusted the test CA')
            finally:
                untrusted_context.close()

        task_browser_home = profile_root / 't'
        task_browser_home.mkdir(mode=0o700)
        _new_nss_database(task_browser_home, ca_cert)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(task_browser_home / 'profile'),
                executable_path=str(executable_path),
                headless=True,
                ignore_https_errors=False,
                service_workers='block',
                args=_browser_arguments(args.gateway_ip),
                env=_browser_environment(task_browser_home),
            )
            page = context.new_page()
            external_hosts: set[str] = set()

            def restrict_to_local_domain(route) -> None:
                parsed = urlparse(route.request.url)
                if parsed.hostname == HOST and parsed.scheme == 'https':
                    route.continue_()
                else:
                    external_hosts.add(parsed.hostname or '')
                    route.abort()

            context.route('**/*', restrict_to_local_domain)
            try:
                response = page.goto(f'https://{HOST}/', wait_until='domcontentloaded', timeout=20000)
                _require(response is not None and response.status == 200, 'trusted browser homepage did not return HTTP 200')
                _require(page.locator('#root').count() == 1, 'SPA root element is missing')
                checks['browser_homepage'] = 'HTTP 200'

                detail = page.goto(f'https://{HOST}/news/{args.news_id}', wait_until='domcontentloaded', timeout=20000)
                _require(detail is not None and detail.status == 200, 'browser news deep link did not return HTTP 200')
                checks['browser_news_deep_link'] = 'HTTP 200'

                page.locator('.article-section-render').scroll_into_view_if_needed()
                diagram = page.locator('[role="img"][aria-label="Mermaid 图表"]')
                diagram.wait_for(state='visible', timeout=20000)
                chart_paint = diagram.locator('svg').first.evaluate("""(svg) => {
                    const texts = Array.from(svg.querySelectorAll('text'));
                    const labels = texts.map((element) => element.textContent?.trim() || '').filter(Boolean);
                    const firstLabel = texts.find((element) => (element.textContent || '').trim());
                    const node = firstLabel?.closest('.node');
                    const shape = node?.querySelector('rect, polygon, path, ellipse');
                    const box = svg.getBoundingClientRect();
                    return {
                        labels,
                        nodeFill: shape ? getComputedStyle(shape).fill : null,
                        textFill: firstLabel ? getComputedStyle(firstLabel).fill : null,
                        width: box.width,
                        height: box.height,
                    };
                }""")
                _require(
                    'Fixture article' in chart_paint['labels'] and 'Mermaid flow' in chart_paint['labels'],
                    'Mermaid labels are missing from the rendered SVG',
                )
                _require(chart_paint['width'] > 0 and chart_paint['height'] > 0, 'Mermaid SVG has no visible size')
                _require(chart_paint['nodeFill'] and chart_paint['textFill'], 'Mermaid node/text computed fill is missing')
                _require(
                    not (
                        chart_paint['nodeFill'] == chart_paint['textFill']
                        and chart_paint['nodeFill'].lower() in {'black', 'rgb(0, 0, 0)', '#000', '#000000'}
                    ),
                    'Mermaid node and label computed fills may be unreadable: '
                    f"node={chart_paint['nodeFill']!r}, text={chart_paint['textFill']!r}",
                )
                mermaid_screenshot = work_dir / f'mermaid-{args.stage}.png'
                page.screenshot(path=str(mermaid_screenshot), full_page=True)
                checks['mermaid_chart'] = json.dumps(chart_paint, sort_keys=True)
                checks['mermaid_screenshot'] = str(mermaid_screenshot)

                page.evaluate("() => fetch('/api/auth/csrf/').then((response) => response.json())")
                cookie = page.evaluate("() => document.cookie")
                _require('csrftoken=' in cookie, 'trusted browser cannot read the CSRF cookie')
                checks['browser_csrf_cookie'] = 'readable through document.cookie'

                if args.stage == 'g1':
                    favorite_api_calls: list[str] = []
                    page.on(
                        'request',
                        lambda request: favorite_api_calls.append(request.url)
                        if '/api/favorites' in request.url else None,
                    )
                    page.goto(f'https://{HOST}/favorites', wait_until='domcontentloaded', timeout=20000)
                    _require(not favorite_api_calls, 'private deep link called its API in read_only mode')
                    checks['private_deep_link'] = 'no favorites API request'

                try:
                    page.goto(
                        f'https://{HOST}:{args.wrong_san_port}/',
                        wait_until='domcontentloaded',
                        timeout=10000,
                    )
                except PlaywrightError as exc:
                    _require('ERR_CERT_COMMON_NAME_INVALID' in str(exc), 'wrong SAN failed for an unexpected reason')
                    checks['browser_wrong_san'] = 'rejected with ERR_CERT_COMMON_NAME_INVALID'
                else:
                    raise AcceptanceError('browser accepted a certificate with the wrong SAN')

                _require(not external_hosts, f'browser attempted non-local egress to {sorted(external_hosts)}')
                checks['browser_external_egress'] = 'blocked; no external host request observed'
            except Exception:
                failure_screenshot = work_dir / 'local-domain-browser-failure.png'
                try:
                    page.screenshot(path=str(failure_screenshot), full_page=True, timeout=5000)
                except Exception:
                    pass
                raise
            finally:
                context.close()


_BROWSER_API_SCRIPT = """async ({method, path, body}) => {
    const headers = {};
    const safeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);
    const hasJsonBody = !safeMethod && body !== undefined && body !== null;
    if (hasJsonBody) headers['Content-Type'] = 'application/json';
    if (!safeMethod) {
      const cookie = document.cookie.split(';').map((value) => value.trim())
        .find((value) => value.startsWith('csrftoken='));
      if (!cookie) throw new Error('CSRF cookie is missing');
      headers['X-CSRFToken'] = decodeURIComponent(cookie.slice('csrftoken='.length));
    }
    const options = {method, credentials: 'same-origin', headers};
    if (hasJsonBody) options.body = JSON.stringify(body);
    const response = await fetch(path, options);
    const text = await response.text();
    let parsed = text;
    try { parsed = text ? JSON.parse(text) : null; } catch { /* keep text */ }
    return {status: response.status, body: parsed};
}"""


async def _browser_api(page, method: str, path: str, body: dict | None = None) -> dict:
    response = await page.evaluate(
        _BROWSER_API_SCRIPT,
        {'method': method, 'path': path, 'body': body},
    )
    return response


async def _wait_user(page, username: str, *, timeout: int = 15000) -> None:
    await page.get_by_role('img', name=f'{username}，已登录').wait_for(state='visible', timeout=timeout)


async def _open_auth(page, *, mode: str) -> object:
    await page.get_by_role('button', name='登录', exact=True).click()
    dialog = page.get_by_role('dialog')
    await dialog.wait_for(state='visible')
    if mode == 'register':
        await dialog.get_by_role('button', name='立即注册', exact=True).click()
        await dialog.locator('#auth-email').wait_for(state='visible')
    else:
        await dialog.locator('#auth-password').wait_for(state='visible')
    return dialog


async def _register_ui(page, person: dict, invitation: dict) -> None:
    dialog = await _open_auth(page, mode='register')
    await dialog.locator('#auth-username').fill(person['username'])
    await dialog.locator('#auth-email').fill(person['email'])
    await dialog.locator('#auth-invite-token').fill(invitation['token'])
    await dialog.locator('#auth-password').fill(person['password'])
    await dialog.get_by_role('button', name='注册', exact=True).click()
    await _wait_user(page, person['username'])
    await dialog.wait_for(state='detached')


async def _login_ui(page, person: dict) -> None:
    dialog = await _open_auth(page, mode='login')
    await dialog.locator('#auth-username').fill(person['username'])
    await dialog.locator('#auth-password').fill(person['password'])
    await dialog.get_by_role('button', name='登录', exact=True).click()
    await _wait_user(page, person['username'])
    await dialog.wait_for(state='detached')


async def _logout_ui(page, username: str, context) -> None:
    await page.get_by_role('button', name='打开菜单').click()
    await page.get_by_role('button', name='退出登录', exact=True).click()
    await page.get_by_role('img', name=f'{username}，已登录').wait_for(state='detached', timeout=15000)
    auth_me = await _browser_api(page, 'GET', '/api/auth/me/')
    _require(auth_me['status'] == 403, 'logged-out browser session still authorized /api/auth/me/')
    remaining = [cookie for cookie in await context.cookies(f'https://{HOST}') if cookie['name'] == 'sessionid']
    _require(not remaining, 'logout did not remove the browser session cookie')


async def _sanitize_g2_failure_page(page) -> bool:
    """Clear visible account fields, or close the auth modal before capture."""
    try:
        modal = page.locator('.auth-modal-backdrop')
        if await modal.count() == 0:
            return True
        for selector in ('#auth-username', '#auth-email', '#auth-password', '#auth-invite-token'):
            field = page.locator(selector)
            if await field.count() and await field.is_visible():
                await field.fill('', timeout=1000)
                if await field.input_value() != '':
                    raise RuntimeError('private field could not be cleared')
        return True
    except Exception:
        try:
            await page.get_by_role('button', name='关闭登录窗口').click(timeout=1000)
            await page.locator('.auth-modal-backdrop').wait_for(state='detached', timeout=1000)
            return True
        except Exception:
            return False


def _browser_cookie_summary(cookies: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name in ('sessionid', 'csrftoken'):
        cookie = next((entry for entry in cookies if entry.get('name') == name), None)
        if cookie is None:
            continue
        result[name] = {
            'secure': cookie.get('secure') is True,
            'http_only': cookie.get('httpOnly') is True,
            'host_only': cookie.get('domain') == HOST,
            'same_site': cookie.get('sameSite'),
        }
    return result


async def _run_g2_browser_checks(args: argparse.Namespace, checks: dict[str, str], work_dir: Path) -> None:
    bundle = _load_fixture_bundle(args.fixture_bundle)
    state = _read_fixture_state(args)
    _require(bundle['news']['title'].endswith(bundle['run_id']), 'G2 synthetic article marker is invalid')
    try:
        installed_version = importlib.metadata.version('playwright')
    except importlib.metadata.PackageNotFoundError as exc:
        raise AcceptanceError('Python Playwright is not installed in the selected interpreter') from exc
    _require(installed_version == PLAYWRIGHT_VERSION, f'Python Playwright must be {PLAYWRIGHT_VERSION}')
    executable = args.chromium_executable or os.environ.get('CHROMIUM_EXECUTABLE', '/usr/bin/chromium')
    executable_path = Path(executable)
    _require(executable_path.is_absolute() and executable_path.is_file(), 'Chromium executable path must be an existing absolute file')
    _require(os.access(executable_path, os.X_OK), 'Chromium executable is not executable')
    ca_cert = args.ca_cert.resolve(strict=True)

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise AcceptanceError('Python Playwright 1.62.0 async API is unavailable') from exc

    # The G1 browser helper already proved an untrusted fresh profile rejects
    # the CA. G2 gets a separate short-lived trusted profile of its own.
    with tempfile.TemporaryDirectory(prefix='nb-', dir='/tmp') as temp_name:
        profile_root = Path(temp_name)
        os.chmod(profile_root, 0o700)
        browser_home = profile_root / 't'
        browser_home.mkdir(mode=0o700)
        _new_nss_database(browser_home, ca_cert)
        external_hosts: set[str] = set()
        observed_cookie_headers: list[dict] = []
        response_tasks: list[asyncio.Task] = []
        requests: list[str] = []
        delayed_me = {'armed': False, 'response': None, 'fetched': None, 'release': None}
        page = None

        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(browser_home / 'profile'), executable_path=str(executable_path),
                headless=True, ignore_https_errors=False, service_workers='block',
                args=_browser_arguments(args.gateway_ip), env=_browser_environment(browser_home),
            )

            async def route_local(route) -> None:
                parsed = urlparse(route.request.url)
                if parsed.hostname == HOST and parsed.scheme == 'https':
                    await route.continue_()
                else:
                    external_hosts.add(parsed.hostname or '')
                    await route.abort()

            await context.route('**/*', route_local)
            page = await context.new_page()

            async def hold_auth_me(route) -> None:
                response = await route.fetch()
                delayed_me['response'] = response
                try:
                    delayed_me['actual_user'] = await response.json()
                except Exception:
                    delayed_me['actual_user'] = None
                delayed_me['fetched'].set()
                await delayed_me['release'].wait()
                await route.fulfill(response=response)

            async def on_response(response) -> None:
                path = urlparse(response.url).path
                if path.startswith('/api/auth/'):
                    requests.append(path)
                    try:
                        headers = await response.headers_array()
                    except Exception:
                        return
                    for header in headers:
                        if header['name'].lower() != 'set-cookie':
                            continue
                        first, *attribute_parts = header['value'].split(';')
                        cookie_name = first.split('=', 1)[0].strip().lower()
                        attributes = {part.strip().lower() for part in attribute_parts}
                        observed_cookie_headers.append({
                            'path': path,
                            'cookie': cookie_name,
                            'secure': 'secure' in attributes,
                            'http_only': 'httponly' in attributes,
                            'host_only': not any(part.startswith('domain=') for part in attributes),
                            'same_site': next((part.split('=', 1)[1] for part in attributes if part.startswith('samesite=')), None),
                            'deleted': any(part in {'max-age=0', 'max-age=0.0'} for part in attributes),
                        })

            page.on('response', lambda response: response_tasks.append(asyncio.create_task(on_response(response))))

            try:
                home = await page.goto(f'https://{HOST}/', wait_until='domcontentloaded', timeout=20000)
                _require(home is not None and home.status == 200, 'G2 browser homepage did not return HTTP 200')
                _require(await page.locator('#root').count() == 1, 'G2 browser SPA root element is missing')
                anonymous = await _browser_api(page, 'GET', '/api/auth/me/')
                _require(anonymous['status'] == 403, 'a fresh browser context was unexpectedly authenticated')
                anonymous_private_calls: list[str] = []
                page.on(
                    'request',
                    lambda request: anonymous_private_calls.append(urlparse(request.url).path)
                    if '/api/favorites' in request.url else None,
                )
                await page.goto(f'https://{HOST}/favorites', wait_until='domcontentloaded', timeout=20000)
                await page.get_by_text('登录后管理内容偏好', exact=True).wait_for(state='visible', timeout=15000)
                _require(not anonymous_private_calls, 'anonymous private route queried the favorites API')
                checks['g2_anonymous_private_route'] = 'favorites page denies anonymous access without querying private API'
                await page.goto(f'https://{HOST}/', wait_until='domcontentloaded', timeout=20000)

                initial_csrf = await page.evaluate("async () => { await fetch('/api/auth/csrf/'); return document.cookie.split(';').map(v => v.trim()).find(v => v.startsWith('csrftoken='))?.slice('csrftoken='.length) || ''; }")
                _require(isinstance(initial_csrf, str) and len(initial_csrf) >= 32, 'G2 browser could not read its host-only CSRF cookie')
                await _register_ui(page, bundle['users']['a'], bundle['invitations']['a'])
                a_csrf = await page.evaluate("() => document.cookie.split(';').map(v => v.trim()).find(v => v.startsWith('csrftoken='))?.slice('csrftoken='.length) || ''")
                _require(a_csrf and a_csrf != initial_csrf, 'registration did not rotate the CSRF token')
                a_cookie_summary = _browser_cookie_summary(await context.cookies(f'https://{HOST}'))
                _require(a_cookie_summary.get('sessionid', {}).get('secure'), 'session cookie is missing Secure')
                _require(a_cookie_summary.get('sessionid', {}).get('http_only'), 'session cookie is missing HttpOnly')
                _require(a_cookie_summary.get('sessionid', {}).get('host_only'), 'session cookie is not host-only')
                _require(a_cookie_summary.get('csrftoken', {}).get('secure'), 'CSRF cookie is missing Secure')
                _require(not a_cookie_summary.get('csrftoken', {}).get('http_only'), 'CSRF cookie is not readable by the SPA')
                _require(a_cookie_summary.get('csrftoken', {}).get('host_only'), 'CSRF cookie is not host-only')
                _require(a_cookie_summary.get('csrftoken', {}).get('same_site') == 'Lax', 'CSRF cookie is not SameSite=Lax')
                checks['g2_registration_a'] = 'real invitation registration via SPA; session Secure/HttpOnly/host-only; CSRF rotated, Secure/readable/host-only/SameSite=Lax'

                await _logout_ui(page, bundle['users']['a']['username'], context)
                await _register_ui(page, bundle['users']['b'], bundle['invitations']['b'])
                await page.reload(wait_until='domcontentloaded', timeout=20000)
                await _wait_user(page, bundle['users']['b']['username'])
                b_cookie_summary = _browser_cookie_summary(await context.cookies(f'https://{HOST}'))
                _require(b_cookie_summary.get('sessionid', {}).get('secure') and b_cookie_summary.get('sessionid', {}).get('http_only'), 'B session cookie security attributes changed after reload')
                checks['g2_registration_b_session_refresh'] = 'real invitation registration; B identity persisted after browser reload'

                attached = await asyncio.to_thread(_run_fixture_program, args, bundle, 'attach-owner')
                state.update(attached)
                _store_fixture_state(args.fixture_state, state)

                b_favorites = await _browser_api(page, 'GET', '/api/favorites/?type=bookmark')
                _require(b_favorites['status'] == 200 and b_favorites['body'].get('results') == [], 'B read A favorite or received an unexpected favorite')
                cross_favorite_delete = await _browser_api(page, 'DELETE', f"/api/favorites/{state['favorite_id']}/")
                _require(cross_favorite_delete['status'] == 404, 'B could delete A favorite')
                b_chat = await _browser_api(page, 'GET', f"/api/news/{state['news_id']}/chat/")
                _require(b_chat['status'] == 200 and b_chat['body'].get('messages') == [], 'B read A chat history')
                b_clear_chat = await _browser_api(page, 'DELETE', f"/api/news/{state['news_id']}/chat/")
                _require(b_clear_chat['status'] == 200, 'B could not clear only B chat history')
                research_path = f"/api/research/{state['research_id']}/"
                _require((await _browser_api(page, 'GET', research_path))['status'] == 404, 'B read A research history')
                _require((await _browser_api(page, 'DELETE', research_path))['status'] == 404, 'B deleted A research history')
                b_ai_post = await _browser_api(
                    page, 'POST', f"/api/news/{state['news_id']}/chat/",
                    {'question': 'synthetic local-domain AI-disabled check'},
                )
                _require(b_ai_post['status'] == 403 and b_ai_post['body'].get('error_code') == 'ai_disabled', 'AI-disabled Chat POST was not blocked before a provider call')
                for path in ('/api/admin/crawler/dashboard/', '/api/provider-comparisons/'):
                    response = await _browser_api(page, 'GET', path)
                    _require(response['status'] == 403, f'ordinary user accessed protected endpoint {path}')
                checks['g2_b_owner_isolation'] = 'B receives no A favorites/chat/research; cross-owner DELETE returns 404; own empty chat DELETE is scoped'
                checks['g2_ai_disabled_post'] = 'HTTP 403 ai_disabled before any model/provider request'
                checks['g2_ordinary_admin_denied'] = 'crawler and provider-comparison APIs return HTTP 403'

                request_paths: list[str] = []
                page.on('request', lambda request: request_paths.append(urlparse(request.url).path))
                await page.goto(f'https://{HOST}/admin/crawlers', wait_until='domcontentloaded', timeout=20000)
                await page.wait_for_timeout(250)
                body_text = await page.locator('body').inner_text()
                _require('超级管理员' in body_text or '管理员' in body_text, 'ordinary-user admin route did not show its protected state')
                _require(not any(path.startswith('/api/admin/crawler/') for path in request_paths), 'ordinary-user admin UI queried the admin API')
                await page.goto(f'https://{HOST}/provider-comparisons', wait_until='domcontentloaded', timeout=20000)
                await page.wait_for_timeout(250)
                _require(not any(path.startswith('/api/provider-comparisons') for path in request_paths), 'AI-disabled ordinary-user UI queried Provider comparison data')
                checks['g2_ordinary_admin_ui'] = 'protected route rendered without admin API request'
                checks['g2_provider_ui'] = 'AI-disabled route rendered without provider-comparison API request'

                await _logout_ui(page, bundle['users']['b']['username'], context)
                await _login_ui(page, bundle['users']['a'])
                await page.goto(f'https://{HOST}/favorites', wait_until='domcontentloaded', timeout=20000)
                await page.get_by_text(bundle['news']['title'], exact=False).wait_for(state='visible', timeout=15000)
                a_favorites = await _browser_api(page, 'GET', '/api/favorites/?type=bookmark')
                _require(a_favorites['status'] == 200 and any(item.get('id') == state['favorite_id'] for item in a_favorites['body'].get('results', [])), 'A favorite fixture was not visible to its owner')
                a_chat = await _browser_api(page, 'GET', f"/api/news/{state['news_id']}/chat/")
                _require(a_chat['status'] == 200 and any(state['chat_marker'] in item.get('content', '') for item in a_chat['body'].get('messages', [])), 'A chat fixture was not visible to its owner')
                a_research = await _browser_api(page, 'GET', research_path)
                _require(a_research['status'] == 200 and any(state['research_marker'] in item.get('content', '') for item in a_research['body'].get('messages', [])), 'A research fixture was not visible to its owner')
                checks['g2_a_owner_data'] = 'A sees its favorite through the page/API and its Chat/Research history through the API'

                delayed_me['armed'] = True
                delayed_me['fetched'] = asyncio.Event()
                delayed_me['release'] = asyncio.Event()
                await context.route('**/api/auth/me/', hold_auth_me)
                await page.reload(wait_until='domcontentloaded', timeout=20000)
                await asyncio.wait_for(delayed_me['fetched'].wait(), timeout=10)
                _require(isinstance(delayed_me.get('actual_user'), dict) and delayed_me['actual_user'].get('username') == bundle['users']['a']['username'], 'held fetchMe response was not the real authenticated A response')
                await _login_ui(page, bundle['users']['b'])
                delayed_me['release'].set()
                await page.wait_for_timeout(250)
                await _wait_user(page, bundle['users']['b']['username'])
                _require(delayed_me['actual_user'].get('username') == bundle['users']['a']['username'], 'late fetchMe fixture did not capture A')
                await page.goto(f'https://{HOST}/favorites', wait_until='domcontentloaded', timeout=20000)
                await page.get_by_text('还没有收藏内容', exact=True).wait_for(state='visible', timeout=15000)
                b_after_switch = await _browser_api(page, 'GET', '/api/favorites/?type=bookmark')
                _require(b_after_switch['status'] == 200 and b_after_switch['body'].get('results') == [], 'A private favorite cache leaked into B after a delayed fetchMe response')
                checks['g2_delayed_fetch_me'] = 'real delayed A fetchMe released after B login; B identity and private cache remained isolated'
                checks['g2_account_switch_cache'] = 'A private favorites were visible to A and absent after switching to B'
                await context.unroute('**/api/auth/me/', hold_auth_me)

                await _logout_ui(page, bundle['users']['b']['username'], context)
                await _login_ui(page, bundle['users']['a'])
                await page.goto(f'https://{HOST}/favorites', wait_until='domcontentloaded', timeout=20000)
                await page.get_by_text(bundle['news']['title'], exact=False).wait_for(state='visible', timeout=15000)
                for method, path in (
                    ('DELETE', f"/api/favorites/{state['favorite_id']}/"),
                    ('DELETE', f"/api/news/{state['news_id']}/chat/"),
                    ('DELETE', research_path),
                ):
                    response = await _browser_api(page, method, path)
                    expected_status = 204 if method == 'DELETE' and path.startswith('/api/favorites') or path.startswith('/api/research/') else 200
                    _require(response['status'] == expected_status, f'A owner CSRF delete {path} returned HTTP {response["status"]}')
                _require((await _browser_api(page, 'GET', f"/api/news/{state['news_id']}/chat/"))['body'].get('messages') == [], 'A chat history did not clear for its owner')
                checks['g2_owner_csrf_writes'] = 'A favorite, Chat, and Research DELETE accepted same-origin CSRF and removed only A-owned fixtures'

                await _logout_ui(page, bundle['users']['a']['username'], context)
                await _login_ui(page, bundle['users']['admin'])
                _require((await _browser_api(page, 'GET', '/api/admin/crawler/dashboard/'))['status'] == 200, 'active synthetic superuser could not read the admin dashboard')
                _require((await _browser_api(page, 'GET', '/api/provider-comparisons/'))['status'] == 200, 'active synthetic superuser could not read provider comparison records')
                request_paths.clear()
                admin_page = await page.goto(f'https://{HOST}/admin/crawlers', wait_until='domcontentloaded', timeout=20000)
                _require(admin_page is not None and admin_page.status == 200, 'admin UI deep link did not load')
                await page.wait_for_timeout(300)
                _require(any(path.startswith('/api/admin/crawler/dashboard/') for path in request_paths), 'active superuser admin UI did not query its dashboard')
                await asyncio.to_thread(_run_fixture_program, args, bundle, 'deactivate-admin')
                _require((await _browser_api(page, 'GET', '/api/auth/me/'))['status'] == 403, 'inactive admin session still passed auth/me')
                _require((await _browser_api(page, 'GET', '/api/admin/crawler/dashboard/'))['status'] == 403, 'inactive admin session still read admin dashboard')
                _require((await _browser_api(page, 'GET', '/api/provider-comparisons/'))['status'] == 403, 'inactive admin session still read provider comparisons')
                await page.reload(wait_until='domcontentloaded', timeout=20000)
                await page.get_by_role('button', name='登录', exact=True).wait_for(state='visible', timeout=15000)
                checks['g2_active_admin'] = 'active synthetic superuser reads admin/provider records and triggers admin UI query'
                checks['g2_inactive_admin_session'] = 'after deactivation, old session receives HTTP 403 from me/admin/provider endpoints'

                await page.goto(f'https://{HOST}/news/{state["news_id"]}', wait_until='domcontentloaded', timeout=20000)
                _require(not external_hosts, f'G2 browser attempted non-local egress to {sorted(external_hosts)}')
                screenshot = work_dir / 'g2-accounts.png'
                await page.screenshot(path=str(screenshot), full_page=True)
                checks['g2_browser_screenshot'] = str(screenshot)
                checks['g2_browser_egress'] = 'blocked; no external host request observed'
                checks['g2_cookie_header_attributes'] = json.dumps(
                    [item for item in observed_cookie_headers if item['cookie'] in {'sessionid', 'csrftoken'}],
                    sort_keys=True,
                )
                while True:
                    response_task_batch = tuple(response_tasks)
                    await asyncio.gather(*response_task_batch, return_exceptions=True)
                    if len(response_task_batch) == len(response_tasks):
                        break
                _require(
                    any(item['cookie'] == 'sessionid' and item['secure'] and item['http_only'] and item['host_only'] for item in observed_cookie_headers),
                    'observed session Set-Cookie headers were missing required security attributes',
                )
                _require(
                    any(item['cookie'] == 'csrftoken' and item['secure'] and not item['http_only'] and item['host_only'] and item['same_site'] == 'lax' for item in observed_cookie_headers),
                    'observed CSRF Set-Cookie headers were missing required security attributes',
                )
                _require(
                    any(item['cookie'] == 'sessionid' and item['deleted'] for item in observed_cookie_headers),
                    'logout response did not expire the session cookie',
                )
            except Exception:
                if delayed_me.get('release') is not None:
                    delayed_me['release'].set()
                if page is not None:
                    if await _sanitize_g2_failure_page(page):
                        try:
                            await page.screenshot(path=str(work_dir / 'g2-browser-failure.png'), full_page=True, timeout=5000)
                        except Exception:
                            pass
                raise
            finally:
                for task in response_tasks:
                    if not task.done():
                        try:
                            await task
                        except Exception:
                            pass
                await context.close()


def _run_sse_check(args: argparse.Namespace, checks: dict[str, str]) -> None:
    command = _curl_command(
        args,
        f'/api/news/{args.news_id}/chat/',
        headers=FORWARDED_SPOOF_HEADERS,
    )
    command[command.index('--max-time') + 1] = '8'
    command[command.index('--connect-timeout') + 1] = '2'
    command.extend(['--no-buffer'])

    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    try:
        first_line = process.stdout.readline() if process.stdout is not None else b''
        first_elapsed = time.monotonic() - started
        remaining, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise AcceptanceError('fake SSE stream did not finish within its deadline') from exc
    total_elapsed = time.monotonic() - started
    body = first_line + remaining
    _require(process.returncode == 0, 'curl could not read the fake SSE stream')
    _require(b'data: first-frame' in body and b'data: final-frame' in body, 'fake SSE frames are missing')
    _require(total_elapsed - first_elapsed >= 0.5, 'first SSE frame did not arrive before the delayed final frame')

    header_frame = next(
        (line[len(SSE_PROXY_HEADER_MARKER):] for line in body.splitlines()
         if line.startswith(SSE_PROXY_HEADER_MARKER)),
        None,
    )
    _require(header_frame is not None, 'fake SSE upstream did not echo the Nginx proxy headers')
    try:
        observed_headers = json.loads(header_frame)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AcceptanceError('fake SSE proxy header echo was not valid JSON') from exc
    _require(observed_headers.get('host') == HOST, 'Nginx did not set the fixed upstream Host header')
    _require(
        observed_headers.get('x_forwarded_proto') == 'https',
        'Nginx did not set X-Forwarded-Proto to https for the secure request',
    )
    try:
        forwarded_ip = ipaddress.ip_address(observed_headers.get('x_forwarded_for', ''))
    except ValueError as exc:
        raise AcceptanceError('fake SSE upstream received an invalid X-Forwarded-For address') from exc
    _require(
        forwarded_ip != ipaddress.ip_address('198.51.100.44'),
        'Nginx preserved the caller-supplied X-Forwarded-For address',
    )
    for name in ('forwarded', 'x_forwarded_host', 'x_forwarded_port'):
        _require(observed_headers.get(name) is None, f'Nginx did not clear the {name} header')
    checks['fake_sse_proxy_header_echo'] = json.dumps(observed_headers, sort_keys=True)
    checks['real_client_address_observation'] = (
        'NOT_RUN: the fake upstream echo verifies proxy headers, not Django WSGI REMOTE_ADDR'
    )
    checks['sse_first_frame_ms'] = str(round(first_elapsed * 1000))
    checks['sse_total_ms'] = str(round(total_elapsed * 1000))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-ip', required=True)
    parser.add_argument('--ca-cert', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--news-id', type=int, default=1)
    parser.add_argument('--wrong-san-port', type=int, default=4443)
    parser.add_argument('--sse-only', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--chromium-executable')
    parser.add_argument('--image-revision')
    parser.add_argument('--nginx-image')
    parser.add_argument('--stage', choices=('g1', 'g2', 'g3'), default='g1')
    parser.add_argument('--fixture-bundle', type=Path)
    parser.add_argument('--fixture-state', type=Path)
    parser.add_argument('--compose-project')
    parser.add_argument('--compose-file', type=Path)
    parser.add_argument('--compose-env', type=Path)
    parser.add_argument('--gateway-container-id')
    parser.add_argument('--app-image-id')
    parser.add_argument('--gateway-image-id')
    parser.add_argument('--curl-image-id')
    parser.add_argument('--private-root', type=Path)
    parser.add_argument('--check-parents', action='store_true')
    parser.add_argument('--fixture-phase', choices=('seed',))
    args = parser.parse_args(argv)

    try:
        address = ipaddress.ip_address(args.gateway_ip)
    except ValueError as exc:
        parser.error('--gateway-ip must be a valid IP address')
        raise exc
    if not isinstance(address, ipaddress.IPv4Address):
        parser.error('--gateway-ip must be IPv4')
    if not 1 <= args.news_id <= 2**31 - 1:
        parser.error('--news-id is out of range')
    if not 1 <= args.wrong_san_port <= 65535:
        parser.error('--wrong-san-port is out of range')
    g2_mode = args.stage == 'g2' and not args.sse_only
    if args.check_parents and (not g2_mode or args.fixture_phase is not None):
        parser.error('--check-parents requires the ordinary G2 setup mode')
    if args.fixture_phase is not None and (not g2_mode or args.check_parents):
        parser.error('--fixture-phase requires the ordinary G2 setup mode')
    if args.stage == 'g2' and args.sse_only:
        if args.check_parents or args.fixture_phase is not None:
            parser.error('G2 SSE-only mode cannot run parent setup or account fixtures')
    elif g2_mode:
        if args.compose_project is None or args.compose_file is None or args.compose_env is None:
            parser.error('G2 requires its smoke-owned Compose project, file, and environment')
        if not re.fullmatch(r'newshub-local-g2-[0-9]+-[0-9a-f]{16}', args.compose_project):
            parser.error('--compose-project is not a smoke-owned G2 project')
        if args.gateway_container_id is not None and not CONTAINER_ID_PATTERN.fullmatch(args.gateway_container_id.lower()):
            parser.error('--gateway-container-id must be a full Docker container ID')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', args.app_image_id or ''):
            parser.error('--app-image-id must be an immutable Docker image ID')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', args.gateway_image_id or ''):
            parser.error('--gateway-image-id must be an immutable Docker image ID')

        needs_fixture = not args.check_parents
        needs_state = needs_fixture and args.fixture_phase is None
        needs_curl = needs_state
        if needs_fixture and (args.fixture_bundle is None or args.fixture_state is None or args.private_root is None):
            parser.error('G2 fixture mode requires bundle, state path, and private root')
        if needs_curl and not re.fullmatch(r'sha256:[a-f0-9]{64}', args.curl_image_id or ''):
            parser.error('--curl-image-id must be an immutable Docker image ID')
        if args.fixture_phase is not None and args.fixture_phase != 'seed':
            parser.error('unsupported G2 fixture phase')

        if args.private_root is not None:
            try:
                private_root = args.private_root.resolve(strict=True)
                args.private_root = private_root
                root_info = private_root.stat()
            except OSError:
                parser.error('--private-root must already exist')
            if not stat.S_ISDIR(root_info.st_mode) or stat.S_IMODE(root_info.st_mode) != 0o700 or root_info.st_uid != os.getuid():
                parser.error('--private-root must be smoke-owned mode 0700')

        required_existing = [args.compose_file, args.compose_env]
        if needs_fixture:
            required_existing.append(args.fixture_bundle)
        if needs_state:
            required_existing.append(args.fixture_state)
        for path in required_existing:
            try:
                resolved = path.resolve(strict=True)
                if args.private_root is not None and not resolved.is_relative_to(args.private_root):
                    parser.error('G2 private files must stay below --private-root')
                if path.is_symlink():
                    parser.error('G2 private files must not be symlinks')
                file_info = path.stat(follow_symlinks=False)
            except OSError:
                parser.error('G2 private input files must already exist')
            if not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != os.getuid():
                parser.error('G2 private files must be smoke-owned regular files')
            if stat.S_IMODE(file_info.st_mode) != 0o600:
                parser.error('G2 private files must remain mode 0600')

        if needs_fixture and args.fixture_bundle is not None:
            try:
                _fixtures.load_bundle(args.fixture_bundle)
            except (OSError, ValueError, json.JSONDecodeError):
                parser.error('--fixture-bundle must be a private smoke-owned mode-0600 file')

        if args.fixture_phase == 'seed':
            assert args.fixture_state is not None and args.private_root is not None
            state_parent = args.fixture_state.parent.resolve(strict=True)
            if state_parent != args.private_root or args.fixture_state.exists() or args.fixture_state.is_symlink():
                parser.error('seed fixture state must be a new path directly below --private-root')
            if args.gateway_container_id is None:
                parser.error('G2 seed requires the previously inspected gateway container ID')
        elif not args.check_parents and args.gateway_container_id is None:
            parser.error('G2 runtime requires the previously inspected gateway container ID')

        if args.check_parents or args.fixture_phase == 'seed':
            if args.report is None:
                parser.error('G2 parent and fixture-seed checks require a persistent --report path')
            try:
                report_root = args.work_dir.resolve(strict=True)
                report_root_info = report_root.stat()
                report_parent = args.report.parent.resolve(strict=True)
            except OSError:
                parser.error('G2 report directory must already exist')
            if (
                not stat.S_ISDIR(report_root_info.st_mode)
                or stat.S_IMODE(report_root_info.st_mode) != 0o700
                or report_root_info.st_uid != os.getuid()
                or report_parent != report_root
            ):
                parser.error('G2 setup and seed reports must stay in the smoke-owned mode-0700 report directory')
            if args.report.exists() or args.report.is_symlink():
                parser.error('G2 setup and seed reports must be new files')
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.stage == 'g3':
        print('NOT_RUN: G3 task/worker acceptance is not part of the G1/G2 harness.')
        return 3
    _require(args.ca_cert.is_file(), 'the temporary test CA certificate does not exist')
    _require(args.work_dir.is_dir(), 'the smoke-owned work directory does not exist')

    if args.check_parents:
        check = 'g2.parent_identity'
        try:
            parents = _inspect_g2_parents(args)
        except Exception as exc:
            result = _g2_failure_report(check, exc)
            _write_safe_report(args.report, result)
            print(json.dumps(result, sort_keys=True))
            return 1
        _write_safe_report(args.report, {
            'stage': 'g2', 'status': 'PASS', 'checks': {check: 'PASS'},
        })
        print(json.dumps(parents, sort_keys=True))
        return 0
    if args.fixture_phase == 'seed':
        check = 'g2.fixture_seed'
        try:
            bundle = _load_fixture_bundle(args.fixture_bundle)
            state = _run_fixture_program(args, bundle, 'seed')
            _require(
                state.get('users_seeded') == 2
                and isinstance(state.get('news_id'), int)
                and state['news_id'] > 0,
                'G2 seed returned an incomplete private fixture state',
            )
            _store_fixture_state(args.fixture_state, state)
        except Exception as exc:
            result = _g2_failure_report(check, exc)
            _write_safe_report(args.report, result)
            print(json.dumps(result, sort_keys=True))
            return 1
        result = {
            'stage': 'g2', 'status': 'PASS',
            'checks': {check: 'PASS'},
        }
        _write_safe_report(args.report, result)
        print(json.dumps(result, sort_keys=True))
        return 0

    checks: dict[str, str] = {}
    result = {
        'stage': args.stage,
        'status': 'PASS',
        'checks': checks,
        'image_revision': args.image_revision,
        'nginx_image': args.nginx_image,
    }
    active_check = f'{args.stage}.http_api'
    try:
        if args.sse_only:
            active_check = f'{args.stage}.sse'
            _run_sse_check(args, checks)
        else:
            _check_http_api(args, checks, args.work_dir)
            active_check = f'{args.stage}.shared_browser'
            _run_browser_checks(args, checks, args.work_dir)
            if args.stage == 'g2':
                active_check = 'g2.account_browser'
                asyncio.run(_run_g2_browser_checks(args, checks, args.work_dir))
                active_check = 'g2.rate_limits'
                _run_g2_rate_limit_checks(args, checks, _load_fixture_bundle(args.fixture_bundle))
    except Exception as exc:
        result['status'] = 'FAIL'
        if getattr(exc, 'cleanup_status', None) == 'FAIL':
            result['cleanup_status'] = 'FAIL'
        if args.stage == 'g2':
            result['failure'] = {
                'stage': 'g2',
                'check': active_check,
                'exception_type': type(exc).__name__,
            }
            result['failure'].update(_safe_http_failure_details(exc))
            screenshots = (
                args.work_dir / 'g2-browser-failure.png',
                args.work_dir / 'local-domain-browser-failure.png',
            )
        else:
            result['failure'] = f'{type(exc).__name__}: {exc}'
            screenshots = (args.work_dir / 'local-domain-browser-failure.png',)
        screenshot = next((path for path in screenshots if path.is_file()), None)
        if screenshot is not None:
            result['failure_screenshot'] = str(screenshot)
        if args.report:
            args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(json.dumps(result, sort_keys=True))
        return 1

    if args.report:
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
