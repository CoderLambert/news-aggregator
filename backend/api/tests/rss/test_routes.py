"""Pure T18 syntax/auth-selection contracts; no DNS, service token or network."""
import json
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType

import pytest
import yaml

from api.rss import routes

ORIGIN = 'https://feeds.example.com'
CONFIG = routes.GatewayConfig(ORIGIN, approved_repositories=(('DIYgod', 'RSSHub'),))


def test_issue_template_matches_pinned_directory_and_canonical_alias():
    route = routes.render_route('github.issue', {'user': 'DIYgod', 'repo': 'RSSHub'})
    assert route.alias == 'rsshub://github/issue/DIYgod/RSSHub/open'
    assert routes.parse_alias('rsshub://github/issue/DIYgod/RSSHub') == route
    assert route.public()['content_kind'] == 'issue' and not route.public()['executable']
    source = Path(routes.__file__).with_name('directory_data') / 'rsshub-subset-v1.json'
    assert json.loads(source.read_text())['namespaces']['github']['routes']['/issue/:user/:repo/:state?/:labels?']['path'] == routes.ISSUE_TEMPLATE.removeprefix('/github')


def test_trending_parameters_and_actual_object_type_are_explicit():
    route = routes.render_route('github.trending', {'since': 'weekly', 'language': 'rust', 'spoken_language': 'zh'})
    assert route.alias == 'rsshub://github/trending/weekly/rust/zh'
    assert routes.parse_alias(route.alias) == route
    assert route.public()['content_kind'] == 'repository'
    assert route.public()['capability_requirements'] == ['config:GITHUB_ACCESS_TOKEN']
    assert all(not template['executable'] for template in routes.template_metadata())


@pytest.mark.parametrize('value', ['../admin', '..', '.', '//127.0.0.1', 'https://evil.example',
    'x/y', r'x\y', '%2fadmin', '%252fadmin', '%2e%2e', 'x?url=https://evil.example',
    'x#fragment', 'x\nAuthorization:secret', 'x\r\n', 'x\x00', 'x user', '${TOKEN}',
    'x;proxy_pass http://127.0.0.1', 'x@evil.example', 'x:443', '中文'])
def test_route_parameter_injection_is_rejected_without_echo(value):
    with pytest.raises(routes.RouteError) as error:
        routes.render_route('github.issue', {'user': 'DIYgod', 'repo': value})
    assert value not in str(error.value)


@pytest.mark.parametrize('key', ['labels', 'url', 'proxy', 'cookie', 'header', 'password', 'token',
    'GITHUB_ACCESS_TOKEN', 'secret_ref', 'scraper_rules', 'disable_tls', 'limit', 'format'])
def test_only_declared_bounded_parameters_are_accepted(key):
    with pytest.raises(routes.RouteError, match='unsupported_route_parameter'):
        routes.render_route('github.issue', {'user': 'DIYgod', 'repo': 'RSSHub', key: 'synthetic-secret'})


@pytest.mark.parametrize('alias', ['https://feeds.example.com/github/trending/daily/any',
    'rsshub://github@evil.example/trending/daily/any', 'rsshub://github:443/trending/daily/any',
    'rsshub://github.evil.example/trending/daily/any', 'rsshub://github/trending/daily/any?token=secret',
    'rsshub://github/trending/daily/any#secret', 'rsshub://github/trending/daily/any/',
    'rsshub://github//trending/daily/any', 'rsshub://github/trending/daily/%61ny',
    'rsshub://github/issue/DIYgod/RSSHub/open/extra', 'rsshub://rsshub/test', 'rsshub://proxy/https://internal'])
def test_alias_is_not_a_general_url_or_rsshub_proxy(alias):
    with pytest.raises(routes.RouteError):
        routes.parse_alias(alias)


@pytest.mark.parametrize('origin', ['http://feeds.example.com', 'https://127.0.0.1',
    'https://[::1]', 'https://169.254.169.254', 'https://2130706433', 'https://localhost',
    'https://feeds.internal', 'https://feeds.example.com:8443', 'https://user:pass@feeds.example.com',
    'https://feeds.example.com/path', 'https://feeds.example.com?password=x', 'https://feeds.example.com.',
    'https://feeds.example.com/#fragment', 'https://%66eeds.example.com'])
def test_gateway_origin_is_fixed_public_https_syntax_only(origin):
    with pytest.raises(routes.RouteError):
        routes.GatewayConfig(origin)


@pytest.mark.parametrize('suffix', ['.evil.example/github/trending/daily/any', ':8443/github/trending/daily/any',
    ':443/github/trending/daily/any', '/github/trending/daily/any?foo=bar', '/github/trending/daily/any#f',
    '/github/trending/daily/%61ny', '/github/trending/daily/any/', '/github/trending/daily/any/../../test',
    '/github/issue/Unapproved/PrivateRepo/open', '/github/issue/DIYgod/RSSHub', '/github/trending/forever/any',
    '/github/trending/daily/https://127.0.0.1', '/test', '/github/..%2Ftest'])
def test_auth_selection_requires_exact_origin_and_canonical_approved_path(suffix):
    with pytest.raises(routes.RouteError):
        routes.match_gateway_target(ORIGIN + suffix, CONFIG)


def test_no_execution_approval_or_credentials_are_shipped_even_if_config_flag_is_true():
    target = routes.gateway_target('rsshub://github/trending/daily/any', CONFIG)
    assert target == ORIGIN + '/github/trending/daily/any'
    assert not routes.LIVE_APPROVALS
    with pytest.raises(routes.RouteError, match='gateway_disabled'):
        routes.gateway_request(target, CONFIG)
    with pytest.raises(routes.RouteError, match='gateway_unverified'):
        routes.gateway_request(target, routes.GatewayConfig(ORIGIN, enabled=True))


def test_synthetic_future_adapter_handoff_never_exposes_reference_or_redirect_permission(monkeypatch):
    # This fixture is only selection logic, not public DNS/TLS/auth/redirect proof.
    monkeypatch.setattr(routes, 'LIVE_APPROVALS', MappingProxyType({
        (ORIGIN, 'github.trending'): (routes.SOURCE_COMMIT, routes.RSSHUB_IMAGE)}))
    config = routes.GatewayConfig(ORIGIN, enabled=True, secret_ref='rsshub_synthetic_auth')
    request = routes.gateway_request(ORIGIN + '/github/trending/daily/python', config)
    assert request.secret_ref == 'rsshub_synthetic_auth' and request.follow_redirects is False
    assert 'secret_ref' not in request.public() and 'rsshub_synthetic_auth' not in repr(request)
    assert 'feed_url' not in request.public() and not request.public()['executable']


def test_profile_and_nginx_default_to_off_and_never_change_engine_private_safety():
    root = Path(__file__).resolve().parents[4]
    overlay = yaml.safe_load((root / 'ops/rss/T18/compose.rsshub.yaml').read_text())
    service = overlay['services']['rsshub']
    assert service['profiles'] == ['rsshub'] and service['image'] == routes.RSSHUB_IMAGE
    assert list(overlay['services']) == ['rsshub'] and 'depends_on' not in service
    assert service['ports'][0].startswith('127.0.0.1:')
    assert service['environment']['CACHE_TYPE'] == 'memory'
    assert service['environment']['ALLOW_USER_SUPPLY_UNSAFE_DOMAIN'] == 'false'
    assert 'REDIS_URL' not in service['environment'] and 'PUPPETEER_WS_ENDPOINT' not in service['environment']
    nginx = (root / 'deploy/nginx/rsshub.gateway.conf.disabled').read_text()
    assert 'set $newshub_rsshub_live 0;' in nginx and 'return 503' in nginx
    for header in ['Authorization', 'Cookie', 'Proxy-Authorization']:
        assert f'proxy_set_header {header} "";' in nginx
    assert 'proxy_hide_header Location;' in nginx and 'proxy_redirect off;' in nginx
    assert 'access_log off;' in nginx and 'proxy_pass_request_headers off;' in nginx
    assert 'FETCHER_ALLOW_PRIVATE_NETWORKS' not in json.dumps(overlay)


@pytest.mark.parametrize('value,expected', [(None, 78), ('', 78), ('synthetic token', 78),
    ('ghp_SYNTHETIC\nsecond-line', 78), ('ghp_' + 'a' * 513, 78), ('ghp_SYNTHETIC_T18_ONLY', 0)])
def test_secret_entrypoint_rejects_bad_files_and_never_traces_value(tmp_path, value, expected):
    root = Path(__file__).resolve().parents[4]
    token = tmp_path / 'synthetic-token'
    if value is not None:
        token.write_text(value)
    # Test-only path substitution; shipped script accepts no user-selected path.
    script = tmp_path / 'entrypoint.sh'
    script.write_text((root / 'ops/rss/T18/rsshub-entrypoint.sh').read_text().replace(
        '/run/secrets/rsshub_github_token', str(token)))
    result = subprocess.run(['sh', '-x', str(script), sys.executable, '-c',
        'import os; assert os.environ["GITHUB_ACCESS_TOKEN"].startswith("ghp_"); print("loaded")'],
        capture_output=True, text=True, timeout=5)
    assert result.returncode == expected
    if value:
        assert value not in result.stdout + result.stderr
