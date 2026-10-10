from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]
NGINX_DIR = PROJECT / 'deploy' / 'nginx'


def _block(source, marker):
    marker_start = source.index(marker)
    line_end = source.find('\n', marker_start)
    if line_end < 0:
        line_end = len(source)
    opening = None
    quote = None
    escaped = False
    for index in range(marker_start, line_end):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == '{':
            opening = index
            break
    if opening is None:
        raise AssertionError(f'block opening not found after {marker!r}')
    depth = 0
    quote = None
    escaped = False
    for index in range(opening, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth == 0:
                return source[opening + 1:index]
    raise AssertionError(f'unclosed Nginx block after {marker!r}')


def test_bootstrap_is_http_only_and_keeps_only_the_acme_fixture():
    bootstrap = (NGINX_DIR / 'news.lambert.host.bootstrap.conf').read_text()

    assert 'server_name news.lambert.host;' in bootstrap
    assert 'listen 80 default_server;' in bootstrap
    assert 'return 444;' in bootstrap
    assert 'location ^~ /.well-known/acme-challenge/' in bootstrap
    assert 'root /var/www/certbot;' in bootstrap
    assert 'try_files $uri =404;' in bootstrap
    assert 'return 503;' in bootstrap
    assert 'listen 443' not in bootstrap
    assert 'ssl_certificate' not in bootstrap


def test_production_hosts_redirects_unknown_hosts_and_static_routing():
    production = (NGINX_DIR / 'news.lambert.host.conf').read_text()
    https_server = _block(
        production,
        'server {\n    listen 443 ssl;\n    server_name news.lambert.host;',
    )

    assert 'server_name news.lambert.host;' in production
    assert production.count('server_name _;') == 2
    assert 'return 444;' in production
    assert 'return 301 https://news.lambert.host$request_uri;' in production
    assert 'location ^~ /.well-known/acme-challenge/' in production
    assert production.count('try_files $uri =404;') >= 8
    assert 'ssl_certificate /etc/letsencrypt/live/news.lambert.host/fullchain.pem;' in production
    assert 'ssl_certificate_key /etc/letsencrypt/live/news.lambert.host/privkey.pem;' in production
    assert 'root /srv/newshub/current;' in production
    assert 'location = /index.html' in https_server
    assert 'add_header Cache-Control "no-store" always;' in _block(
        https_server, 'location = /index.html'
    )

    assert 'location = /favicon.svg' in https_server
    assert 'location = /icons.svg' in https_server
    assert 'location = /favicon.ico' in https_server
    assert 'location = /apple-touch-icon.png' in https_server
    for icon_path in (
        'location = /favicon.svg',
        'location = /icons.svg',
        'location = /favicon.ico',
        'location = /favicon-16x16.png',
        'location = /favicon-32x32.png',
        'location = /apple-touch-icon.png',
        'location = /site.webmanifest',
    ):
        icon = _block(https_server, icon_path)
        assert 'try_files $uri =404;' in icon
        assert 'add_header Cache-Control "no-cache";' in icon

    assert 'location /assets/' in https_server
    regular_assets = _block(https_server, 'location /assets/')
    assert 'root /srv/newshub;' in regular_assets
    assert 'try_files $uri =404;' in regular_assets
    assert 'add_header Cache-Control "no-cache";' in regular_assets
    assert 'immutable' not in regular_assets
    assert 'try_files $uri $uri/ /index.html;' in _block(https_server, 'location / {')
    assert 'location ~* ^/(?!api/|assets/).+\\.' in https_server
    assert 'location ^~ /assets/' not in https_server
    assert 'location ~* "^/assets/' in https_server

    hashed_assets = _block(https_server, 'location ~* "^/assets/')
    assert 'root /srv/newshub;' in hashed_assets
    assert 'add_header Cache-Control "public, max-age=31536000, immutable";' in hashed_assets
    assert 'always' not in hashed_assets
    assert 'try_files $uri =404;' in hashed_assets


def test_api_proxy_overwrites_forwarding_headers_and_disables_caching():
    production = (NGINX_DIR / 'news.lambert.host.conf').read_text()
    proxy = (NGINX_DIR / 'newshub-proxy.conf').read_text()

    for marker in ('location = /api', 'location /api/'):
        api = _block(production, marker)
        assert 'proxy_pass http://127.0.0.1:9527;' in api
        assert 'include /etc/nginx/snippets/newshub-proxy.conf;' in api
        assert 'add_header Cache-Control "no-store" always;' in api
        assert 'try_files' not in api

    assert 'proxy_set_header Host news.lambert.host;' in proxy
    assert 'proxy_set_header X-Forwarded-Proto $scheme;' in proxy
    assert 'proxy_set_header X-Forwarded-For $remote_addr;' in proxy
    for name in ('Forwarded', 'X-Forwarded-Host', 'X-Forwarded-Port'):
        assert f'proxy_set_header {name} "";' in proxy
    assert 'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' not in proxy


def test_only_approved_sse_paths_disable_nginx_buffering_and_compression():
    production = (NGINX_DIR / 'news.lambert.host.conf').read_text()

    sse_markers = (
        'location ~ ^/api/news/[0-9]+/(?:chat|translate)/',
        'location = /api/research/',
        'location ~ "^/api/research/[0-9A-Fa-f]{8}',
    )
    for marker in sse_markers:
        block = _block(production, marker)
        assert 'proxy_buffering off;' in block
        assert 'proxy_cache off;' in block
        assert 'gzip off;' in block
        assert 'proxy_read_timeout 300s;' in block
        assert 'proxy_pass http://127.0.0.1:9527;' in block
        assert 'add_header Cache-Control "no-store" always;' in block

    assert production.count('proxy_buffering off;') == len(sse_markers)
    assert production.count('proxy_cache off;') == len(sse_markers)
    assert production.count('gzip off;') == len(sse_markers)
    assert '/events/' not in production
