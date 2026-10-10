import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


PROJECT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT / 'scripts' / 'deploy' / 'local_domain_acceptance.py'
SPEC = importlib.util.spec_from_file_location('local_domain_acceptance', MODULE_PATH)
acceptance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(acceptance)


@pytest.mark.parametrize(('scheme', 'request_target'), [
    ('http', 'http://news.lambert.host/'),
    ('https', 'https://news.lambert.host/'),
])
def test_absolute_uri_host_negative_keeps_tls_validation_and_fixed_host(scheme, request_target):
    args = SimpleNamespace(gateway_ip='127.0.0.1', ca_cert=Path('/tmp/local-domain-test-ca.pem'))
    with patch.object(acceptance.shutil, 'which', return_value='/usr/bin/curl'):
        command = acceptance._curl_command(
            args,
            '/',
            scheme=scheme,
            headers=('Host: evil.invalid',),
            request_target=request_target,
        )

    target_index = command.index('--request-target')
    assert command[target_index + 1] == request_target
    assert command[command.index('--header') + 1] == 'Host: evil.invalid'
    assert command[-1] == f'{scheme}://news.lambert.host:{443 if scheme == "https" else 80}/'
    assert '--cacert' in command if scheme == 'https' else '--cacert' not in command
    assert '-k' not in command
    assert '--insecure' not in command


@pytest.mark.parametrize(('scheme', 'exit_code'), [('http', 52), ('https', 56)])
def test_absolute_uri_unknown_host_requires_strict_connection_close(scheme, exit_code):
    args = SimpleNamespace(gateway_ip='127.0.0.1', ca_cert=Path('/tmp/local-domain-test-ca.pem'))
    checks = {}
    response = subprocess.CompletedProcess(
        ['curl'], exit_code, f'{acceptance.STATUS_MARKER}000', 'connection closed',
    )
    with (
        patch.object(acceptance, '_curl_command', return_value=['curl', '--request-target']),
        patch.object(acceptance.subprocess, 'run', return_value=response) as run,
    ):
        acceptance._check_absolute_uri_unknown_host(args, checks, scheme=scheme)

    assert run.call_args.args[0] == ['curl', '--request-target']
    assert checks[f'absolute_uri_unknown_{scheme}_host'] == 'connection closed by Nginx 444'


def test_absolute_uri_unknown_host_rejects_a_successful_http_response():
    args = SimpleNamespace(gateway_ip='127.0.0.1', ca_cert=Path('/tmp/local-domain-test-ca.pem'))
    response = subprocess.CompletedProcess(
        ['curl'], 0,
        f'HTTP/1.1 200 OK\n\nfixture{acceptance.STATUS_MARKER}200',
        '',
    )
    with (
        patch.object(acceptance, '_curl_command', return_value=['curl']),
        patch.object(acceptance.subprocess, 'run', return_value=response),
    ):
        with pytest.raises(acceptance.AcceptanceError, match='absolute-URI HTTPS request'):
            acceptance._check_absolute_uri_unknown_host(args, {}, scheme='https')


def test_forwarded_header_spoof_uses_non_exempt_real_csrf_path_and_checks_secure_cookie(tmp_path):
    args = SimpleNamespace()
    checks = {}
    calls = []

    def expect_status(_args, result_checks, name, path, expected, **kwargs):
        calls.append((name, path, expected, kwargs))
        result_checks[name] = f'HTTP {expected}'
        return '{"csrfToken":"fixture"}', {
            'set-cookie': ['csrftoken=fixture; Path=/; SameSite=Lax; Secure'],
        }

    with patch.object(acceptance, '_expect_status', side_effect=expect_status):
        acceptance._check_forwarded_header_secure_request(args, checks, tmp_path)

    assert len(calls) == 1
    name, path, expected, kwargs = calls[0]
    assert (name, path, expected) == ('real_django_secure_request', '/api/auth/csrf/', 200)
    assert path != '/api/health/live/'
    assert kwargs['headers'] == acceptance.FORWARDED_SPOOF_HEADERS
    assert checks['real_django_secure_request'].startswith('HTTP 200 on non-exempt CSRF path')
    assert checks['real_client_address_observation'].startswith('NOT_RUN:')


@pytest.mark.parametrize(('scheme', 'exit_code'), [('http', 52), ('https', 52), ('https', 56)])
def test_closed_without_http_response_accepts_only_expected_empty_status(scheme, exit_code):
    result = subprocess.CompletedProcess(
        ['curl'], exit_code, f'{acceptance.STATUS_MARKER}000',
        'curl: connection closed without an HTTP response',
    )
    assert acceptance._curl_closed_without_http_response(result, scheme=scheme)


@pytest.mark.parametrize(('scheme', 'exit_code'), [
    ('http', 56),
    ('http', 35), ('http', 60), ('http', 28), ('http', 7),
    ('https', 35), ('https', 60), ('https', 28), ('https', 7),
])
def test_closed_without_http_response_rejects_unapproved_curl_exit_codes(scheme, exit_code):
    result = subprocess.CompletedProcess(['curl'], exit_code, f'{acceptance.STATUS_MARKER}000', '')
    assert not acceptance._curl_closed_without_http_response(result, scheme=scheme)


@pytest.mark.parametrize(('scheme', 'exit_code'), [('http', 52), ('https', 52), ('https', 56)])
def test_closed_without_http_response_rejects_output_with_http_status_line(scheme, exit_code):
    result = subprocess.CompletedProcess(
        ['curl'], exit_code,
        f'HTTP/1.1 444 No Response\n\n{acceptance.STATUS_MARKER}000',
        '',
    )
    assert not acceptance._curl_closed_without_http_response(result, scheme=scheme)


@pytest.mark.parametrize(('status', 'body'), [(200, 'ok'), (403, 'forbidden')])
def test_closed_without_http_response_rejects_normal_http_responses(status, body):
    result = subprocess.CompletedProcess(
        ['curl'], 0,
        f'HTTP/1.1 {status} Response\n\n{body}{acceptance.STATUS_MARKER}{status}',
        '',
    )
    assert not acceptance._curl_closed_without_http_response(result, scheme='https')


def _run_sse_with_headers(observed_headers):
    args = SimpleNamespace(news_id=17)
    checks = {}
    encoded_headers = json.dumps(observed_headers, sort_keys=True).encode('utf-8')
    body = (
        b'\ndata: proxy-headers=' + encoded_headers + b'\n\n'
        b'data: final-frame\n\n'
    )
    process = SimpleNamespace(
        stdout=SimpleNamespace(readline=lambda: b'data: first-frame\n'),
        returncode=0,
        communicate=lambda timeout: (body, b''),
    )
    with (
        patch.object(
            acceptance,
            '_curl_command',
            return_value=['curl', '--max-time', '12', '--connect-timeout', '3'],
        ) as make_command,
        patch.object(acceptance.subprocess, 'Popen', return_value=process),
        patch.object(acceptance.time, 'monotonic', side_effect=[10.0, 10.1, 11.1]),
    ):
        acceptance._run_sse_check(args, checks)

    assert make_command.call_args.kwargs['headers'] == acceptance.FORWARDED_SPOOF_HEADERS
    return checks


def test_fake_sse_echo_proves_nginx_overwrites_and_clears_forwarding_headers():
    checks = _run_sse_with_headers({
        'host': acceptance.HOST,
        'x_forwarded_proto': 'https',
        'x_forwarded_for': '172.30.0.1',
        'forwarded': None,
        'x_forwarded_host': None,
        'x_forwarded_port': None,
    })

    assert 'fake_sse_proxy_header_echo' in checks
    assert checks['sse_first_frame_ms'] == '100'
    assert checks['sse_total_ms'] == '1100'
    assert checks['real_client_address_observation'].startswith('NOT_RUN:')


def test_fake_sse_echo_rejects_a_preserved_spoofed_header():
    for changed_header, value in (
        ('x_forwarded_proto', 'http'),
        ('x_forwarded_for', '198.51.100.44'),
        ('forwarded', 'proto=http;host=spoof.invalid'),
        ('x_forwarded_host', 'spoof.invalid'),
        ('x_forwarded_port', '80'),
    ):
        observed = {
            'host': acceptance.HOST,
            'x_forwarded_proto': 'https',
            'x_forwarded_for': '172.30.0.1',
            'forwarded': None,
            'x_forwarded_host': None,
            'x_forwarded_port': None,
        }
        observed[changed_header] = value
        try:
            _run_sse_with_headers(observed)
        except acceptance.AcceptanceError:
            continue
        raise AssertionError(f'accepted a forged upstream {changed_header} header')
