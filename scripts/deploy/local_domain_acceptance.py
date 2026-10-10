#!/usr/bin/env python3
"""G1 acceptance checks for the isolated news.lambert.host smoke stack."""

from __future__ import annotations

import argparse
import importlib.metadata
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


HOST = 'news.lambert.host'
PLAYWRIGHT_VERSION = '1.62.0'
STATUS_MARKER = '\n__NEWSHUB_HTTP_STATUS__='
FORWARDED_SPOOF_HEADERS = (
    'X-Forwarded-Proto: http',
    'X-Forwarded-For: 198.51.100.44',
    'Forwarded: proto=http;host=spoof.invalid',
    'X-Forwarded-Host: spoof.invalid',
    'X-Forwarded-Port: 80',
)
SSE_PROXY_HEADER_MARKER = b'data: proxy-headers='


class AcceptanceError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _run_checked(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        raise AcceptanceError(f"command failed: {Path(command[0]).name} (exit {result.returncode})")
    return result


def _curl_command(args: argparse.Namespace, path: str, *, scheme: str = 'https', port: int | None = None,
                  method: str = 'GET', headers: tuple[str, ...] = (), body: str | None = None,
                  header_file: Path | None = None) -> list[str]:
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
    _require(status == expected, f'{name} expected HTTP {expected}, got {status}')
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
    _require(capabilities.get('site_mode') == 'read_only', 'production smoke did not stay in read_only mode')
    _require(
        any('no-store' in value.lower() for value in capability_headers.get('cache-control', [])),
        'capabilities response is missing Cache-Control: no-store',
    )

    search_body, _ = _expect_status(
        args,
        checks,
        'keyword_search',
        '/api/news/?search=NewshubLocalDomainG1Fixture',
        200,
    )
    _require('NewshubLocalDomainG1Fixture' in search_body, 'keyword search did not return the seeded fixture')

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
    with tempfile.TemporaryDirectory(prefix='newshub-browser-', dir=work_dir) as temp_name:
        profile_root = Path(temp_name)
        task_browser_home = profile_root / 'untrusted-home'
        task_browser_home.mkdir()
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

        task_browser_home = profile_root / 'trusted-home'
        task_browser_home.mkdir()
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
                mermaid_screenshot = work_dir / 'mermaid-g1.png'
                page.screenshot(path=str(mermaid_screenshot), full_page=True)
                checks['mermaid_chart'] = json.dumps(chart_paint, sort_keys=True)
                checks['mermaid_screenshot'] = str(mermaid_screenshot)

                page.evaluate("() => fetch('/api/auth/csrf/').then((response) => response.json())")
                cookie = page.evaluate("() => document.cookie")
                _require('csrftoken=' in cookie, 'trusted browser cannot read the CSRF cookie')
                checks['browser_csrf_cookie'] = 'readable through document.cookie'

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
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _require(args.ca_cert.is_file(), 'the temporary test CA certificate does not exist')
    _require(args.work_dir.is_dir(), 'the smoke-owned work directory does not exist')

    checks: dict[str, str] = {}
    result = {
        'stage': 'g1',
        'status': 'PASS',
        'checks': checks,
        'image_revision': args.image_revision,
        'nginx_image': args.nginx_image,
    }
    try:
        if args.sse_only:
            _run_sse_check(args, checks)
        else:
            _check_http_api(args, checks, args.work_dir)
            _run_browser_checks(args, checks, args.work_dir)
    except Exception as exc:
        result['status'] = 'FAIL'
        result['failure'] = f'{type(exc).__name__}: {exc}'
        screenshot = args.work_dir / 'local-domain-browser-failure.png'
        if screenshot.is_file():
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
