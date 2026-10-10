import asyncio
import importlib.util
import json
import os
import stat
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


def test_g2_args_require_private_owned_bundle_and_all_runtime_inputs(tmp_path):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    bundle_path = private_root / 'fixtures.json'
    acceptance._fixtures.create_bundle(bundle_path)
    state_path = private_root / 'state.json'
    state_path.write_text('{"ok":true,"news_id":1}\n', encoding='utf-8')
    compose_file = private_root / 'compose.yaml'
    compose_file.write_text('services: {}\n', encoding='utf-8')
    compose_env = private_root / 'compose.env'
    compose_env.write_text('SYNTHETIC=1\n', encoding='utf-8')
    for path in (state_path, compose_file, compose_env):
        path.chmod(0o600)
    ca_cert = private_root / 'ca.crt'
    ca_cert.write_text('test CA\n', encoding='utf-8')

    args = acceptance._parse_args([
        '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
        '--work-dir', str(private_root), '--stage', 'g2',
        '--fixture-bundle', str(bundle_path), '--fixture-state', str(state_path),
        '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
        '--compose-file', str(compose_file), '--compose-env', str(compose_env),
        '--gateway-container-id', '0123456789ab', '--curl-image', 'curlimages/curl:8.10.1',
        '--private-root', str(private_root),
    ])
    assert args.stage == 'g2'
    assert args.private_root == private_root.resolve()

    with pytest.raises(SystemExit):
        acceptance._parse_args([
            '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
            '--work-dir', str(private_root), '--stage', 'g2',
        ])

    state_path.chmod(0o644)
    with pytest.raises(SystemExit):
        acceptance._parse_args([
            '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
            '--work-dir', str(private_root), '--stage', 'g2',
            '--fixture-bundle', str(bundle_path), '--fixture-state', str(state_path),
            '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
            '--compose-file', str(compose_file), '--compose-env', str(compose_env),
            '--gateway-container-id', '0123456789ab', '--curl-image', 'curlimages/curl:8.10.1',
            '--private-root', str(private_root),
        ])


def test_g2_http_api_matrix_requires_full_accounts_and_blocks_private_ai_anonymous(tmp_path):
    bundle_path = tmp_path / 'fixtures.json'
    bundle = acceptance._fixtures.create_bundle(bundle_path)
    calls = []
    checks = {}
    args = SimpleNamespace(
        stage='g2', fixture_bundle=bundle_path, work_dir=tmp_path, news_id=1,
        gateway_ip='127.0.0.1', ca_cert=tmp_path / 'ca.crt',
    )
    args.ca_cert.write_text('synthetic CA\n', encoding='utf-8')

    def fake_expect(_args, result_checks, name, path, expected, **kwargs):
        calls.append((name, path, expected, kwargs))
        result_checks[name] = f'HTTP {expected}'
        body = ''
        headers = {}
        header_file = kwargs.get('header_file')
        if name == 'http_redirect':
            header_file.write_text('HTTP/1.1 301 Moved Permanently\nLocation: https://news.lambert.host/news/1?from=smoke\n\n', encoding='utf-8')
            headers = {'location': ['https://news.lambert.host/news/1?from=smoke']}
        elif name == 'acme_fixture':
            body = 'newshub-local-acme-fixture\n'
        elif name in ('csrf_initialization', 'real_django_secure_request'):
            body = '{"csrfToken":"fixture"}'
            headers = {'set-cookie': ['csrftoken=fixture; Path=/; SameSite=Lax; Secure']}
            if header_file:
                header_file.write_text('Set-Cookie: csrftoken=fixture; Path=/; SameSite=Lax; Secure\n', encoding='utf-8')
        elif name == 'capabilities':
            enabled = ('accounts', 'signup', 'favorites', 'blocked_news', 'chat_history')
            disabled = ('chat', 'research', 'provider_comparisons', 'translation', 'tts')
            body = json.dumps({
                'site_mode': 'full',
                'chatgpt_auth_mode': 'disabled',
                'features': {
                    **{key: {'enabled': True} for key in enabled},
                    **{key: {'enabled': False, 'reason': 'ai_disabled'} for key in disabled},
                },
            })
            headers = {'cache-control': ['no-store']}
        elif name == 'keyword_search':
            body = bundle['news']['title']
        elif name == 'anonymous_ai_chat_disabled':
            body = '{"error_code":"ai_disabled"}'
        elif name == 'legacy_hash_asset':
            body = 'legacy-asset-fixture\n'
            headers = {'cache-control': ['public, max-age=31536000, immutable']}
            header_file.write_text('Cache-Control: public, max-age=31536000, immutable\n', encoding='utf-8')
        elif name == 'index_no_store':
            header_file.write_text('Cache-Control: no-store\n', encoding='utf-8')
        return body, headers

    missing_hash_headers = None

    def fake_curl(_args, path, **kwargs):
        nonlocal missing_hash_headers
        if path.startswith('/assets/not-present-'):
            missing_hash_headers = kwargs.get('header_file')
            return 404, '', subprocess.CompletedProcess(['curl'], 0, f'{acceptance.STATUS_MARKER}404', '')
        if path == '/favicon.svg':
            return 200, '<svg xmlns="http://www.w3.org/2000/svg"></svg>', subprocess.CompletedProcess(['curl'], 0, f'{acceptance.STATUS_MARKER}200', '')
        return 404, '', subprocess.CompletedProcess(['curl'], 0, f'{acceptance.STATUS_MARKER}404', '')

    with (
        patch.object(acceptance, '_expect_status', side_effect=fake_expect),
        patch.object(acceptance, '_curl', side_effect=fake_curl),
        patch.object(acceptance.shutil, 'which', return_value='/usr/bin/curl'),
        patch.object(acceptance.subprocess, 'run', return_value=subprocess.CompletedProcess(
            ['curl'], 52, f'{acceptance.STATUS_MARKER}000', 'closed',
        )),
    ):
        acceptance._check_http_api(args, checks, tmp_path)

    call_map = {name: (path, status, kwargs) for name, path, status, kwargs in calls}
    assert checks['g2_capabilities'].startswith('full site')
    assert checks['g2_ai_post'].startswith('HTTP 403 ai_disabled')
    assert call_map['anonymous_favorites'][:2] == ('/api/favorites/?type=bookmark', 403)
    assert call_map['anonymous_chat_history'][:2] == ('/api/news/1/chat/', 403)
    assert call_map['anonymous_research_history'][:2] == ('/api/research/sessions/', 403)
    assert call_map['anonymous_admin'][:2] == ('/api/admin/crawler/dashboard/', 403)
    assert call_map['anonymous_ai_chat_disabled'][:2] == ('/api/news/1/chat/', 403)
    assert call_map['anonymous_ai_chat_disabled'][2]['method'] == 'POST'
    assert not any(name in call_map for name in ('translation_post', 'admin_get', 'subscription_get'))
    assert missing_hash_headers is not None
    assert 'g2_capabilities' in checks and checks['index_no_store'] == 'HTTP 200'


def test_g2_failure_report_redacts_exception_values_from_stdout_and_json(tmp_path, capsys):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    bundle_path = private_root / 'fixtures.json'
    bundle = acceptance._fixtures.create_bundle(bundle_path)
    state_path = private_root / 'state.json'
    state_path.write_text('{"ok":true,"news_id":1}\n', encoding='utf-8')
    compose_file = private_root / 'compose.yaml'
    compose_file.write_text('services: {}\n', encoding='utf-8')
    compose_env = private_root / 'compose.env'
    compose_env.write_text('SYNTHETIC=1\n', encoding='utf-8')
    ca_cert = private_root / 'ca.crt'
    ca_cert.write_text('test CA\n', encoding='utf-8')
    for path in (state_path, compose_file, compose_env):
        path.chmod(0o600)
    report_path = private_root / 'report.json'
    password = bundle['users']['a']['password']
    invitation = bundle['invitations']['a']['token']
    cookie = 'sessionid=private-cookie-marker'
    argv = [
        '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
        '--work-dir', str(private_root), '--stage', 'g2', '--report', str(report_path),
        '--fixture-bundle', str(bundle_path), '--fixture-state', str(state_path),
        '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
        '--compose-file', str(compose_file), '--compose-env', str(compose_env),
        '--gateway-container-id', '0123456789ab', '--curl-image', 'curlimages/curl:8.10.1',
        '--private-root', str(private_root),
    ]
    leaked_exception = RuntimeError(f'fill timeout value={password} invite={invitation} {cookie}')
    with patch.object(acceptance, '_check_http_api', side_effect=leaked_exception):
        assert acceptance.main(argv) == 1

    stdout = capsys.readouterr().out
    report = report_path.read_text(encoding='utf-8')
    for private_value in (password, invitation, cookie):
        assert private_value not in stdout
        assert private_value not in report
    payload = json.loads(report)
    assert payload['failure'] == {
        'stage': 'g2', 'check': 'g2.http_api', 'exception_type': 'RuntimeError',
    }


def test_g2_failure_page_is_cleared_or_closed_before_a_screenshot():
    selectors = ('#auth-username', '#auth-email', '#auth-password', '#auth-invite-token')

    class FakeLocator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def count(self):
            return int(self.selector == '.auth-modal-backdrop' and self.page.modal) or int(self.selector in self.page.values)

        async def is_visible(self):
            return True

        async def fill(self, value, timeout):
            assert timeout == 1000
            if self.page.fail_clear == self.selector:
                raise RuntimeError(self.page.values[self.selector])
            self.page.values[self.selector] = value

        async def input_value(self):
            return self.page.values[self.selector]

        async def wait_for(self, state, timeout):
            assert state == 'detached' and timeout == 1000
            assert not self.page.modal

    class FakePage:
        def __init__(self, *, fail_clear=None, fail_close=False):
            self.modal = True
            self.fail_clear = fail_clear
            self.fail_close = fail_close
            self.values = {selector: f'synthetic-secret-{index}' for index, selector in enumerate(selectors)}

        def locator(self, selector):
            return FakeLocator(self, selector)

        def get_by_role(self, role, *, name):
            assert role == 'button' and name == '关闭登录窗口'
            page = self

            class CloseButton:
                async def click(self, timeout):
                    assert timeout == 1000
                    if page.fail_close:
                        raise RuntimeError('close failed')
                    page.modal = False

            return CloseButton()

    cleared_page = FakePage()
    assert asyncio.run(acceptance._sanitize_g2_failure_page(cleared_page))
    assert all(cleared_page.values[selector] == '' for selector in selectors)

    closed_page = FakePage(fail_clear='#auth-password')
    assert asyncio.run(acceptance._sanitize_g2_failure_page(closed_page))
    assert not closed_page.modal

    unsafe_page = FakePage(fail_clear='#auth-password', fail_close=True)
    assert not asyncio.run(acceptance._sanitize_g2_failure_page(unsafe_page))


def test_g2_fixture_program_uses_stdin_and_keeps_output_files_private(tmp_path):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    bundle = acceptance._fixtures.create_bundle(private_root / 'bundle.json')
    args = SimpleNamespace(
        compose_project='newshub-local-g2-123-0123456789abcdef',
        compose_file=private_root / 'compose.yaml', compose_env=private_root / 'compose.env',
        private_root=private_root,
    )
    result = subprocess.CompletedProcess(['docker'], 0, '{"ok":true}\n', '')
    with patch.object(acceptance.subprocess, 'run', return_value=result) as run:
        assert acceptance._run_fixture_program(args, bundle, 'seed') == {'ok': True}
    command = run.call_args.args[0]
    program = run.call_args.kwargs['input']
    password = bundle['users']['a']['password']
    assert command[-2:] == ['python', '-']
    assert password in program
    assert password not in command
    assert run.call_args.kwargs['capture_output'] is True
    saved_files = list(private_root.glob('fixture-seed-*.stdout')) + list(private_root.glob('fixture-seed-*.stderr'))
    assert len(saved_files) == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in saved_files)

    marker = 'private-helper-output-marker'
    failed = subprocess.CompletedProcess(['docker'], 2, marker, marker)
    with patch.object(acceptance.subprocess, 'run', return_value=failed):
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance._run_fixture_program(args, bundle, 'audit')
    assert marker not in str(error.value)
    audit_files = list(private_root.glob('fixture-audit-*'))
    assert len(audit_files) == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in audit_files)


def test_g2_rate_sidecar_is_scoped_nonroot_readonly_and_never_ignores_tls(tmp_path):
    private_root = tmp_path / 'private'
    rate_root = private_root / 'rate'
    rate_root.mkdir(mode=0o700, parents=True)
    ca_cert = private_root / 'ca.crt'
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    config = rate_root / 'probe.curlrc'
    config.write_text('synthetic request\n', encoding='utf-8')
    args = SimpleNamespace(
        private_root=private_root, compose_project='newshub-local-g2-123-0123456789abcdef',
        gateway_container_id='0123456789ab', curl_image='curlimages/curl:8.10.1', ca_cert=ca_cert,
    )
    results = [
        subprocess.CompletedProcess(['docker', 'inspect'], 1, '', ''),
        subprocess.CompletedProcess(['docker', 'run'], 0, 'csrf=200\nsixth=429\n', ''),
    ]
    config.chmod(0o600)
    with patch.object(acceptance.subprocess, 'run', side_effect=results) as run:
        assert acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config), ('sixth', config)]) == {
            'csrf': 200, 'sixth': 429,
        }
    command = run.call_args_list[1].args[0]
    assert '--pull=never' in command
    assert command[command.index('--network') + 1] == 'container:0123456789ab'
    assert command[command.index('--user') + 1] == f'{os.getuid()}:{os.getgid()}'
    assert '--read-only' in command
    assert '--privileged' not in command and '-p' not in command and '--publish' not in command
    assert '-k' not in command and '--insecure' not in command
    assert any(value.endswith('/smoke/ca.crt,readonly') for value in command if value.startswith('type=bind'))
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in rate_root.iterdir() if path.is_file())


def test_g2_rate_matrix_uses_real_loopback_buckets_and_xff_only_as_negative(tmp_path):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    rate_root = private_root / 'rate'
    ca_cert = private_root / 'ca.crt'
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    bundle = acceptance._fixtures.create_bundle(private_root / 'bundle.json')
    args = SimpleNamespace(private_root=private_root, ca_cert=ca_cert)
    checks = {}
    sidecar_calls = []
    phases = {'login-rate-count': iter((0, 0, 5))}

    def fake_fixture(_args, _bundle, phase):
        if phase == 'login-rate-count':
            return {'ok': True, 'count': next(phases[phase])}
        if phase == 'registration-rate-counts':
            return {'ok': True, 'per_ip_counts': [5] * 5, 'global_count': 27}
        assert phase == 'audit'
        return {'ok': True}

    def fake_sidecar(_args, interface, requests):
        sidecar_calls.append((interface, requests))
        statuses = {}
        for marker, config in requests:
            if marker == 'csrf':
                statuses[marker] = 200
                body_path = rate_root / f'{config.stem}.body'
                body_path.write_text(
                    json.dumps({'csrfToken': 'c' * 40}), encoding='utf-8',
                )
                body_path.chmod(0o600)
            elif marker in {'bad_csrf', 'hostile_origin'}:
                statuses[marker] = 403
            elif marker.startswith('login_') and marker != 'login_6':
                statuses[marker] = 401
            elif marker == 'login_6' or marker == 'sixth':
                statuses[marker] = 429
                headers_path = rate_root / f'{config.stem}.headers'
                headers_path.write_text('HTTP/1.1 429 Too Many Requests\nRetry-After: 60\n\n', encoding='utf-8')
                headers_path.chmod(0o600)
            elif marker == 'special':
                statuses[marker] = 400 if config.stem == 'register-2-special' else 403
            elif marker.startswith('missing_'):
                statuses[marker] = 403
            else:
                raise AssertionError(f'unexpected synthetic request marker {marker}')
        return statuses

    with (
        patch.object(acceptance, '_run_fixture_program', side_effect=fake_fixture),
        patch.object(acceptance, '_run_rate_sidecar', side_effect=fake_sidecar),
    ):
        acceptance._run_g2_rate_limit_checks(args, checks, bundle)

    assert len(sidecar_calls) == 13
    assert [ip for ip, _requests in sidecar_calls[:3]] == ['127.0.0.70'] * 3
    assert [sidecar_calls[index][0] for index in range(3, 13)] == [
        '127.0.0.61', '127.0.0.61', '127.0.0.62', '127.0.0.62',
        '127.0.0.63', '127.0.0.63', '127.0.0.64', '127.0.0.64',
        '127.0.0.65', '127.0.0.65',
    ]
    login_requests = sidecar_calls[2][1]
    login_configs = {marker: path.read_text(encoding='utf-8') for marker, path in login_requests}
    assert all('interface = "127.0.0.70"' in content for content in login_configs.values())
    assert 'X-Forwarded-For:' not in '\n'.join(login_configs[f'login_{attempt}'] for attempt in range(1, 6))
    assert 'X-Forwarded-For: 198.51.100.44' in login_configs['login_6']
    for index, octet in enumerate(range(61, 66)):
        csrf_requests = sidecar_calls[3 + index * 2][1]
        registration_requests = sidecar_calls[4 + index * 2][1]
        assert all(f'interface = "127.0.0.{octet}"' in path.read_text(encoding='utf-8') for _marker, path in csrf_requests + registration_requests)
        sixth = dict(registration_requests)['sixth'].read_text(encoding='utf-8')
        assert 'X-Forwarded-For: 198.51.100.44' in sixth
        assert len(registration_requests) == 6
    assert checks['g2_login_rate_limit'].startswith('127.0.0.70:')
    assert checks['g2_registration_rate_sources'].startswith('five true loopback source IPs')
    assert checks['g2_registration_global_bucket'] == '27/100 within the fixed limit'
    report_text = json.dumps(checks)
    assert all(bundle['users'][role]['password'] not in report_text for role in bundle['users'])
    assert all(invitation['token'] not in report_text for invitation in bundle['invitations'].values())
