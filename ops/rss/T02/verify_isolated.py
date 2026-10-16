"""Create only a fresh T02 project with synthetic secrets; tear it down always."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import urllib.request

ROOT = Path(__file__).resolve().parents[3]


def command(args, *, env=None, input=None, check=True):
    return subprocess.run(args, env=env, input=input, text=True,
                          capture_output=True, check=check, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'newshub-rss-t02:[a-zA-Z0-9_.-]+', args.image):
        parser.error('only explicitly named local T02 test images are accepted')
    endpoint = None if os.environ.get('DOCKER_CONTEXT') else os.environ.get('DOCKER_HOST')
    endpoint = endpoint or command(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    if not endpoint.startswith('unix://'):
        parser.error('requires a local Unix-socket Docker daemon')
    project = 'newshub-rss-t02-' + uuid.uuid4().hex[:12]
    if command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip():
        parser.error('refusing existing project containers')
    if command(['docker', 'network', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip():
        parser.error('refusing existing project network')
    if command(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip():
        parser.error('refusing existing project volumes')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        path = Path(directory)
        os.chmod(path, 0o700)
        files = {'RSS_PG_PASSWORD_FILE': 'synthetic-t02-pg',
            'RSS_DATABASE_URL_FILE': 'postgres://miniflux:synthetic-t02-pg@rss-db/miniflux?sslmode=disable',
            'RSS_ENGINE_ADMIN_PASSWORD_FILE': 'synthetic-t02-admin',
            'RSS_ENGINE_TOKEN_FILE': 'pending-synthetic-collector-token',
            'AI_BYOK_GATEWAY_PROJECT_KEY_FILE': 'synthetic-unused-gateway'}
        env = os.environ.copy()
        for name, value in files.items():
            secret = path / name.lower()
            secret.write_text(value)
            secret.chmod(0o644)  # Protected parent; UID10001 reads its read-only mount.
            env[name] = str(secret)
        env_file = path / 'synthetic.env'
        env_file.write_text('# synthetic isolated T02 configuration only\n')
        env.update(NEWSHUB_IMAGE=args.image, NEWSHUB_RSS_IMAGE=args.image,
            NEWSHUB_ENV_FILE=str(env_file), RSS_ENGINE_PORT='0',
            RSS_ENGINE_INSTANCE_UUID=str(uuid.uuid4()), RSS_ENGINE_ACCOUNT_ID='2',
            DJANGO_SECRET_KEY='synthetic-t02-ORM-only-key-abcdefghijklmnopqrstuvwxyz-0123456789',
            WAITRESS_TRUSTED_PROXY='127.0.0.1')
        override = path / 'isolated.yaml'
        override.write_text('''services:
  migrate:
    command: [python, /app/backend/manage.py, migrate, --noinput, --skip-checks]
  rss-db:
    healthcheck: {interval: 1s, timeout: 5s, retries: 60}
  miniflux:
    healthcheck: {interval: 1s, timeout: 5s, retries: 60, start_period: 1s}
  rss-sync:
    healthcheck: {interval: 1s, timeout: 5s, retries: 60, start_period: 1s}
''')
        compose = ['docker', 'compose', '-p', project, '--env-file', str(env_file),
            '-f', str(ROOT / 'compose.prod.yaml'), '-f', str(ROOT / 'compose.rss.prod.yaml'),
            '-f', str(override), '--profile', 'rss']

        def call(*values, **kwargs):
            return command(compose + list(values), env=env, **kwargs)

        print('isolated project:', project, flush=True)
        try:
            rendered = json.loads(call('config', '--format', 'json').stdout)
            assert rendered['services']['app']['network_mode'] == 'host'
            assert 'ports' not in rendered['services']['rss-db']
            assert rendered['services']['miniflux']['ports'][0]['host_ip'] == '127.0.0.1'
            call('up', '-d', '--wait', 'rss-sync')
            port = call('port', 'miniflux', '8080').stdout.strip()
            assert port.startswith('127.0.0.1:')

            def api(method, route, data=None, username=None, password=None, token=None):
                headers = {'Content-Type': 'application/json'}
                if token:
                    headers['X-Auth-Token'] = token
                else:
                    encoded = base64.b64encode((username + ':' + password).encode()).decode()
                    headers['Authorization'] = 'Basic ' + encoded
                request = urllib.request.Request('http://' + port + '/v1/' + route,
                    data=json.dumps(data).encode() if data is not None else None,
                    headers=headers, method=method)
                with opener.open(request, timeout=10) as response:
                    return json.load(response)

            user = api('POST', 'users', {'username': 't02_collector',
                'password': 'synthetic-t02-collector', 'is_admin': False},
                'newshub-engine-admin', 'synthetic-t02-admin')
            assert user['id'] == 2 and user['is_admin'] is False
            key = api('POST', 'api-keys', {'description': 'T02 isolated only'},
                't02_collector', 'synthetic-t02-collector')['token']
            Path(env['RSS_ENGINE_TOKEN_FILE']).write_text(key)
            assert api('GET', 'me', token=key)['is_admin'] is False
            call('exec', '-T', 'rss-sync', 'python', '-c',
                "import os; from pathlib import Path; import miniflux; "
                "client=miniflux.Client(os.environ['RSS_ENGINE_BASE_URL'], "
                "api_key=Path(os.environ['RSS_ENGINE_TOKEN_FILE']).read_text()); "
                "assert client.me()['is_admin'] is False; print('collector token mount PASS')")
            image_probe = call('exec', '-T', 'rss-sync', 'python', '-',
                input=(ROOT / 'ops/rss/T02/image_probe.py').read_text())
            evidence = json.loads(image_probe.stdout)
            health = json.loads(call('exec', '-T', 'rss-sync', 'python',
                '/app/backend/manage.py', 'rss_runtime', '--healthcheck').stdout)
            assert health['sync_ready'] is False
            duplicate = call('run', '--rm', '--no-deps', 'rss-sync', check=False)
            assert duplicate.returncode != 0 and 'Another rss-sync process' in duplicate.stderr
            for service in ('rss-db', 'miniflux', 'rss-sync'):
                identifier = call('ps', '-q', service).stdout.strip()
                inspected = json.loads(command(['docker', 'inspect', identifier]).stdout)[0]
                assert inspected['State']['Health']['Status'] == 'healthy'
                if service == 'rss-db':
                    assert not inspected['HostConfig']['PortBindings']
                if service == 'rss-sync':
                    assert inspected['HostConfig']['ReadonlyRootfs']
                    assert sorted(m['Destination'] for m in inspected['Mounts']) == [
                        '/run/secrets/rss_engine_token', '/var/lib/newshub/db', '/var/lib/newshub/rss-runtime']
            image = json.loads(command(['docker', 'image', 'inspect', args.image]).stdout)[0]
            evidence.update(project=project, image_id=image['Id'], image_size_bytes=image['Size'],
                miniflux_version=api('GET', 'version', token=key)['version'],
                collector_is_admin=False, duplicate_worker_rejected=True,
                runtime_health=health, production_services_started=False)
        finally:
            call('down', '--volumes', '--remove-orphans')
        assert not call('ps', '-aq').stdout.strip()
        assert not command(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
        evidence['resources_removed'] = True
        args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
        print('PASS: actual Python3.12 image, ORM shell, private PG, collector secret, singleton and cleanup', flush=True)


if __name__ == '__main__':
    main()
