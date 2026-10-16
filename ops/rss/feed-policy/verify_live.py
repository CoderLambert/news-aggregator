"""Reuse pinned T00 images in a new, disposable project; no existing services."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]
IMAGE = 'newshub-rss-t08:isolated-final'


def run(args, *, input=None):
    return subprocess.run(args, input=input, text=True, capture_output=True, check=True, timeout=180)


def resources(project, resource):
    command = ['docker', 'ps', '-aq'] if resource == 'container' else ['docker', resource, 'ls', '-q']
    return run(command + ['--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    endpoint = None if os.environ.get('DOCKER_CONTEXT') else os.environ.get('DOCKER_HOST')
    endpoint = endpoint or run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    if not endpoint.startswith('unix://'):
        parser.error('local Unix Docker only')
    project = 'newshub-rss-feed-policy-' + uuid.uuid4().hex[:12]
    for resource in ('container', 'network', 'volume'):
        if resources(project, resource):
            parser.error('refusing existing project resources')
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        tls = root / 'tls'
        tls.mkdir()
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
             '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'), '-subj', '/CN=publisher.example',
             '-addext', 'subjectAltName=DNS:publisher.example,DNS:www.reuters.com,DNS:arxiv.org'])
        token = root / 'collector-token'
        token.write_text('synthetic-pending')
        token.chmod(0o644)
        overlay = {'services': {
            'fixture': {'command': ['python', '/fixture/server.py'], 'volumes': [
                str(ROOT / 'ops/rss/feed-policy/publisher.py') + ':/fixture/server.py:ro',
                str(tls) + ':/fixture/tls:ro'],
                'networks': {'isolated': {'aliases': ['publisher.example', 'www.reuters.com', 'arxiv.org']}}},
            'engine': {'environment': {'SSL_CERT_FILE': '/fixture-ca.pem', 'HTTP_CLIENT_TIMEOUT': '5'},
                'volumes': [str(tls / 'cert.pem') + ':/fixture-ca.pem:ro'],
                'healthcheck': {'test': ['CMD', '/usr/bin/miniflux', '-healthcheck', 'auto'],
                                'interval': '1s', 'timeout': '5s', 'retries': 60}},
            'worker': {'image': IMAGE, 'command': ['sleep', 'infinity'],
                'environment': {'DJANGO_SECRET_KEY': 'synthetic-feed-policy-abcdefghijklmnopqrstuvwxyz-123456789',
                    'WAITRESS_TRUSTED_PROXY': '127.0.0.1', 'RSS_ENGINE_INSTANCE_UUID': str(uuid.uuid4()),
                    'RSS_ENGINE_ACCOUNT_ID': '2', 'RSS_ENGINE_BASE_URL': 'http://engine:8080',
                    'RSS_ENGINE_TOKEN_FILE': '/run/secrets/collector-token', 'RSS_FULL_CONTENT_ENABLED': '1',
                    'NEWSHUB_RUNTIME_ROLE': 'rss_sync', 'DJANGO_DB_PATH': '/var/lib/newshub/db/db.sqlite3'},
                'read_only': True, 'volumes': [str(token) + ':/run/secrets/collector-token:ro',
                    str(ROOT / 'backend') + ':/app/backend:ro'],
                'tmpfs': ['/var/lib/newshub/db:uid=10001,gid=10001', '/tmp'], 'networks': ['isolated']}}}
        path = root / 'overlay.json'
        path.write_text(json.dumps(overlay))
        compose = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'ops/rss/T00/compose.yaml'), '-f', str(path)]
        def call(*args, input=None):
            return run(compose + list(args), input=input).stdout.strip()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        print('isolated project:', project, flush=True)
        try:
            call('up', '-d', '--wait', 'engine', 'fixture', 'worker')
            address = call('port', 'engine', '8080')
            assert address.startswith('127.0.0.1:')
            def api(path, data, username, password):
                auth = base64.b64encode((username + ':' + password).encode()).decode()
                request = urllib.request.Request('http://' + address + '/v1/' + path,
                    data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
                with opener.open(request, timeout=10) as response:
                    return json.load(response)
            user = api('users', {'username': 'policy_collector', 'password': 'synthetic-collector', 'is_admin': False},
                't00_admin', 'synthetic-t00-admin')
            assert user['id'] == 2 and not user['is_admin']
            token.write_text(api('api-keys', {'description': 'isolated feed policy'}, 'policy_collector', 'synthetic-collector')['token'])
            try:
                evidence = json.loads(call('exec', '-T', 'worker', 'python', '-',
                    input=(ROOT / 'ops/rss/feed-policy/live_driver.py').read_text()))
            except subprocess.CalledProcessError as error:
                raise RuntimeError(error.stderr[-5000:]) from None
            fixture = call('port', 'fixture', '8000')
            assert fixture.startswith('127.0.0.1:')
            with opener.open('http://' + fixture + '/state', timeout=5) as response:
                counts = json.load(response)
            assert counts.get('publisher.example:8443/allowed', 0) > 0, counts
            assert counts.get('www.reuters.com:8443/denied', 0) == 0, counts
            assert counts.get('arxiv.org:8443/abstract', 0) == 0, counts
            assert counts.get('publisher.example:8443/native', 0) == 0, counts
            assert counts.get('www.reuters.com:8443/redirect-target', 0) > 0, counts
            evidence.update(project=project, publisher_counters=counts,
                engine_image='miniflux/miniflux:2.3.3@sha256:49d7b60987616387c306a8023087b31f2c9b7b21288b523026cb04058e8b6dbb',
                runtime_image_id=json.loads(run(['docker', 'image', 'inspect', IMAGE]).stdout)[0]['Id'],
                runtime_source='current task backend mounted read-only; existing locked lightweight dependencies',
                redirect_gate='BLOCKED: allowed URL redirected to denied synthetic publisher; no public DNS was used')
        finally:
            call('down', '--volumes', '--remove-orphans')
        assert not any(resources(project, resource) for resource in ('container', 'network', 'volume'))
        evidence['resources_removed'] = True
        args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
        print('PASS: initial mode/filter + closed gate; redirect limitation reproduced; resources removed')


if __name__ == '__main__':
    main()
