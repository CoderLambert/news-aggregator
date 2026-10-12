#!/usr/bin/env python3
"""Run T02's Django model-test API through an isolated T00-G LiteLLM Proxy stack."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / 'backend'
TEST_STUBS = Path('/tmp/byok-t02-test-stubs')
PYTHON_ENV = {
    'DJANGO_ENV': 'development',
    'DJANGO_SECRET_KEY': 't02-proxy-local-synthetic-django-secret-only',
    'AI_BYOK_ENABLED': '1',
    'AI_CONNECTION_ENCRYPTION_KEY': base64.urlsafe_b64encode(b'0123456789abcdef0123456789abcdef').decode('ascii').rstrip('='),
    'AI_CONNECTION_ENCRYPTION_KEY_ID': 't02-proxy-local-v1',
    'PUBLIC_SITE_MODE': 'full',
    'PUBLIC_AI_ENABLED': '1',
    'PUBLIC_SIGNUP_ENABLED': '0',
    'CHATGPT_AUTH_MODE': 'local_oss',
    'CHATGPT_PLAN_USAGE_ENABLED': '0',
    'T02_PROXY_LOCAL': '1',
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())


def _run(command: list[str], *, cwd: Path, env=None, input_bytes=None, timeout=300):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _json_request(url: str, *, method='GET', payload=None, bearer=None):
    headers = {'Accept': 'application/json'}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if bearer:
        headers['Authorization'] = f'Bearer {bearer}'
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with HTTP.open(request, timeout=10) as response:
            raw = response.read(128 * 1024)
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as error:
        raw = error.read(128 * 1024)
        try:
            body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        return error.code, body


def _compose_command(compose_files: list[Path], project: str, env_file: Path, *args: str) -> list[str]:
    command = ['docker', 'compose', '--project-name', project, '--env-file', str(env_file)]
    for compose_file in compose_files:
        command.extend(['-f', str(compose_file)])
    command.extend(args)
    return command


def _compose(compose_files, project, env_file, *args, input_bytes=None, timeout=300):
    return _run(
        _compose_command(compose_files, project, env_file, *args),
        cwd=compose_files[0].parent,
        input_bytes=input_bytes,
        timeout=timeout,
    )


def _client_request(compose_files, project, env_file, *, target, path, method='GET', payload=None, bearer=None):
    spec = {'target': target, 'path': path, 'method': method, 'payload': payload, 'bearer': bearer}
    result = _compose(
        compose_files,
        project,
        env_file,
        'exec', '-T', 'newshub-test-client', 'python', '/fixtures/cli_client.py',
        input_bytes=json.dumps(spec, ensure_ascii=True, separators=(',', ':')).encode('utf-8'),
        timeout=30,
    )
    try:
        decoded = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0, {}
    body = decoded.get('body', {})
    return int(decoded.get('status', 0)), body if isinstance(body, dict) else {}


def _wait_ready(url: str, timeout_seconds: int = 150) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status, _body = _json_request(url)
            if status == 200:
                return True
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(1)
    return False


def _validate_gateway_source(root: Path) -> list[Path]:
    proxy_root = root / 'ops' / 'shared-litellm-proxy'
    compose_files = [proxy_root / 'compose.yaml', proxy_root / 'compose.test.yaml']
    required = [
        *compose_files,
        proxy_root / 'proxy.test.yaml',
        proxy_root / 'tests' / 'upstream.py',
        proxy_root / 'tests' / 'cli_client.py',
    ]
    if not all(path.is_file() for path in required):
        raise ValueError('gateway_test_source_invalid')
    return compose_files


def _run_test(gateway_root: Path) -> dict:
    for dotenv in (REPO_ROOT / '.env', BACKEND_DIR / '.env'):
        if dotenv.exists():
            raise ValueError('dotenv_present_test_refused')
    if not (TEST_STUBS / 'chromadb.py').is_file():
        raise ValueError('isolated_test_stub_missing')

    compose_files = _validate_gateway_source(gateway_root)
    project = f'byok-t02-{secrets.token_hex(4)}'
    provider_key = 'sk-t02-provider-' + secrets.token_hex(20)
    project_key = ''
    master_key = 'sk-' + secrets.token_hex(32)
    secret_values = {
        'postgres_password': secrets.token_hex(32),
        'litellm_master_key': master_key,
        'litellm_salt_key': secrets.token_hex(32),
    }
    proxy_url = ''
    summary = {
        'scope': 'T02_PROXY_LOCAL_SYNTHETIC_ONLY',
        'provider_real': 'NOT_RUN',
        'proxy_target': 'isolated_docker_gateway_bridge',
        'provider_key_label': 't02-provider',
        'model_alias': 'news.deepseek-flash',
        'text_probe': 'NOT_RUN',
        'tools_probe': 'NOT_RUN',
        'upstream_request_count': 0,
        'provider_key_only_at_upstream': False,
        'secret_leak_check': 'NOT_RUN',
    }

    with tempfile.TemporaryDirectory(prefix=f'{project}-') as temporary:
        temp = Path(temporary)
        secrets_dir = temp / 'secrets'
        secrets_dir.mkdir(mode=0o700)
        secret_paths = {}
        for name, value in secret_values.items():
            path = secrets_dir / name
            path.write_text(value, encoding='utf-8')
            path.chmod(0o600)
            secret_paths[name] = path

        env_file = temp / 'compose.env'
        env_values = {
            'POSTGRES_DB': 'litellm',
            'POSTGRES_USER': 'litellm',
            'POSTGRES_PASSWORD_FILE': str(secret_paths['postgres_password']),
            'LITELLM_MASTER_KEY_FILE': str(secret_paths['litellm_master_key']),
            'LITELLM_SALT_KEY_FILE': str(secret_paths['litellm_salt_key']),
            'GATEWAY_BACKEND_NETWORK': f'{project}-backend',
            'GATEWAY_EGRESS_NETWORK': f'{project}-provider-egress',
            'PROVIDER_EGRESS_INTERNAL': 'true',
            'T00G_TEST_PROVIDER_KEY_HASHES': json.dumps({'t02-provider': _sha(provider_key)}, separators=(',', ':')),
        }
        env_file.write_text(''.join(f'{name}={value}\n' for name, value in env_values.items()), encoding='utf-8')
        env_file.chmod(0o600)

        attempted_start = False
        try:
            attempted_start = True
            up = _compose(
                compose_files, project, env_file,
                '--profile', 'test', 'up', '-d', '--wait', '--wait-timeout', '240', timeout=300,
            )
            if up.returncode != 0:
                raise ValueError('proxy_stack_start_failed')
            proxy_ids = _compose(compose_files, project, env_file, 'ps', '-q', 'proxy', timeout=30)
            container_id = proxy_ids.stdout.decode('utf-8', errors='replace').strip()
            if proxy_ids.returncode != 0 or not container_id:
                raise ValueError('proxy_container_lookup_failed')
            inspected = _run(['docker', 'inspect', container_id], cwd=compose_files[0].parent, timeout=30)
            if inspected.returncode != 0:
                raise ValueError('proxy_container_inspect_failed')
            try:
                container = json.loads(inspected.stdout)[0]
                network = container['NetworkSettings']['Networks'][f'{project}-backend']
                bridge_ip = ipaddress.ip_address(network['IPAddress'])
            except (IndexError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ValueError('proxy_gateway_network_lookup_failed') from None
            if not bridge_ip.is_private:
                raise ValueError('proxy_gateway_network_not_private')
            proxy_url = f'http://{bridge_ip.compressed}:4000'
            if not _wait_ready(proxy_url + '/health/readiness'):
                raise ValueError('proxy_readiness_timeout')

            key_status, key_response = _json_request(
                proxy_url + '/key/generate',
                method='POST',
                payload={
                    'models': ['news.deepseek-flash'],
                    'key_alias': 't02-local-test',
                    'metadata': {'project': 't02-local-test'},
                    'max_budget': 1.0,
                    'budget_duration': '1d',
                    'rpm_limit': 10,
                    'tpm_limit': 1000,
                    'max_parallel_requests': 1,
                    'duration': '1d',
                },
                bearer=master_key,
            )
            project_key = key_response.get('key') if key_status == 200 and isinstance(key_response, dict) else ''
            if not isinstance(project_key, str) or not project_key.startswith('sk-'):
                raise ValueError('project_virtual_key_provision_failed')

            expectations_status, _expectations = _client_request(
                compose_files, project, env_file,
                target='test-upstream',
                path='/test/expectations',
                method='POST',
                payload={
                    'provider_key_hashes': {'t02-provider': _sha(provider_key)},
                    'project_key_hashes': [_sha(project_key)],
                    'master_key_hash': _sha(master_key),
                },
            )
            if expectations_status != 200:
                raise ValueError('synthetic_upstream_setup_failed')

            test_env = {
                'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                'HOME': str(temp / 'home'),
                'PYTHONPATH': os.pathsep.join((str(TEST_STUBS), str(BACKEND_DIR))),
                **PYTHON_ENV,
                'DJANGO_DB_PATH': str(temp / 't02-proxy-local.sqlite3'),
                'CHROMA_DATA_DIR': str(temp / 'chroma'),
                'TTS_CACHE_DIR': str(temp / 'tts-cache'),
                'AI_BYOK_GATEWAY_URL': proxy_url,
                'AI_BYOK_GATEWAY_PROJECT_KEY': project_key,
                'T02_SYNTHETIC_PROVIDER_KEY': provider_key,
                'XDG_CACHE_HOME': str(temp / 'xdg-cache'),
            }
            for directory_name in ('home', 'chroma', 'tts-cache', 'xdg-cache'):
                (temp / directory_name).mkdir(mode=0o700)

            test = _run(
                [sys.executable, '-m', 'pytest', '-q', 'api/tests/test_ai_model_proxy_local.py'],
                cwd=BACKEND_DIR,
                env=test_env,
                timeout=180,
            )
            if test.returncode != 0:
                raise ValueError('django_proxy_integration_failed')
            test_output = test.stdout.decode('utf-8', errors='replace')
            if '1 passed' not in test_output:
                raise ValueError('django_proxy_integration_not_executed')
            summary['text_probe'] = 'PASS'
            summary['tools_probe'] = 'PASS_FAILED_SAFELY'

            records_status, records = _client_request(
                compose_files, project, env_file, target='test-upstream', path='/test/records',
            )
            upstream_rows = records.get('records', []) if records_status == 200 else []
            summary['upstream_request_count'] = len(upstream_rows) if isinstance(upstream_rows, list) else 0
            provider_only = (
                isinstance(upstream_rows, list)
                and len(upstream_rows) == 2
                and all(row.get('provider_label') == 't02-provider' for row in upstream_rows)
                and all(row.get('authorization_class') == 'provider_key' for row in upstream_rows)
                and all(row.get('provider_auth_header') == 'authorization' for row in upstream_rows)
                and all(row.get('authorization_header_count') == 1 for row in upstream_rows)
                and not any(row.get('project_key_forwarded') or row.get('master_key_forwarded') for row in upstream_rows)
                and not any(row.get('project_key_hash_forwarded') or row.get('master_key_hash_forwarded') for row in upstream_rows)
                and not any(row.get('body_api_key_present') for row in upstream_rows)
            )
            summary['provider_key_only_at_upstream'] = provider_only
            leaked = any(
                value and value in json.dumps(upstream_rows, ensure_ascii=True)
                for value in [provider_key, project_key, master_key, *secret_values.values()]
            )
            summary['secret_leak_check'] = 'FAIL' if leaked else 'PASS'
            if not provider_only or leaked:
                raise ValueError('upstream_credential_boundary_failed')

            proxy_logs = _compose(compose_files, project, env_file, 'logs', '--no-color', 'proxy', timeout=30)
            log_text = proxy_logs.stdout.decode('utf-8', errors='replace') + proxy_logs.stderr.decode('utf-8', errors='replace')
            if any(value and value in log_text for value in [provider_key, project_key, master_key, *secret_values.values()]):
                summary['secret_leak_check'] = 'FAIL'
                raise ValueError('secret_found_in_proxy_logs')
            summary['provider_real'] = 'NOT_RUN'
            summary['status'] = 'PASS'
            return summary
        finally:
            if attempted_start:
                down = _compose(
                    compose_files, project, env_file, '--profile', 'test', 'down',
                    '--volumes', '--remove-orphans', timeout=120,
                )
                summary['cleanup'] = 'PASS' if down.returncode == 0 else 'FAIL'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-worktree', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary = _run_test(args.gateway_worktree.resolve())
    except Exception as error:
        summary = {
            'scope': 'T02_PROXY_LOCAL_SYNTHETIC_ONLY',
            'status': 'FAIL',
            'error_code': str(error) if isinstance(error, ValueError) else 'runner_error',
            'provider_real': 'NOT_RUN',
        }
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
        return 1
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary.get('status') == 'PASS' and summary.get('cleanup') == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
