"""T09 live experiment, reusing only T00 pinned images/config as a read-only base."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]


def run(args, *, env=None, input=None):
    return subprocess.run(args, env=env, input=input, text=True, capture_output=True,
                          check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch('newshub-rss-t09:[a-zA-Z0-9_.-]+', args.image):
        parser.error('explicit local T09 image required')
    endpoint = None if os.environ.get('DOCKER_CONTEXT') else os.environ.get('DOCKER_HOST')
    endpoint = endpoint or run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    if not endpoint.startswith('unix://'):
        parser.error('local Unix-socket Docker daemon required')
    project = 'newshub-rss-t09-' + uuid.uuid4().hex[:12]
    for resource in ('container', 'network', 'volume'):
        command = ['docker', 'ps', '-aq'] if resource == 'container' else ['docker', resource, 'ls', '-q']
        if run(command + ['--filter', 'label=com.docker.compose.project=' + project]).stdout.strip():
            parser.error('refusing existing project resources')
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        tls = root / 'tls'
        tls.mkdir()
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'),
            '-subj', '/CN=publisher.example', '-addext', 'subjectAltName=DNS:publisher.example,DNS:zero.publisher.example'])
        token = root / 'collector-token'
        token.write_text('synthetic-pending')
        token.chmod(0o644)
        overlay = {'services': {
            'fixture': {'command': ['python', '/fixture/server.py'],
                'volumes': [str(ROOT / 'ops/rss/T09/publisher.py') + ':/fixture/server.py:ro',
                            str(tls) + ':/fixture/tls:ro'],
                'networks': {'isolated': {'aliases': ['publisher.example', 'zero.publisher.example']}}},
            'engine': {'environment': {'SSL_CERT_FILE': '/fixture-ca.pem', 'HTTP_CLIENT_TIMEOUT': '2'},
                'volumes': [str(tls / 'cert.pem') + ':/fixture-ca.pem:ro'],
                'healthcheck': {'test': ['CMD', '/usr/bin/miniflux', '-healthcheck', 'auto'],
                                'interval': '1s', 'timeout': '5s', 'retries': 60}},
            'worker': {'image': args.image, 'command': ['sleep', 'infinity'],
                'environment': {'DJANGO_SECRET_KEY': 'synthetic-t09-abcdefghijklmnopqrstuvwxyz-0123456789-abcdef',
                    'WAITRESS_TRUSTED_PROXY': '127.0.0.1', 'RSS_ENGINE_INSTANCE_UUID': str(uuid.uuid4()),
                    'RSS_ENGINE_ACCOUNT_ID': '2', 'RSS_ENGINE_BASE_URL': 'http://engine:8080',
                    'RSS_ENGINE_TOKEN_FILE': '/run/secrets/collector-token',
                    'DJANGO_DB_PATH': '/var/lib/newshub/db/db.sqlite3'},
                'read_only': True, 'volumes': [str(token) + ':/run/secrets/collector-token:ro'],
                'tmpfs': ['/var/lib/newshub/db:uid=10001,gid=10001',
                          '/var/lib/newshub/rss-runtime:uid=10001,gid=10001', '/tmp'],
                'networks': ['isolated']}}}
        path = root / 'overlay.json'
        path.write_text(json.dumps(overlay))
        compose = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'ops/rss/T00/compose.yaml'), '-f', str(path)]
        def call(*args, input=None):
            return run(compose + list(args), input=input).stdout.strip()
        print('isolated project:', project, flush=True)
        try:
            call('up', '-d', '--wait', 'engine', 'fixture', 'worker')
            address = call('port', 'engine', '8080')
            assert address.startswith('127.0.0.1:')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(path, data, username, password):
                auth = base64.b64encode((username + ':' + password).encode()).decode()
                request = urllib.request.Request('http://' + address + '/v1/' + path,
                    data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
                with opener.open(request, timeout=10) as response:
                    return json.load(response)
            user = api('users', {'username': 't09_collector', 'password': 'synthetic-collector', 'is_admin': False},
                       't00_admin', 'synthetic-t00-admin')
            assert user['id'] == 2 and user['is_admin'] is False
            key = api('api-keys', {'description': 'T09 isolated only'}, 't09_collector', 'synthetic-collector')['token']
            token.write_text(key)
            driver = (ROOT / 'ops/rss/T09/live_driver.py').read_text()
            def stage(name):
                try:
                    return json.loads(call('exec', '-T', '-e', 'T09_STAGE=' + name,
                        'worker', 'python', '-', input=driver))
                except subprocess.CalledProcessError as error:
                    raise RuntimeError(error.stderr[-6000:]) from None
            def sql(statement):
                return call('exec', '-T', 'postgres', 'psql', '-U', 'rss_contract', '-d',
                            'rss_contract', '-v', 'ON_ERROR_STOP=1', '-c', statement)
            evidence = {'bootstrap': stage('bootstrap')}
            sql("CREATE TABLE t09_delayed AS SELECT * FROM entries WHERE id=2; DELETE FROM entries WHERE id=2;")
            evidence['initial'] = stage('initial')
            call('stop', 'engine')
            evidence['outage'] = stage('outage')
            call('up', '-d', '--wait', 'engine')
            sql("INSERT INTO entries SELECT * FROM t09_delayed; UPDATE entries SET content='<p>Changed retained body from engine.</p>' WHERE id=1;")
            sql("INSERT INTO entries SELECT (jsonb_populate_record(NULL::entries, to_jsonb(e) || jsonb_build_object('id', nextval('entries_id_seq'), 'url', 'https://publisher.example:8443/old-date', 'hash', 't09-high-id-old-date', 'title', 'Old date new ID', 'published_at', '1990-01-01T00:00:00Z'))).* FROM entries e LIMIT 1;")
            evidence['reconcile'] = stage('reconcile')
            sql("DELETE FROM entries;")
            evidence['cleanup'] = stage('cleanup')
            call('exec', '-d', 'worker', 'python', '/app/backend/manage.py', 'rss_sync_worker')
            for _ in range(20):
                time.sleep(1)
                health = json.loads(call('exec', '-T', 'worker', 'python', '/app/backend/manage.py',
                                        'rss_sync_worker', '--healthcheck'))
                if health.get('sync_ready'):
                    break
            assert health['mode'] == 'sync_worker' and health['sync_ready'], health
            evidence.update(runtime_health=health, project=project,
                image_id=json.loads(run(['docker', 'image', 'inspect', args.image]).stdout)[0]['Id'],
                publisher='synthetic HTTPS + temporary test CA; private fetch allowed ONLY here')
        finally:
            call('down', '--volumes', '--remove-orphans')
        assert not call('ps', '-aq')
        evidence['resources_removed'] = True
        args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
        print('PASS: real engine sync, crash replay, DB busy, outage, retained sweep and cleanup')


if __name__ == '__main__':
    main()
