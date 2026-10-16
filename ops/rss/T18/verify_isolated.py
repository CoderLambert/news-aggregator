#!/usr/bin/env python3
"""Actual Nginx/static RSSHub checks with a synthetic local-CA publisher only.

No public DNS provisioning, production TLS, real source token or live route test.
The lab alone changes the candidate's live=0 to1 for local fixture assertions.
"""
import argparse
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from api.rss.routes import RSSHUB_IMAGE, SOURCE_COMMIT

NGINX_IMAGE = 'nginx@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236'
PYTHON_IMAGE = 'python:3.12.12-alpine3.22@sha256:848ba4413eb897e225159b8fc1b02094576cbae4aa73fc13142608ae2c8c0e32'
HOST = 'rsshub.example.com'


def run(arguments, *, input=None):
    try:
        return subprocess.run(arguments, input=input, text=True, capture_output=True, check=True, timeout=180).stdout.strip()
    except subprocess.CalledProcessError as error:
        # All resources and credentials here are synthetic; do not dump config/env.
        raise RuntimeError('isolated subprocess failed: ' + error.stderr[-1500:]) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    endpoint = os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
    endpoint = endpoint or run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'])
    assert endpoint.startswith('unix://'), 'local Unix Docker required'
    project = 'newshub-rss-t18-' + uuid.uuid4().hex[:12]
    for resource in ('container', 'volume', 'network'):
        arguments = ['docker', 'ps', '-aq'] if resource == 'container' else ['docker', resource, 'ls', '-q']
        assert not run(arguments + ['--filter', 'label=com.docker.compose.project=' + project])
    print('isolated project:', project, flush=True)
    evidence = {'scope': 'local synthetic TLS/header/redirect tests; public live gate remains BLOCKED',
                'rsshub_image': RSSHUB_IMAGE, 'source_commit': SOURCE_COMMIT, 'nginx_image': NGINX_IMAGE}
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        temporary = Path(directory)
        tls = temporary / 'tls'
        tls.mkdir()
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'),
            '-subj', '/CN=' + HOST, '-addext', 'subjectAltName=DNS:' + HOST])
        password = 'synthetic-gateway-password'
        htpasswd = temporary / 'htpasswd'
        htpasswd.write_text('synthetic:' + run(['openssl', 'passwd', '-apr1', '-stdin'], input=password + '\n') + '\n')
        htpasswd.chmod(0o644)  # Lab APR1 hash only; Nginx worker can read it.
        token = temporary / 'github-token'
        token.write_text('ghp_SYNTHETIC_T18_NOT_A_CREDENTIAL')
        token.chmod(0o600)
        config = (ROOT / 'deploy/nginx/rsshub.gateway.conf.disabled').read_text()
        config = config.replace('listen 443 ssl;', 'listen 8443 ssl;')
        config = config.replace('/etc/letsencrypt/live/' + HOST + '/fullchain.pem', '/fixture-tls/cert.pem')
        config = config.replace('/etc/letsencrypt/live/' + HOST + '/privkey.pem', '/fixture-tls/key.pem')
        config = config.replace('http://127.0.0.1:1200', 'http://fixture:8000')
        candidate = temporary / 'conf'
        candidate.mkdir()
        (candidate / 'default.conf').write_text(config)
        profile = yaml.safe_load((ROOT / 'ops/rss/T18/compose.rsshub.yaml').read_text())
        rsshub = profile['services']['rsshub']
        rsshub['ports'] = ['127.0.0.1::1200']
        rsshub['volumes'] = [str(ROOT / 'ops/rss/T18/rsshub-entrypoint.sh') + ':/run/config/rsshub-entrypoint.sh:ro']
        rsshub['healthcheck'].update(interval='1s', retries=30, start_period='10s')
        compose_file = temporary / 'compose.json'
        compose_file.write_text(json.dumps({'services': {
            'rsshub': rsshub,
            'fixture': {'image': PYTHON_IMAGE, 'command': ['python', '/fixture.py'],
                'volumes': [str(ROOT / 'ops/rss/T18/fixture.py') + ':/fixture.py:ro'], 'networks': ['lab']},
            'gateway': {'image': NGINX_IMAGE,
                'volumes': [str(candidate) + ':/etc/nginx/conf.d:ro', str(tls) + ':/fixture-tls:ro',
                            str(htpasswd) + ':/etc/nginx/rsshub.htpasswd:ro'],
                'ports': ['127.0.0.1::8443'], 'networks': ['lab'], 'depends_on': ['fixture']},
        }, 'networks': {'lab': {'driver': 'bridge'}, 'rsshub-egress': {'driver': 'bridge'}},
            'secrets': {'rsshub_github_token': {'file': str(token)}}}))
        compose = ['docker', 'compose', '-p', project, '-f', str(compose_file), '--profile', 'rsshub']
        def call(*arguments):
            return run(compose + list(arguments))
        try:
            call('up', '-d', '--wait')
            call('exec', '-T', 'gateway', 'nginx', '-t')
            address = call('port', 'gateway', '8443')
            assert address.startswith('127.0.0.1:')
            port = int(address.rsplit(':', 1)[1])
            context = ssl.create_default_context(cafile=str(tls / 'cert.pem'))
            class BoundHTTPS(http.client.HTTPSConnection):
                def connect(self):
                    raw = socket.create_connection(('127.0.0.1', port), timeout=5)
                    self.sock = self._context.wrap_socket(raw, server_hostname=HOST)
            def get(path, *, authenticated=True, method='GET', host=HOST):
                headers = {'Host': host, 'Cookie': 'synthetic-cookie', 'Proxy-Authorization': 'synthetic-proxy-auth'}
                if authenticated:
                    headers['Authorization'] = 'Basic ' + base64.b64encode(('synthetic:' + password).encode()).decode()
                connection = BoundHTTPS(HOST, port=port, timeout=5, context=context)
                try:
                    connection.request(method, path, headers=headers)
                    response = connection.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    connection.close()
            valid = '/github/trending/daily/any'
            assert get(valid)[0] == 503  # Shipped default remains closed.
            # Test-only activation against a fixed private synthetic upstream.
            (candidate / 'default.conf').write_text(config.replace('set $newshub_rsshub_live 0;', 'set $newshub_rsshub_live 1;'))
            call('exec', '-T', 'gateway', 'nginx', '-t')
            call('exec', '-T', 'gateway', 'nginx', '-s', 'reload')
            deadline = time.monotonic() + 5
            while get(valid, authenticated=False)[0] == 503 and time.monotonic() < deadline:
                time.sleep(.1)
            assert get(valid, authenticated=False)[0] == 401
            status, headers, body = get(valid)
            assert status == 200 and b'Synthetic gateway fixture' in body
            assert get(valid, method='HEAD')[0] == 200
            assert get(valid, method='POST')[0] == 405
            assert get(valid, host=HOST + '.evil.example')[0] == 421
            rejected = ['/test', '/github/trending/daily/any?token=synthetic-secret',
                '/github/trending/daily/%61ny', '/github/trending//daily/any',
                '/github/trending/daily/any/../../test', '/github/issue/Private/Unapproved/open',
                '/github/trending/daily/http:%2f%2f127.0.0.1', '/github/issue/DIYgod/RSSHub/open/labels']
            for path in rejected:
                assert get(path)[0] in {400, 404}
            for since in ('weekly', 'monthly'):
                status, headers, body = get('/github/trending/' + since + '/any')
                assert status == 502 and 'Location' not in headers and b'SYNTHETIC_UPSTREAM_SECRET' not in body
            state = json.loads(call('exec', '-T', 'fixture', 'python', '-c',
                "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/state').read().decode())"))
            assert state and not any(row['authorization'] or row['cookie'] or row['proxy_authorization'] for row in state)
            assert not any(row['path'] == '/leak' for row in state)
            logs = call('logs', '--no-color')
            assert all(value not in logs for value in (password, token.read_text(), 'synthetic-cookie',
                                                       'synthetic-secret', 'SYNTHETIC_UPSTREAM_SECRET'))
            runtime = json.loads(call('exec', '-T', 'rsshub', 'node', '-e',
                'const fs=require("node:fs"); console.log(JSON.stringify({node:process.version,uid:process.getuid(),browserCache:fs.readdirSync("/app/node_modules/.cache/ms-playwright")}));'))
            assert runtime['uid'] == 1000 and runtime['browserCache'] == []
            revision = json.loads(run(['docker', 'image', 'inspect', RSSHUB_IMAGE]))[0]['Config']['Labels']['org.opencontainers.image.revision']
            assert revision == SOURCE_COMMIT
            evidence.update(project=project, default_closed='PASS', nginx_config='PASS', exact_paths_and_host='PASS',
                basic_auth_and_header_stripping='PASS: synthetic', upstream_redirect_refused='PASS: synthetic',
                upstream_error_redacted='PASS: synthetic', selected_logs_secret_free='PASS: synthetic',
                rsshub_nonroot_health='PASS', runtime=runtime, public_dns_tls_hairpin='BLOCKED: no deployment configuration',
                real_github_token_route_objects='BLOCKED: no service token',
                miniflux_publisher_no_redirect_auth='BLOCKED: adapter extension and real gateway proof absent')
        finally:
            call('down', '--volumes', '--remove-orphans')
        for resource in ('container', 'network', 'volume'):
            arguments = ['docker', 'ps', '-aq'] if resource == 'container' else ['docker', resource, 'ls', '-q']
            assert not run(arguments + ['--filter', 'label=com.docker.compose.project=' + project])
        evidence['resources_removed'] = True
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    print('PASS: isolated Nginx + static RSSHub checks; production/live gates remain BLOCKED')


if __name__ == '__main__':
    main()
