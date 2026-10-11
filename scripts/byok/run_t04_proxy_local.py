#!/usr/bin/env python3
"""Run T04's real chat endpoint through the pinned T00 local Responses Proxy."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
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
LITELLM_IMAGE = 'ghcr.io/berriai/litellm@sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500'
MASTER_KEY = 'sk-t00-master-synthetic'
PROVIDER_KEY = 'sk-t00-provider-a-synthetic'
ENCRYPTION_KEY = base64.urlsafe_b64encode(b'0123456789abcdef0123456789abcdef').decode('ascii').rstrip('=')


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())


def _run(command, *, cwd, env=None, timeout=300):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _json_request(url, *, method='GET', payload=None, bearer=None):
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
            body = json.loads(response.read(128 * 1024))
            return response.status, body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read(128 * 1024))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        return error.code, body if isinstance(body, dict) else {}


def _compose_command(project, fixture_dir, *args):
    command = ['docker', 'compose', '--project-name', project, '-f', str(fixture_dir / 'compose.yaml')]
    command.extend(args)
    return command


def _compose(project, fixture_dir, *args, timeout=300):
    return _run(_compose_command(project, fixture_dir, *args), cwd=fixture_dir, timeout=timeout)


def _wait_ready(url, timeout_seconds=90):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status, _body = _json_request(url)
            if status == 200:
                return True
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return False


def _prepare_fixture(t00_worktree, temp_dir):
    source = t00_worktree / 'tools' / 'byok_t00_probe'
    required = ('compose.yaml', 'proxy.yaml', 'proxy_callback.py', 'upstream.py')
    if not source.is_dir() or any(not (source / name).is_file() for name in required):
        raise ValueError('t00_fixture_missing')
    fixture_dir = temp_dir / 't00_fixture'
    fixture_dir.mkdir(mode=0o700)
    for name in required:
        shutil.copyfile(source / name, fixture_dir / name)
    proxy_config = fixture_dir / 'proxy.yaml'
    text = proxy_config.read_text(encoding='utf-8')
    if LITELLM_IMAGE not in (fixture_dir / 'compose.yaml').read_text(encoding='utf-8'):
        raise ValueError('litellm_image_not_pinned')
    if 'model_name: t00-deepseek-smoke' not in text:
        raise ValueError('deepseek_test_route_missing')
    proxy_config.write_text(text.replace('model_name: t00-deepseek-smoke', 'model_name: news.deepseek-flash'), encoding='utf-8')
    return fixture_dir


def _container_info(project, fixture_dir, service):
    rows = _compose(project, fixture_dir, 'ps', '-q', service, timeout=20)
    container_id = rows.stdout.decode('ascii', errors='ignore').strip()
    if rows.returncode != 0 or not container_id:
        return None
    inspected = _run(['docker', 'inspect', container_id], cwd=fixture_dir, timeout=20)
    if inspected.returncode != 0:
        return None
    try:
        container = json.loads(inspected.stdout)[0]
        network_info = next(iter(container['NetworkSettings']['Networks'].values()))
        address = ipaddress.ip_address(network_info['IPAddress'])
    except (IndexError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    except ValueError:
        return None
    if not address.is_private:
        return None
    return container, address.compressed


def _proxy_image_matches(fixture_dir, container, expected_image):
    try:
        configured_image = container['Config']['Image']
        image_id = container['Image']
    except (KeyError, TypeError):
        return False
    resolved = _run(['docker', 'image', 'inspect', expected_image], cwd=fixture_dir, timeout=20)
    if resolved.returncode != 0:
        return False
    try:
        resolved_id = json.loads(resolved.stdout)[0]['Id']
    except (IndexError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return configured_image == expected_image and image_id == resolved_id


def _local_sdk_diagnostic(proxy_url, project_key, provider_key):
    """One synthetic direct SDK request, used only after the Django path fails."""
    try:
        import httpx2
        from openai import OpenAI

        http_client = httpx2.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx2.Timeout(15, connect=5),
        )
        client = OpenAI(
            api_key=project_key,
            base_url=proxy_url.rstrip('/') + '/v1',
            http_client=http_client,
            max_retries=0,
            timeout=15,
        )
        try:
            stream = client.responses.create(
                model='news.deepseek-flash',
                input=[{'role': 'user', 'content': 'T00_T04_RUNNER_DIAGNOSTIC_A'}],
                max_output_tokens=32,
                store=False,
                stream=True,
                extra_body={'api_key': provider_key},
            )
            terminal = 'none'
            with stream:
                for event in stream:
                    if getattr(event, 'type', '').startswith('response.'):
                        terminal = getattr(event, 'type', 'unknown')
            return terminal if terminal in {'response.completed', 'response.incomplete', 'response.failed'} else 'unexpected_terminal'
        except Exception as error:
            status = getattr(error, 'status_code', None)
            status_label = str(status) if isinstance(status, int) and 100 <= status <= 599 else 'none'
            type_name = type(error).__name__
            safe_types = {
                'APIConnectionError', 'APIStatusError', 'AuthenticationError',
                'BadRequestError', 'NotFoundError', 'InternalServerError',
                'TimeoutException', 'ConnectError', 'TypeError', 'ValueError',
            }
            return (type_name if type_name in safe_types else 'other') + '_http_' + status_label
        finally:
            client.close()
    except Exception as error:
        type_name = type(error).__name__
        return type_name if type_name in {'ImportError', 'ModuleNotFoundError', 'TypeError', 'ValueError'} else 'diagnostic_setup_failed'


def _run_test(t00_worktree):
    for dotenv in (REPO_ROOT / '.env', BACKEND_DIR / '.env'):
        if dotenv.exists():
            raise ValueError('dotenv_present_test_refused')
    if not (TEST_STUBS / 'chromadb.py').is_file():
        raise ValueError('isolated_test_stub_missing')

    project = f'byok-t04-{secrets.token_hex(4)}'
    provider_key = PROVIDER_KEY
    project_key = ''
    summary = {
        'scope': 'T04_PROXY_LOCAL_SYNTHETIC_ONLY',
        'sdk_local': 'PASS',
        'proxy_local': 'NOT_RUN',
        'provider_real': 'NOT_RUN',
        'model_alias': 'news.deepseek-flash',
        'upstream_request_count': 0,
        'provider_key_only_at_upstream': False,
        'no_retry_or_fallback': False,
        'secret_leak_check': 'NOT_RUN',
        'cleanup': 'NOT_RUN',
    }

    with tempfile.TemporaryDirectory(prefix=f'{project}-') as directory:
        temp = Path(directory)
        fixture_dir = _prepare_fixture(t00_worktree, temp)
        attempted_start = False
        try:
            attempted_start = True
            up = _compose(
                project,
                fixture_dir,
                '--profile', 'native-stream',
                'up', '-d', '--wait', '--wait-timeout', '180',
                'db', 'upstream', 'native_stream_proxy',
                timeout=240,
            )
            if up.returncode != 0:
                raise ValueError('proxy_stack_start_failed')
            proxy_info = _container_info(project, fixture_dir, 'native_stream_proxy')
            upstream_info = _container_info(project, fixture_dir, 'upstream')
            if proxy_info is None or upstream_info is None:
                raise ValueError('gateway_network_lookup_failed')
            if not _proxy_image_matches(fixture_dir, proxy_info[0], LITELLM_IMAGE):
                raise ValueError('proxy_image_mismatch')

            proxy_url = f'http://{proxy_info[1]}:4002'
            upstream_url = f'http://{upstream_info[1]}:8080'
            if not _wait_ready(proxy_url + '/health/liveliness'):
                raise ValueError('proxy_readiness_timeout')
            if not _wait_ready(upstream_url + '/healthz'):
                raise ValueError('upstream_readiness_timeout')

            key_status, key_result = _json_request(
                proxy_url + '/key/generate',
                method='POST',
                payload={
                    'models': ['news.deepseek-flash'],
                    'key_alias': 't04-local-test',
                    'metadata': {'project': 't04-local-test'},
                    'max_budget': 1.0,
                    'budget_duration': '1d',
                    'rpm_limit': 10,
                    'tpm_limit': 10000,
                    'max_parallel_requests': 1,
                    'duration': '1d',
                },
                bearer=MASTER_KEY,
            )
            project_key = key_result.get('key') if key_status == 200 else ''
            if not isinstance(project_key, str) or not project_key.startswith('sk-'):
                raise ValueError('project_virtual_key_provision_failed')
            expectations_status, _expectations = _json_request(
                upstream_url + '/test/expectations',
                method='POST',
                payload={'project_key_sha256': [hashlib.sha256(project_key.encode()).hexdigest()]},
            )
            if expectations_status != 200:
                raise ValueError('controlled_upstream_setup_failed')

            test_env = {
                'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                'HOME': str(temp / 'home'),
                'PYTHONPATH': os.pathsep.join((str(TEST_STUBS), str(BACKEND_DIR))),
                'DJANGO_ENV': 'development',
                'DJANGO_SECRET_KEY': 't04-proxy-local-synthetic-django-secret-only',
                'DJANGO_DB_PATH': str(temp / 't04-proxy-local.sqlite3'),
                'AI_BYOK_ENABLED': '1',
                'AI_CONNECTION_ENCRYPTION_KEY': ENCRYPTION_KEY,
                'AI_CONNECTION_ENCRYPTION_KEY_ID': 't04-proxy-local-v1',
                'AI_BYOK_GATEWAY_URL': proxy_url,
                'AI_BYOK_GATEWAY_PROJECT_KEY': project_key,
                'PUBLIC_SITE_MODE': 'full',
                'PUBLIC_AI_ENABLED': '1',
                'PUBLIC_SIGNUP_ENABLED': '0',
                'CHATGPT_AUTH_MODE': 'local_oss',
                'CHATGPT_PLAN_USAGE_ENABLED': '0',
                'CHROMA_DATA_DIR': str(temp / 'chroma'),
                'TTS_CACHE_DIR': str(temp / 'tts-cache'),
                'XDG_CACHE_HOME': str(temp / 'xdg-cache'),
                'T04_PROXY_LOCAL': '1',
                'T04_SYNTHETIC_PROVIDER_KEY': provider_key,
            }
            for name in ('home', 'chroma', 'tts-cache', 'xdg-cache'):
                (temp / name).mkdir(mode=0o700)
            test = _run(
                [sys.executable, '-m', 'pytest', '-q', 'api/tests/test_ai_chat_proxy_local.py'],
                cwd=BACKEND_DIR,
                env=test_env,
                timeout=180,
            )
            test_output = (
                test.stdout.decode('utf-8', errors='replace')
                + '\n'
                + test.stderr.decode('utf-8', errors='replace')
            )
            if test.returncode != 0 or '1 passed' not in test_output:
                failed_cases = [
                    line.strip().split(' - ', 1)[0]
                    for line in test_output.splitlines()
                    if line.strip().startswith(('FAILED ', 'ERROR '))
                ][:4]
                detail = ':'.join(failed_cases) if failed_cases else 'pytest_nonpass'
                assertion_lines = [
                    line.strip()
                    for line in test_output.splitlines()
                    if re.match(r'E\s+assert\s+', line.strip())
                ]
                if assertion_lines:
                    safe_assertion = assertion_lines[0]
                    for secret in (provider_key, project_key, MASTER_KEY):
                        if secret:
                            safe_assertion = safe_assertion.replace(secret, '[redacted]')
                    safe_assertion = re.sub(r'sk-[A-Za-z0-9_-]{8,}', '[redacted]', safe_assertion)
                    safe_assertion = re.sub(r'[^A-Za-z0-9_. =<>!-]', '?', safe_assertion)[:160]
                    detail += ':' + safe_assertion
                known_error_codes = {
                    'model_not_found', 'model_not_configured', 'model_unavailable',
                    'model_reselection_required', 'model_route_unavailable',
                    'gateway_unavailable', 'provider_unavailable', 'provider_rejected',
                    'incomplete_response', 'empty_response', 'execution_changed',
                }
                error_codes = sorted(set(re.findall(r'"code"\s*:\s*"([a-z_]+)"', test_output)) & known_error_codes)
                if error_codes:
                    detail += ':safe_error_code=' + ','.join(error_codes[:3])
                direct_diagnostic = _local_sdk_diagnostic(proxy_url, project_key, provider_key)
                detail += ':direct_sdk=' + direct_diagnostic
                stats_status, stats = _json_request(upstream_url + '/stats')
                failed_rows = stats.get('records', []) if stats_status == 200 else []
                if isinstance(failed_rows, list) and failed_rows:
                    safe_rows = [
                        '/'.join(str(row.get(field, 'unknown')) for field in (
                            'test_id', 'protocol', 'tenant', 'upstream_terminal', 'provider_key_match',
                        ))
                        for row in failed_rows[:4]
                        if isinstance(row, dict)
                    ]
                    if safe_rows:
                        detail += ':upstream=' + ','.join(safe_rows)
                failure_logs = _compose(
                    project, fixture_dir, 'logs', '--no-color', 'native_stream_proxy', timeout=30,
                )
                failure_log_text = (
                    failure_logs.stdout.decode('utf-8', errors='replace')
                    + failure_logs.stderr.decode('utf-8', errors='replace')
                )
                safe_signatures = {
                    'BYOK_PROVIDER_KEY_REQUIRED': 'provider_key_missing_at_proxy',
                    'T00_STREAMING_DISABLED': 'streaming_denied_at_proxy',
                    'AuthenticationError': 'proxy_authentication_error',
                    'BadRequestError': 'proxy_bad_request',
                    'NotFoundError': 'proxy_route_not_found',
                    'APIConnectionError': 'proxy_connection_error',
                }
                matched_signatures = [
                    label for marker, label in safe_signatures.items() if marker in failure_log_text
                ]
                if matched_signatures:
                    detail += ':proxy_diagnostic=' + ','.join(matched_signatures[:3])
                raise ValueError(f'django_proxy_chat_integration_failed:{detail}')

            stats_status, stats = _json_request(upstream_url + '/stats')
            rows = stats.get('records', []) if stats_status == 200 else []
            summary['upstream_request_count'] = len(rows) if isinstance(rows, list) else 0
            expected_turns = {
                'T00_T04_PROXY_STREAM_A': 'finish_reason_stop',
                'T00_T04_PROXY_INCOMPLETE_A': 'finish_reason_length',
            }
            provider_only = (
                isinstance(rows, list)
                and len(rows) == len(expected_turns)
                and {row.get('test_id') for row in rows if isinstance(row, dict)} == set(expected_turns)
                and all(
                    row.get('protocol') == 'completions'
                    and row.get('upstream_terminal') == expected_turns.get(row.get('test_id'))
                    and row.get('tenant') == 'tenant-a'
                    and row.get('expected_tenant') == 'tenant-a'
                    and row.get('provider_key_match') is True
                    and row.get('provider_auth_scheme') == 'bearer'
                    and row.get('project_key_match') is False
                    and row.get('master_key_match') is False
                    and row.get('admin_key_match') is False
                    and row.get('deployment_default_match') is False
                    and row.get('wrong_provider_header_present') is False
                    for row in rows if isinstance(row, dict)
                )
            )
            summary['provider_key_only_at_upstream'] = provider_only
            summary['no_retry_or_fallback'] = provider_only
            if not provider_only:
                raise ValueError('upstream_provider_boundary_failed')

            logs = _compose(project, fixture_dir, 'logs', '--no-color', 'upstream', 'native_stream_proxy', timeout=30)
            log_text = logs.stdout.decode('utf-8', errors='replace') + logs.stderr.decode('utf-8', errors='replace')
            secrets_to_scan = [provider_key, project_key, MASTER_KEY, 't00_password_synthetic']
            leaked = any(value and value in log_text for value in secrets_to_scan)
            summary['secret_leak_check'] = 'FAIL' if leaked else 'PASS'
            if leaked:
                raise ValueError('secret_found_in_local_gateway_logs')
            summary['proxy_local'] = 'PASS'
            summary['status'] = 'PASS'
        except Exception as error:
            summary['status'] = 'FAIL'
            summary['error_code'] = str(error) if isinstance(error, ValueError) else 'runner_error'
        finally:
            if attempted_start:
                try:
                    down = _compose(
                        project,
                        fixture_dir,
                        '--profile', 'native-stream',
                        'down', '--volumes', '--remove-orphans',
                        timeout=120,
                    )
                    summary['cleanup'] = 'PASS' if down.returncode == 0 else 'FAIL'
                except Exception:
                    summary['cleanup'] = 'FAIL'
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--t00-worktree', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary = _run_test(args.t00_worktree.resolve())
    except Exception as error:
        summary = {
            'scope': 'T04_PROXY_LOCAL_SYNTHETIC_ONLY',
            'status': 'FAIL',
            'error_code': str(error) if isinstance(error, ValueError) else 'runner_error',
            'sdk_local': 'PASS',
            'proxy_local': 'NOT_RUN',
            'provider_real': 'NOT_RUN',
            'cleanup': 'UNKNOWN',
        }
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary.get('status') == 'PASS' and summary.get('cleanup') == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
