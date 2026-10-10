import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT / 'scripts' / 'deploy' / 'local_domain_acceptance.py'
SPEC = importlib.util.spec_from_file_location('local_domain_acceptance', MODULE_PATH)
acceptance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(acceptance)


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
