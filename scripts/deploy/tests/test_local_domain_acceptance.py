import asyncio
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import textwrap
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
APP_IMAGE_ID = 'sha256:' + 'a' * 64
GATEWAY_IMAGE_ID = 'sha256:' + 'b' * 64
CURL_IMAGE_ID = 'sha256:' + 'c' * 64
GATEWAY_CONTAINER_ID = 'd' * 64
APP_CONTAINER_ID = 'e' * 64
NETWORK_ID = 'f' * 64


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
        '--gateway-container-id', GATEWAY_CONTAINER_ID,
        '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
        '--curl-image-id', CURL_IMAGE_ID,
        '--private-root', str(private_root),
    ])
    assert args.stage == 'g2'
    assert args.private_root == private_root.resolve()
    assert args.app_image_id == APP_IMAGE_ID
    assert args.gateway_image_id == GATEWAY_IMAGE_ID
    assert args.curl_image_id == CURL_IMAGE_ID

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
            '--gateway-container-id', GATEWAY_CONTAINER_ID,
            '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
            '--curl-image-id', CURL_IMAGE_ID,
            '--private-root', str(private_root),
        ])


def test_g2_sse_only_parser_needs_no_account_or_compose_inputs(tmp_path):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    ca_cert = private_root / 'ca.crt'
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')

    args = acceptance._parse_args([
        '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
        '--work-dir', str(private_root), '--stage', 'g2', '--sse-only',
    ])

    assert args.stage == 'g2' and args.sse_only
    with pytest.raises(SystemExit):
        acceptance._parse_args([
            '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
            '--work-dir', str(private_root), '--stage', 'g2',
        ])


def test_browser_api_executes_without_get_head_bodies_and_keeps_post_csrf():
    node = shutil.which('node')
    assert node is not None
    driver = textwrap.dedent(f'''\
        const source = {json.dumps(acceptance._BROWSER_API_SCRIPT)};
        const api = (0, eval)('(' + source + ')');
        const calls = [];
        globalThis.document = {{cookie: 'csrftoken=token%2Bvalue'}};
        globalThis.fetch = async (path, options) => {{
          calls.push({{path, options}});
          return {{status: 200, text: async () => '{{"ok":true}}'}};
        }};
        (async () => {{
          for (const method of ['GET', 'HEAD', 'OPTIONS']) {{
            for (const body of [null, undefined, {{ignored: true}}]) {{
              await api({{method, path: '/api/read/', body}});
            }}
          }}
          await api({{method: 'POST', path: '/api/write/', body: {{value: 1}}}});
          for (const {{options}} of calls.slice(0, 9)) {{
            if (Object.hasOwn(options, 'body')) throw new Error('safe method sent a body');
            if (Object.hasOwn(options.headers, 'Content-Type')) throw new Error('safe method sent JSON Content-Type');
          }}
          const post = calls[9].options;
          if (post.body !== '{{"value":1}}') throw new Error('POST JSON body changed');
          if (post.headers['Content-Type'] !== 'application/json') throw new Error('POST content type missing');
          if (post.headers['X-CSRFToken'] !== 'token+value') throw new Error('POST CSRF header missing');
        }})().catch((error) => {{ console.error(error.message); process.exitCode = 1; }});
    ''')
    result = subprocess.run([node, '-e', driver], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


class _FakeLogoutResponse:
    def __init__(self, page, status=200, *, leave_session=False):
        self.page = page
        self.url = f'https://{acceptance.HOST}/api/auth/logout/'
        self.request = SimpleNamespace(method='POST')
        self.status = status
        self.leave_session = leave_session
        self.complete = False

    async def finished(self):
        self.page.events.append('response.finished.wait')
        await asyncio.sleep(0)
        self.complete = True
        if self.status == 200 and not self.leave_session:
            self.page.context.session_present = False
        self.page.events.append('response.finished.done')
        return None


class _FakeResponseExpectation:
    def __init__(self, page, predicate):
        self.page = page
        self.predicate = predicate
        self.future = asyncio.get_running_loop().create_future()

    async def __aenter__(self):
        self.page.events.append('response.expect.enter')
        self.page.expectation = self
        return self

    async def __aexit__(self, *_args):
        self.page.events.append('response.expect.exit')

    @property
    def value(self):
        return self.future


class _FakeLogoutLocator:
    def __init__(self, page, role, name):
        self.page = page
        self.role = role
        self.name = name

    async def click(self):
        if self.name == '打开菜单':
            self.page.events.append('menu.click')
            return
        assert self.name == '退出登录'
        self.page.events.append('logout.click')
        self.page.avatar_visible = False
        self.page.events.append('avatar.detach.triggered')
        expectation = self.page.expectation
        response = _FakeLogoutResponse(
            self.page,
            self.page.response_status,
            leave_session=self.page.leave_session,
        )
        self.page.response = response
        if expectation is None:
            return
        if self.page.response_error is not None:
            expectation.future.set_exception(self.page.response_error)
            return
        assert expectation.predicate(response)
        expectation.future.set_result(response)

    async def wait_for(self, *, state, timeout):
        assert state == 'detached' and timeout == 15000
        assert not self.page.avatar_visible
        self.page.events.append('avatar.detached')


class _FakeLogoutPage:
    def __init__(self, *, status=200, leave_session=False, response_error=None, me_status=403):
        self.events = []
        self.context = _FakeLogoutContext(self.events)
        self.response_status = status
        self.leave_session = leave_session
        self.response_error = response_error
        self.me_status = me_status
        self.avatar_visible = True
        self.expectation = None
        self.response = None

    def expect_response(self, predicate, *, timeout):
        assert timeout == 15000
        return _FakeResponseExpectation(self, predicate)

    def get_by_role(self, role, *, name, exact=False):
        if role == 'img':
            assert name == 'synthetic-user，已登录'
            return _FakeLogoutLocator(self, role, name)
        assert role == 'button'
        if name == '退出登录':
            assert exact is True
        return _FakeLogoutLocator(self, role, name)


class _FakeLogoutContext:
    def __init__(self, events):
        self.events = events
        self.session_present = True

    async def cookies(self, origin):
        assert origin == f'https://{acceptance.HOST}'
        self.events.append('cookies.read')
        if self.session_present:
            return [{'name': 'sessionid', 'value': 'synthetic-session'}]
        return []


async def _fake_logout_api(page, method, path):
    assert (method, path) == ('GET', '/api/auth/me/')
    page.events.append('get_me')
    assert page.response is not None and page.response.complete, 'GET /me ran before logout response.finished()'
    return {'status': page.me_status, 'body': {}}


def test_logout_waits_for_response_finished_before_me_and_cookie_checks():
    page = _FakeLogoutPage()

    with patch.object(acceptance, '_browser_api', side_effect=_fake_logout_api):
        asyncio.run(acceptance._logout_ui(page, 'synthetic-user', page.context))

    assert page.events.index('logout.click') < page.events.index('response.finished.wait')
    assert page.events.index('avatar.detach.triggered') < page.events.index('response.finished.done')
    assert page.events.index('response.finished.done') < page.events.index('get_me')
    assert page.events.index('response.finished.done') < page.events.index('avatar.detached')
    assert page.events.index('get_me') < page.events.index('cookies.read')
    assert page.context.session_present is False


@pytest.mark.parametrize('status', [403, 500])
def test_logout_non_200_fails_before_get_me_and_preserves_numeric_status(status):
    page = _FakeLogoutPage(status=status)

    with patch.object(acceptance, '_browser_api', side_effect=_fake_logout_api):
        with pytest.raises(acceptance.G2BrowserAcceptanceError) as raised:
            asyncio.run(acceptance._logout_ui(
                page, 'synthetic-user', page.context,
                checks={}, subcheck='g2.logout_a',
            ))

    exc = raised.value
    assert exc.source_check_name == 'g2.logout_http'
    assert exc.expected_http_status == 200 and exc.actual_http_status == status
    assert exc.active_subcheck == 'g2.logout_a'
    assert exc.browser_exception_type == 'AcceptanceError'
    assert 'get_me' not in page.events
    assert page.context.session_present is True
    assert acceptance._safe_http_failure_details(exc) == {
        'source_check_name': 'g2.logout_http',
        'expected_http_status': 200,
        'actual_http_status': status,
    }


def test_logout_get_me_must_be_anonymous_and_reports_http_status():
    page = _FakeLogoutPage(me_status=200)

    with patch.object(acceptance, '_browser_api', side_effect=_fake_logout_api):
        with pytest.raises(acceptance.G2BrowserAcceptanceError) as raised:
            asyncio.run(acceptance._logout_ui(
                page, 'synthetic-user', page.context,
                checks={}, subcheck='g2.logout_a',
            ))

    exc = raised.value
    assert exc.source_check_name == 'g2.logout_me'
    assert exc.expected_http_status == 403 and exc.actual_http_status == 200
    assert page.events.index('response.finished.done') < page.events.index('get_me')
    assert 'cookies.read' not in page.events


def test_logout_response_timeout_reports_safe_no_response_status():
    secret_values = ('synthetic-password', 'synthetic-invite', 'synthetic-user@example.invalid')
    page = _FakeLogoutPage(response_error=TimeoutError('timed out ' + ' '.join(secret_values)))

    with patch.object(acceptance, '_browser_api', side_effect=_fake_logout_api):
        with pytest.raises(acceptance.G2BrowserAcceptanceError) as raised:
            asyncio.run(acceptance._logout_ui(
                page, 'synthetic-user', page.context,
                checks={}, subcheck='g2.logout_a',
            ))

    exc = raised.value
    assert exc.active_subcheck == 'g2.logout_a'
    assert exc.browser_exception_type == 'TimeoutError'
    assert exc.source_check_name == 'g2.logout_http'
    assert exc.expected_http_status == 200 and exc.actual_http_status == 0
    assert 'get_me' not in page.events and 'cookies.read' not in page.events
    serialized = json.dumps({
        'active_subcheck': exc.active_subcheck,
        'browser_exception_type': exc.browser_exception_type,
        **acceptance._safe_http_failure_details(exc),
    }, sort_keys=True)
    assert all(secret not in serialized for secret in secret_values)


def test_logout_200_still_fails_when_session_cookie_remains():
    page = _FakeLogoutPage(leave_session=True)

    with patch.object(acceptance, '_browser_api', side_effect=_fake_logout_api):
        with pytest.raises(acceptance.G2BrowserAcceptanceError) as raised:
            asyncio.run(acceptance._logout_ui(
                page, 'synthetic-user', page.context,
                checks={}, subcheck='g2.logout_a',
            ))

    exc = raised.value
    assert exc.source_check_name == 'g2.logout_cookie'
    assert exc.expected_http_status is None and exc.actual_http_status is None
    assert page.events.index('response.finished.done') < page.events.index('get_me')
    assert 'cookies.read' in page.events


def test_logout_response_matcher_requires_same_origin_exact_path_and_post():
    good = SimpleNamespace(
        url=f'https://{acceptance.HOST}/api/auth/logout/',
        request=SimpleNamespace(method='POST'),
    )
    assert acceptance._is_expected_logout_response(good)
    for url, method in (
        (f'https://evil.invalid/api/auth/logout/', 'POST'),
        (f'http://{acceptance.HOST}/api/auth/logout/', 'POST'),
        (f'https://{acceptance.HOST}/api/auth/logout', 'POST'),
        (f'https://{acceptance.HOST}/api/auth/login/', 'POST'),
        (f'https://{acceptance.HOST}/api/auth/logout/', 'GET'),
        (f'https://{acceptance.HOST}:444/api/auth/logout/', 'POST'),
    ):
        response = SimpleNamespace(url=url, request=SimpleNamespace(method=method))
        assert not acceptance._is_expected_logout_response(response)


def test_g2_browser_subchecks_are_fixed_and_cover_the_account_flow():
    required = {
        'g2.account_initial', 'g2.register_a', 'g2.logout_a', 'g2.register_b',
        'g2.attach_owner', 'g2.owner_b', 'g2.admin_gate', 'g2.logout_b',
        'g2.owner_a', 'g2.auth_races', 'g2.owner_csrf', 'g2.admin',
        'g2.final_audit', 'g2.anon_after_logout', 'g2.cookie_attributes',
    }
    assert required <= acceptance.G2_BROWSER_SUBCHECKS
    checks = {}
    acceptance._mark_g2_browser_subcheck(checks, 'g2.logout_a')
    assert checks == {'_g2_active_subcheck': 'g2.logout_a'}
    with pytest.raises(ValueError):
        acceptance._mark_g2_browser_subcheck(checks, 'g2.secret-value')


def test_g2_browser_failure_metadata_is_fixed_and_redacts_timeout_values(tmp_path, capsys):
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
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    for path in (state_path, compose_file, compose_env):
        path.chmod(0o600)
    report_path = private_root / 'report.json'
    password = bundle['users']['a']['password']
    invite = bundle['invitations']['a']['token']
    email = bundle['users']['a']['email']
    secret = f'{password} {invite} {email} sessionid=synthetic-cookie'
    argv = [
        '--gateway-ip', '127.0.0.1', '--ca-cert', str(ca_cert),
        '--work-dir', str(private_root), '--stage', 'g2', '--report', str(report_path),
        '--fixture-bundle', str(bundle_path), '--fixture-state', str(state_path),
        '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
        '--compose-file', str(compose_file), '--compose-env', str(compose_env),
        '--gateway-container-id', GATEWAY_CONTAINER_ID,
        '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
        '--curl-image-id', CURL_IMAGE_ID, '--private-root', str(private_root),
    ]

    async def failing_browser(_args, checks, _work_dir):
        checks['_g2_active_subcheck'] = 'g2.logout_a'
        raise acceptance._g2_browser_failure(
            TimeoutError(f'fill timeout {secret}'),
            'g2.logout_a',
            source_check_name='g2.logout_http',
            expected_http_status=200,
            actual_http_status=0,
        )

    with (
        patch.object(acceptance, '_check_http_api', side_effect=lambda *_args: None),
        patch.object(acceptance, '_run_browser_checks', side_effect=lambda *_args: None),
        patch.object(acceptance, '_run_g2_browser_checks', side_effect=failing_browser),
    ):
        assert acceptance.main(argv) == 1

    output = capsys.readouterr().out
    report = report_path.read_text(encoding='utf-8')
    assert all(value not in output and value not in report for value in (password, invite, email, 'synthetic-cookie'))
    failure = json.loads(report)['failure']
    assert failure == {
        'stage': 'g2', 'check': 'g2.logout_http', 'exception_type': 'AcceptanceError',
        'active_subcheck': 'g2.logout_a', 'browser_exception_type': 'TimeoutError',
        'source_check_name': 'g2.logout_http',
        'expected_http_status': 200,
        'actual_http_status': 0,
    }


def test_main_awaits_g2_browser_checks_before_rate_checks_and_sanitizes_async_failure(tmp_path, capsys):
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
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    for path in (state_path, compose_file, compose_env):
        path.chmod(0o600)
    report = private_root / 'report.json'
    argv = [
        '--gateway-ip', '127.0.0.1', '--ca-cert', str(ca_cert),
        '--work-dir', str(private_root), '--stage', 'g2', '--report', str(report),
        '--fixture-bundle', str(bundle_path), '--fixture-state', str(state_path),
        '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
        '--compose-file', str(compose_file), '--compose-env', str(compose_env),
        '--gateway-container-id', GATEWAY_CONTAINER_ID,
        '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
        '--curl-image-id', CURL_IMAGE_ID, '--private-root', str(private_root),
    ]
    events = []

    async def browser_accounts(*_args):
        events.append('g2-browser-start')
        await asyncio.sleep(0)
        events.append('g2-browser-finished')

    with (
        patch.object(acceptance, '_check_http_api', side_effect=lambda *_args: events.append('http')),
        patch.object(acceptance, '_run_browser_checks', side_effect=lambda *_args: events.append('shared-browser')),
        patch.object(acceptance, '_run_g2_browser_checks', side_effect=browser_accounts),
        patch.object(acceptance, '_run_g2_rate_limit_checks', side_effect=lambda *_args: events.append('rate')),
    ):
        assert acceptance.main(argv) == 0
    capsys.readouterr()
    assert events == ['http', 'shared-browser', 'g2-browser-start', 'g2-browser-finished', 'rate']

    events.clear()
    private_values = (bundle['users']['a']['password'], bundle['invitations']['a']['token'])

    async def failing_browser(*_args):
        events.append('g2-browser-start')
        await asyncio.sleep(0)
        raise RuntimeError(f'fill failure {private_values[0]} {private_values[1]}')

    with (
        patch.object(acceptance, '_check_http_api', side_effect=lambda *_args: events.append('http')),
        patch.object(acceptance, '_run_browser_checks', side_effect=lambda *_args: events.append('shared-browser')),
        patch.object(acceptance, '_run_g2_browser_checks', side_effect=failing_browser),
        patch.object(acceptance, '_run_g2_rate_limit_checks', side_effect=lambda *_args: events.append('rate')),
    ):
        assert acceptance.main(argv) == 1
    failure_output = capsys.readouterr().out
    failure_report = report.read_text(encoding='utf-8')
    assert events == ['http', 'shared-browser', 'g2-browser-start']
    assert all(value not in failure_output and value not in failure_report for value in private_values)
    assert json.loads(failure_report)['failure'] == {
        'stage': 'g2', 'check': 'g2.account_browser', 'exception_type': 'RuntimeError',
    }

    with (
        patch.object(acceptance, '_check_http_api', side_effect=lambda *_args: None),
        patch.object(acceptance, '_run_browser_checks', side_effect=lambda *_args: None),
        patch.object(acceptance, '_run_g2_browser_checks', side_effect=browser_accounts),
        patch.object(
            acceptance, '_run_g2_rate_limit_checks',
            side_effect=acceptance.CleanupAcceptanceError('synthetic cleanup failure'),
        ),
    ):
        assert acceptance.main(argv) == 1
    cleanup_report = json.loads(report.read_text(encoding='utf-8'))
    assert cleanup_report['status'] == 'FAIL'
    assert cleanup_report['cleanup_status'] == 'FAIL'


def _valid_parent_inspects(project='newshub-local-g2-123-0123456789abcdef'):
    gateway = {
        'Id': GATEWAY_CONTAINER_ID,
        'Config': {'Labels': {
            'com.docker.compose.project': project,
            'com.docker.compose.service': 'gateway',
        }},
        'State': {'Running': True},
        'Image': GATEWAY_IMAGE_ID,
        'HostConfig': {'NetworkMode': f'{project}_isolated'},
        'NetworkSettings': {
            'Ports': {'80/tcp': None, '443/tcp': None},
            'Networks': {f'{project}_isolated': {
                'NetworkID': NETWORK_ID, 'IPAddress': '172.28.0.2',
            }},
        },
    }
    app = {
        'Id': APP_CONTAINER_ID,
        'Config': {'Labels': {
            'com.docker.compose.project': project,
            'com.docker.compose.service': 'app',
        }, 'User': '10001:10001'},
        'State': {'Running': True},
        'Image': APP_IMAGE_ID,
        'HostConfig': {'NetworkMode': f'container:{GATEWAY_CONTAINER_ID}'},
        'Mounts': [{
            'Type': 'volume', 'Name': f'{project}_db-data',
            'Destination': '/var/lib/newshub/db', 'RW': True,
        }],
    }
    network = {
        'Id': NETWORK_ID,
        'Name': f'{project}_isolated',
        'Internal': True,
        'Labels': {
            'com.docker.compose.project': project,
            'com.docker.compose.network': 'isolated',
        },
    }
    volume = {
        'Name': f'{project}_db-data',
        'Driver': 'local',
        'Scope': 'local',
        'Options': None,
        'Labels': {
            'com.docker.compose.project': project,
            'com.docker.compose.volume': 'db-data',
        },
    }
    return gateway, app, network, volume


def _g2_inspect_args(tmp_path):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    compose_file = private_root / 'compose.yaml'
    compose_file.write_text('services: {}\n', encoding='utf-8')
    compose_env = private_root / 'compose.env'
    compose_env.write_text('SYNTHETIC=1\n', encoding='utf-8')
    compose_file.chmod(0o600)
    compose_env.chmod(0o600)
    return SimpleNamespace(
        compose_project='newshub-local-g2-123-0123456789abcdef',
        compose_file=compose_file, compose_env=compose_env,
        gateway_container_id=GATEWAY_CONTAINER_ID,
        app_image_id=APP_IMAGE_ID, gateway_image_id=GATEWAY_IMAGE_ID,
        curl_image_id=CURL_IMAGE_ID, private_root=private_root,
    )


def _mock_parent_docker_run(commands, objects):
    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[:2] == ['docker', 'compose']:
            service = command[-1]
            container_id = GATEWAY_CONTAINER_ID if service == 'gateway' else APP_CONTAINER_ID
            return subprocess.CompletedProcess(command, 0, container_id + '\n', '')
        if command[:3] == ['docker', 'inspect', '--type']:
            payload = objects['gateway'] if command[-1] == GATEWAY_CONTAINER_ID else objects['app']
        elif command[:3] == ['docker', 'network', 'inspect']:
            payload = objects['network']
        elif command[:3] == ['docker', 'volume', 'inspect']:
            payload = objects['volume']
        else:
            raise AssertionError(f'unexpected Docker command: {command}')
        return subprocess.CompletedProcess(command, 0, json.dumps([payload]), '')
    return run


def test_g2_parent_inspection_accepts_exact_owned_app_gateway_volume_and_network(tmp_path):
    args = _g2_inspect_args(tmp_path)
    objects = dict(zip(('gateway', 'app', 'network', 'volume'), _valid_parent_inspects(args.compose_project)))
    commands = []
    with patch.object(acceptance.subprocess, 'run', side_effect=_mock_parent_docker_run(commands, objects)):
        parents = acceptance._inspect_g2_parents(args)
    assert parents == {
        'app_container_id': APP_CONTAINER_ID,
        'gateway_container_id': GATEWAY_CONTAINER_ID,
        'gateway_network_id': NETWORK_ID,
        'gateway_ip': '172.28.0.2',
    }
    assert not any(command[:2] == ['docker', 'exec'] for command, _kwargs in commands)


@pytest.mark.parametrize('mutation', [
    'gateway-image', 'gateway-project', 'gateway-service', 'gateway-stopped',
    'gateway-published-port', 'network-not-internal', 'network-label',
    'app-image', 'app-project', 'app-service', 'app-user', 'app-namespace',
    'app-bind-db', 'app-foreign-volume', 'app-overlapping-mounts',
    'app-extra-app-bind', 'app-extra-backend-volume', 'app-extra-python-bind', 'app-extra-volume',
    'db-volume-owner', 'db-volume-label', 'db-volume-driver', 'db-volume-scope', 'db-volume-bind-options',
])
def test_g2_parent_identity_failures_refuse_fixture_exec_and_private_stdin(tmp_path, mutation):
    args = _g2_inspect_args(tmp_path)
    bundle = acceptance._fixtures.create_bundle(args.private_root / 'bundle.json')
    gateway, app, network, volume = _valid_parent_inspects(args.compose_project)
    objects = {'gateway': gateway, 'app': app, 'network': network, 'volume': volume}
    if mutation == 'gateway-image': gateway['Image'] = APP_IMAGE_ID
    elif mutation == 'gateway-project': gateway['Config']['Labels']['com.docker.compose.project'] = 'other'
    elif mutation == 'gateway-service': gateway['Config']['Labels']['com.docker.compose.service'] = 'app'
    elif mutation == 'gateway-stopped': gateway['State']['Running'] = False
    elif mutation == 'gateway-published-port': gateway['NetworkSettings']['Ports']['443/tcp'] = [{'HostIp': '127.0.0.1', 'HostPort': '443'}]
    elif mutation == 'network-not-internal': network['Internal'] = False
    elif mutation == 'network-label': network['Labels']['com.docker.compose.project'] = 'other'
    elif mutation == 'app-image': app['Image'] = GATEWAY_IMAGE_ID
    elif mutation == 'app-project': app['Config']['Labels']['com.docker.compose.project'] = 'other'
    elif mutation == 'app-service': app['Config']['Labels']['com.docker.compose.service'] = 'gateway'
    elif mutation == 'app-user': app['Config']['User'] = '0:0'
    elif mutation == 'app-namespace': app['HostConfig']['NetworkMode'] = 'container:other'
    elif mutation == 'app-bind-db': app['Mounts'][0]['Type'] = 'bind'
    elif mutation == 'app-foreign-volume': app['Mounts'][0]['Name'] = 'user_db'
    elif mutation == 'app-overlapping-mounts': app['Mounts'].append({
        'Type': 'bind', 'Source': '/tmp/synthetic',
        'Destination': '/var/lib/newshub/db/db.sqlite3', 'RW': True,
    })
    elif mutation == 'app-extra-app-bind': app['Mounts'].append({
        'Type': 'bind', 'Source': '/tmp/synthetic', 'Destination': '/app', 'RW': True,
    })
    elif mutation == 'app-extra-backend-volume': app['Mounts'].append({
        'Type': 'volume', 'Name': 'other_backend', 'Destination': '/app/backend', 'RW': True,
    })
    elif mutation == 'app-extra-python-bind': app['Mounts'].append({
        'Type': 'bind', 'Source': '/tmp/python', 'Destination': '/usr/local/lib/python3.12/site-packages', 'RW': True,
    })
    elif mutation == 'app-extra-volume': app['Mounts'].append({
        'Type': 'volume', 'Name': 'other_cache', 'Destination': '/var/cache/newshub', 'RW': True,
    })
    elif mutation == 'db-volume-owner': volume['Labels']['com.docker.compose.project'] = 'other'
    elif mutation == 'db-volume-label': volume['Labels']['com.docker.compose.volume'] = 'other'
    elif mutation == 'db-volume-driver': volume['Driver'] = 'local-persist'
    elif mutation == 'db-volume-scope': volume['Scope'] = 'global'
    elif mutation == 'db-volume-bind-options': volume['Options'] = {'type': 'none', 'o': 'bind', 'device': '/tmp/foreign'}
    commands = []
    with patch.object(acceptance.subprocess, 'run', side_effect=_mock_parent_docker_run(commands, objects)):
        with pytest.raises(acceptance.AcceptanceError):
            acceptance._run_fixture_program(args, bundle, 'seed')
    assert not any(command[:2] == ['docker', 'exec'] for command, _kwargs in commands)
    assert not any('input' in kwargs for _command, kwargs in commands)
    if mutation.startswith('app-extra-'):
        assert not any(command[:3] == ['docker', 'volume', 'inspect'] for command, _kwargs in commands)
    if mutation.startswith('db-volume-'):
        assert any(command[:3] == ['docker', 'volume', 'inspect'] for command, _kwargs in commands)


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


def test_expect_status_failure_reports_only_fixed_http_status_metadata():
    args = SimpleNamespace()
    private_body = 'response-body-private-marker'
    private_header = 'X-Private: invite-token-marker'
    response = subprocess.CompletedProcess(
        ['curl'], 0, f'{acceptance.STATUS_MARKER}403', private_header,
    )
    with patch.object(acceptance, '_curl', return_value=(403, private_body, response)):
        with pytest.raises(acceptance.AcceptanceError) as raised:
            acceptance._expect_status(
                args, {}, 'acme_fixture',
                '/.well-known/acme-challenge/newshub-local-test', 200,
                scheme='http',
            )

    payload = acceptance._g2_failure_report('g2.http_api', raised.value)
    failure_json = json.dumps(payload, sort_keys=True)
    assert payload['failure']['source_check_name'] == 'acme_fixture'
    assert payload['failure']['expected_http_status'] == 200
    assert payload['failure']['actual_http_status'] == 403
    assert private_body not in failure_json
    assert private_header not in failure_json
    assert 'invite-token-marker' not in failure_json


@pytest.mark.parametrize(('check_name', 'expected', 'actual'), [
    ('acme_fixture;token=private-marker', 200, 403),
    ('acme_fixture', '200', 403),
    ('acme_fixture', 200, 600),
    ('acme_fixture', True, 403),
])
def test_g2_failure_report_rejects_untrusted_http_metadata(check_name, expected, actual):
    exc = acceptance.AcceptanceError(
        'synthetic exception with private-body-marker',
        source_check_name=check_name,
        expected_http_status=expected,
        actual_http_status=actual,
    )
    payload = acceptance._g2_failure_report('g2.http_api', exc)
    failure = payload['failure']
    assert failure['check'] == 'g2.http_api'
    assert 'source_check_name' not in failure
    assert 'expected_http_status' not in failure
    assert 'actual_http_status' not in failure
    assert 'private-body-marker' not in json.dumps(payload)


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
        '--gateway-container-id', GATEWAY_CONTAINER_ID,
        '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
        '--curl-image-id', CURL_IMAGE_ID,
        '--private-root', str(private_root),
    ]
    leaked_exception = acceptance.AcceptanceError(
        f'fill timeout value={password} invite={invitation} {cookie}; '
        'body=response-body-private-marker header=header-private-marker',
        source_check_name='acme_fixture',
        expected_http_status=200,
        actual_http_status=403,
    )
    with patch.object(acceptance, '_check_http_api', side_effect=leaked_exception):
        assert acceptance.main(argv) == 1

    stdout = capsys.readouterr().out
    report = report_path.read_text(encoding='utf-8')
    for private_value in (password, invitation, cookie):
        assert private_value not in stdout
        assert private_value not in report
    payload = json.loads(report)
    assert payload['failure'] == {
        'stage': 'g2', 'check': 'g2.http_api', 'exception_type': 'AcceptanceError',
        'source_check_name': 'acme_fixture',
        'expected_http_status': 200,
        'actual_http_status': 403,
    }
    for private_value in (
        'response-body-private-marker', 'header-private-marker',
    ):
        assert private_value not in stdout
        assert private_value not in report


@pytest.mark.parametrize(('child_error_type', 'reported_error_type'), [
    ('ImproperlyConfigured', 'ImproperlyConfigured'),
    ('opaque-child-error-private-marker', 'FixtureExecutionError'),
])
def test_g2_seed_failure_persists_only_safe_child_error_type(
    tmp_path, capsys, child_error_type, reported_error_type,
):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    report_root = tmp_path / 'reports'
    report_root.mkdir(mode=0o700)
    report_root.chmod(0o700)
    bundle_path = private_root / 'fixtures.json'
    bundle = acceptance._fixtures.create_bundle(bundle_path)
    compose_file = private_root / 'compose.yaml'
    compose_file.write_text('services: {}\n', encoding='utf-8')
    compose_env = private_root / 'compose.env'
    compose_env.write_text('SYNTHETIC=1\n', encoding='utf-8')
    ca_cert = report_root / 'ca.crt'
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    for path in (compose_file, compose_env, ca_cert):
        path.chmod(0o600)
    report_path = report_root / 'seed.json'
    state_path = private_root / 'state.json'
    secret = bundle['invitations']['a']['token']
    argv = [
        '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
        '--work-dir', str(report_root), '--stage', 'g2', '--report', str(report_path),
        '--fixture-phase', 'seed', '--fixture-bundle', str(bundle_path),
        '--fixture-state', str(state_path),
        '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
        '--compose-file', str(compose_file), '--compose-env', str(compose_env),
        '--gateway-container-id', GATEWAY_CONTAINER_ID,
        '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
        '--private-root', str(private_root),
    ]
    child_failure = json.dumps({'ok': False, 'error_type': child_error_type}) + '\n'
    child_result = subprocess.CompletedProcess(
        ['docker', 'exec'], 1, child_failure, f'private traceback token={secret}',
    )
    with (
        patch.object(acceptance, '_inspect_g2_parents', return_value={
            'app_container_id': APP_CONTAINER_ID,
            'gateway_container_id': GATEWAY_CONTAINER_ID,
            'gateway_network_id': NETWORK_ID,
            'gateway_ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', return_value=child_result),
    ):
        assert acceptance.main(argv) == 1

    stdout = capsys.readouterr().out
    report = report_path.read_text(encoding='utf-8')
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert secret not in stdout and secret not in report
    if child_error_type != reported_error_type:
        assert child_error_type not in stdout and child_error_type not in report
    payload = json.loads(report)
    assert payload['status'] == 'FAIL'
    assert payload['failure'] == {
        'stage': 'g2', 'check': 'g2.fixture_seed',
        'exception_type': reported_error_type,
        'child_exception_type': reported_error_type,
    }
    private_stderr = list(private_root.glob('fixture-seed-*.stderr'))
    assert len(private_stderr) == 1
    assert stat.S_IMODE(private_stderr[0].stat().st_mode) == 0o600
    assert secret in private_stderr[0].read_text(encoding='utf-8')


def test_g2_parent_identity_failure_report_is_safe_and_persistent(tmp_path, capsys):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    report_root = tmp_path / 'reports'
    report_root.mkdir(mode=0o700)
    report_root.chmod(0o700)
    compose_file = private_root / 'compose.yaml'
    compose_file.write_text('services: {}\n', encoding='utf-8')
    compose_env = private_root / 'compose.env'
    compose_env.write_text('SYNTHETIC=1\n', encoding='utf-8')
    ca_cert = report_root / 'ca.crt'
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    for path in (compose_file, compose_env, ca_cert):
        path.chmod(0o600)
    report_path = report_root / 'setup.json'
    secret = 'private-parent-identity-marker'
    argv = [
        '--gateway-ip', '172.28.0.2', '--ca-cert', str(ca_cert),
        '--work-dir', str(report_root), '--stage', 'g2', '--report', str(report_path),
        '--compose-project', 'newshub-local-g2-123-0123456789abcdef',
        '--compose-file', str(compose_file), '--compose-env', str(compose_env),
        '--app-image-id', APP_IMAGE_ID, '--gateway-image-id', GATEWAY_IMAGE_ID,
        '--private-root', str(private_root), '--check-parents',
    ]
    with patch.object(
        acceptance, '_inspect_g2_parents',
        side_effect=acceptance.AcceptanceError(f'private inspect detail {secret}'),
    ):
        assert acceptance.main(argv) == 1

    stdout = capsys.readouterr().out
    report = report_path.read_text(encoding='utf-8')
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert secret not in stdout and secret not in report
    payload = json.loads(report)
    assert payload['failure'] == {
        'stage': 'g2', 'check': 'g2.parent_identity',
        'exception_type': 'AcceptanceError',
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
        private_root=private_root, app_image_id=APP_IMAGE_ID,
        gateway_image_id=GATEWAY_IMAGE_ID, gateway_container_id=GATEWAY_CONTAINER_ID,
    )
    result = subprocess.CompletedProcess(['docker'], 0, '{"ok":true}\n', '')
    parents = {
        'app_container_id': APP_CONTAINER_ID,
        'gateway_container_id': GATEWAY_CONTAINER_ID,
        'gateway_network_id': NETWORK_ID,
        'gateway_ip': '172.28.0.2',
    }
    with (
        patch.object(acceptance, '_inspect_g2_parents', return_value=parents),
        patch.object(acceptance.subprocess, 'run', return_value=result) as run,
    ):
        assert acceptance._run_fixture_program(args, bundle, 'seed') == {'ok': True}
    command = run.call_args.args[0]
    program = run.call_args.kwargs['input']
    password = bundle['users']['a']['password']
    assert command == ['docker', 'exec', '-i', APP_CONTAINER_ID, 'python', '-']
    assert password in program
    assert password not in command
    assert run.call_args.kwargs['capture_output'] is True
    saved_files = list(private_root.glob('fixture-seed-*.stdout')) + list(private_root.glob('fixture-seed-*.stderr'))
    assert len(saved_files) == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in saved_files)

    marker = 'private-helper-output-marker'
    failed = subprocess.CompletedProcess(['docker'], 2, marker, marker)
    with (
        patch.object(acceptance, '_inspect_g2_parents', return_value=parents),
        patch.object(acceptance.subprocess, 'run', return_value=failed),
    ):
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance._run_fixture_program(args, bundle, 'audit')
    assert marker not in str(error.value)
    audit_files = list(private_root.glob('fixture-audit-*'))
    assert len(audit_files) == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in audit_files)


def _rate_sidecar_setup(tmp_path):
    private_root = tmp_path / 'private'
    private_root.mkdir(mode=0o700)
    rate_root = private_root / 'rate'
    rate_root.mkdir(mode=0o700)
    output_root = rate_root / 'output'
    output_root.mkdir(mode=0o700)
    ca_cert = private_root / 'ca.crt'
    ca_cert.write_text('synthetic CA\n', encoding='utf-8')
    ca_cert.chmod(0o600)
    config = rate_root / 'probe.curlrc'
    config.write_text('synthetic request\n', encoding='utf-8')
    config.chmod(0o600)
    args = SimpleNamespace(
        private_root=private_root, compose_project='newshub-local-g2-123-0123456789abcdef',
        gateway_container_id=GATEWAY_CONTAINER_ID, curl_image_id=CURL_IMAGE_ID,
        app_image_id=APP_IMAGE_ID, gateway_image_id=GATEWAY_IMAGE_ID, ca_cert=ca_cert,
    )
    return args, private_root, rate_root, output_root, ca_cert, config


def _sidecar_inspect(args, container_id, *, owner=None, image=None, user=None, network=None, running=False):
    return {
        'Id': container_id,
        'Config': {'Labels': {
            'org.newshub.local-domain.owner': owner or args.compose_project,
        }, 'User': user or f'{os.getuid()}:{os.getgid()}'},
        'Image': image or CURL_IMAGE_ID,
        'HostConfig': {'NetworkMode': network or f'container:{GATEWAY_CONTAINER_ID}'},
        'State': {'Running': running},
    }


def _mock_sidecar_lifecycle(
    args, rate_root, *, start_result=None, identity=None, rm_code=0,
    ledger_after_start=None, create_timeout=False, write_cid=True,
):
    container_id = '9' * 64
    obj = identity or _sidecar_inspect(args, container_id)
    calls = []
    cidfile_path = None

    def run(command, **kwargs):
        nonlocal cidfile_path
        calls.append((command, kwargs))
        if command[:3] == ['docker', 'inspect', '--type'] and command[-1].startswith('nhsmoke-rate-'):
            return subprocess.CompletedProcess(command, 1, '', '')
        if command[:2] == ['docker', 'create']:
            cidfile_path = Path(command[command.index('--cidfile') + 1])
            if write_cid:
                cidfile_path.write_text(container_id + '\n', encoding='ascii')
                cidfile_path.chmod(0o600)
            if create_timeout:
                raise subprocess.TimeoutExpired(command, 30)
            return subprocess.CompletedProcess(command, 0, container_id + '\n', '')
        if command[:3] == ['docker', 'inspect', '--type']:
            return subprocess.CompletedProcess(command, 0, json.dumps([obj]), '')
        if command[:3] == ['docker', 'start', '--attach']:
            if ledger_after_start == 'lost':
                assert cidfile_path is not None
                cidfile_path.unlink()
            elif ledger_after_start == 'replaced':
                assert cidfile_path is not None
                cidfile_path.write_text('8' * 64 + '\n', encoding='ascii')
                cidfile_path.chmod(0o600)
            if isinstance(start_result, BaseException):
                raise start_result
            return start_result or subprocess.CompletedProcess(command, 0, 'csrf=200\nsixth=429\n', '')
        if command[:2] == ['docker', 'rm']:
            return subprocess.CompletedProcess(command, rm_code, '', '')
        raise AssertionError(f'unexpected sidecar Docker command: {command}')

    return calls, run, container_id


def test_g2_rate_sidecar_uses_cid_create_inspect_start_and_exact_cleanup(tmp_path):
    args, _private_root, rate_root, output_root, ca_cert, config = _rate_sidecar_setup(tmp_path)
    calls, run, container_id = _mock_sidecar_lifecycle(args, rate_root)
    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        statuses = acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config), ('sixth', config)])

    assert statuses == {'csrf': 200, 'sixth': 429}
    commands = [command for command, _kwargs in calls]
    assert [command[1] for command in commands] == ['inspect', 'create', 'inspect', 'start', 'inspect', 'rm']
    create = commands[1]
    assert '--pull=never' in create
    assert create[create.index('--network') + 1] == f'container:{GATEWAY_CONTAINER_ID}'
    assert create[create.index('--user') + 1] == f'{os.getuid()}:{os.getgid()}'
    assert create[-2] == CURL_IMAGE_ID
    assert '--read-only' in create
    assert '--privileged' not in create and '-p' not in create and '--publish' not in create
    assert '-k' not in create and '--insecure' not in create
    mounts = [value for value in create if value.startswith('type=bind')]
    assert any(value.endswith('/smoke/ca.crt,readonly') for value in mounts)
    assert any(value.endswith('/smoke/rate,readonly') for value in mounts)
    assert any(value.endswith('/smoke/output') for value in mounts)
    assert commands[3] == ['docker', 'start', '--attach', container_id]
    assert commands[-1] == ['docker', 'rm', '-f', container_id]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in rate_root.iterdir() if path.is_file())
    assert stat.S_IMODE(output_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(ca_cert.stat().st_mode) == 0o600


@pytest.mark.parametrize('failure', [
    'start-timeout', 'unexpected-marker', 'owner-mismatch', 'image-mismatch',
    'user-mismatch', 'namespace-mismatch', 'cleanup-error',
])
def test_g2_rate_sidecar_failures_never_delete_by_name_and_cleanup_only_validated_id(tmp_path, failure):
    args, _private_root, rate_root, _output_root, _ca_cert, config = _rate_sidecar_setup(tmp_path)
    identity = None
    start_result = None
    rm_code = 0
    if failure == 'start-timeout':
        start_result = subprocess.TimeoutExpired(['docker', 'start'], 120)
    elif failure == 'unexpected-marker':
        start_result = subprocess.CompletedProcess(['docker', 'start'], 0, 'wrong=200\n', '')
    elif failure == 'owner-mismatch':
        identity = _sidecar_inspect(args, '9' * 64, owner='another-project')
    elif failure == 'image-mismatch':
        identity = _sidecar_inspect(args, '9' * 64, image=APP_IMAGE_ID)
    elif failure == 'user-mismatch':
        identity = _sidecar_inspect(args, '9' * 64, user='0:0')
    elif failure == 'namespace-mismatch':
        identity = _sidecar_inspect(args, '9' * 64, network='container:another-gateway')
    elif failure == 'cleanup-error':
        rm_code = 1
    calls, run, container_id = _mock_sidecar_lifecycle(
        args, rate_root, start_result=start_result, identity=identity, rm_code=rm_code,
    )
    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        with pytest.raises(acceptance.AcceptanceError) as error:
            acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config)])
    if failure == 'cleanup-error':
        assert isinstance(error.value, acceptance.CleanupAcceptanceError)
        assert error.value.cleanup_status == 'FAIL'

    commands = [command for command, _kwargs in calls]
    assert not any(command[1] == 'run' for command in commands)
    assert not any(command[-1].startswith('nhsmoke-rate-') for command in commands if command[1] == 'rm')
    assert commands[1][1] == 'create'
    assert commands[2][1] == 'inspect'
    identity_failure = failure in {'owner-mismatch', 'image-mismatch', 'user-mismatch', 'namespace-mismatch'}
    if identity_failure:
        assert not any(command[1] == 'start' for command in commands)
        assert not any(command[1] == 'rm' for command in commands)
    else:
        assert commands[3][1] == 'start'
        assert commands[-2:] == [['docker', 'inspect', '--type', 'container', container_id], ['docker', 'rm', '-f', container_id]]


@pytest.mark.parametrize('ledger_change', ['lost', 'replaced'])
def test_g2_rate_sidecar_lost_or_replaced_ledger_fails_but_cleans_only_memory_cid(tmp_path, ledger_change):
    args, _private_root, rate_root, _output_root, _ca_cert, config = _rate_sidecar_setup(tmp_path)
    calls, run, container_id = _mock_sidecar_lifecycle(
        args, rate_root, ledger_after_start=ledger_change,
        start_result=subprocess.CompletedProcess(['docker', 'start'], 0, 'csrf=200\n', ''),
    )
    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        with pytest.raises(acceptance.AcceptanceError, match='CID ledger'):
            acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config)])

    commands = [command for command, _kwargs in calls]
    assert ['docker', 'rm', '-f', container_id] in commands
    assert not any(command[-1] == '8' * 64 for command in commands if command[1] in {'inspect', 'rm'})
    assert not any(command[1] == 'rm' and command[-1].startswith('nhsmoke-rate-') for command in commands)


def test_g2_rate_sidecar_create_timeout_with_written_owned_cid_is_removed_by_exact_id(tmp_path):
    args, _private_root, rate_root, _output_root, _ca_cert, config = _rate_sidecar_setup(tmp_path)
    calls, run, container_id = _mock_sidecar_lifecycle(
        args, rate_root, create_timeout=True,
    )
    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        with pytest.raises(acceptance.AcceptanceError, match='bounded runtime') as error:
            acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config)])

    assert not isinstance(error.value, acceptance.CleanupAcceptanceError)
    commands = [command for command, _kwargs in calls]
    assert ['docker', 'rm', '-f', container_id] in commands
    assert not any(command[1] == 'rm' and command[-1].startswith('nhsmoke-rate-') for command in commands)


def test_g2_rate_sidecar_create_timeout_without_verifiable_cid_marks_cleanup_fail(tmp_path):
    args, _private_root, rate_root, _output_root, _ca_cert, config = _rate_sidecar_setup(tmp_path)
    calls, run, _container_id = _mock_sidecar_lifecycle(
        args, rate_root, create_timeout=True, write_cid=False,
    )
    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        with pytest.raises(acceptance.CleanupAcceptanceError) as error:
            acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config)])

    assert error.value.cleanup_status == 'FAIL'
    commands = [command for command, _kwargs in calls]
    assert not any(command[1] == 'rm' for command in commands)


def test_g2_rate_sidecar_create_failure_without_cid_does_not_delete_reused_name(tmp_path):
    args, _private_root, _rate_root, _output_root, _ca_cert, config = _rate_sidecar_setup(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ['docker', 'inspect', '--type']:
            return subprocess.CompletedProcess(command, 1, '', '')
        if command[:2] == ['docker', 'create']:
            return subprocess.CompletedProcess(command, 1, '', '')
        raise AssertionError(f'unexpected command after failed create: {command}')

    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        with pytest.raises(acceptance.AcceptanceError, match='create failed'):
            acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config)])
    assert [command[1] for command, _kwargs in calls] == ['inspect', 'create']


def test_g2_rate_sidecar_refuses_a_preexisting_random_name_before_create_or_remove(tmp_path):
    args, _private_root, _rate_root, _output_root, _ca_cert, config = _rate_sidecar_setup(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert command[:3] == ['docker', 'inspect', '--type']
        return subprocess.CompletedProcess(command, 0, '[{}]', '')

    with (
        patch.object(acceptance, '_inspect_g2_gateway', return_value={
            'container_id': GATEWAY_CONTAINER_ID, 'network_id': NETWORK_ID, 'ip': '172.28.0.2',
        }),
        patch.object(acceptance.subprocess, 'run', side_effect=run),
    ):
        with pytest.raises(acceptance.AcceptanceError, match='name is already in use'):
            acceptance._run_rate_sidecar(args, '127.0.0.70', [('csrf', config)])
    assert len(calls) == 1
    assert not any(command[1] in {'create', 'start', 'rm'} for command, _kwargs in calls)


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
                body_path = rate_root / 'output' / f'{config.stem}.body'
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
                headers_path = rate_root / 'output' / f'{config.stem}.headers'
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
