"""Real-browser acceptance on one allowlisted synthetic Docker project + temp app DB."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]
PYTHON = os.environ.get('RSS_T27_PYTHON', sys.executable)

def run(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, check=True, timeout=kwargs.pop("timeout", 180), **kwargs)

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hold', action='store_true')
    parser.add_argument('--automatic-summary', action='store_true')
    parser.add_argument('--browser-script', choices=('browser.py', 'browser_automatic.py', 'browser_followup.py'), default=None)
    args = parser.parse_args()
    endpoint = (None if os.environ.get('DOCKER_CONTEXT') else os.environ.get('DOCKER_HOST')) or run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    assert endpoint.startswith('unix://'), 'local Docker only'
    project = 'newshub-rss-t27-' + uuid.uuid4().hex[:12]
    for kind in ('container', 'network', 'volume'):
        command = ['docker', 'ps', '-aq'] if kind == 'container' else ['docker', kind, 'ls', '-q']
        assert not run(command + ['--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        state = Path(directory); state.chmod(0o700)
        tls = state / 'tls'; tls.mkdir()
        audit = state / 'audit'; audit.mkdir(); audit.chmod(0o777)
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'), '-subj', '/CN=publisher.example', '-addext', 'subjectAltName=DNS:publisher.example,DNS:zero.publisher.example,DNS:restricted.publisher.example'])
        overlay = {'services': {'fixture': {'command': ['python', '/fixture/server.py'],
            'volumes': [str(ROOT / 'ops/rss/T27/publisher.py') + ':/fixture/server.py:ro', str(tls) + ':/fixture/tls:ro', str(audit) + ':/fixture/audit'],
            'networks': {'isolated': {'aliases': ['publisher.example', 'zero.publisher.example', 'restricted.publisher.example']}}},
            'engine': {'environment': {'SSL_CERT_FILE': '/fixture-ca.pem', 'HTTP_CLIENT_TIMEOUT': '3'},
                'volumes': [str(tls / 'cert.pem') + ':/fixture-ca.pem:ro'],
                'healthcheck': {'test': ['CMD', '/usr/bin/miniflux', '-healthcheck', 'auto'], 'interval': '1s', 'timeout': '5s', 'retries': 60}}}}
        overlay_path = state / 'overlay.json'; overlay_path.write_text(json.dumps(overlay))
        compose = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'ops/rss/T00/compose.yaml'), '-f', str(overlay_path)]
        processes, logs = [], []
        def call(*arguments):
            return run(compose + list(arguments)).stdout.strip()
        try:
            call('up', '-d', '--wait', 'engine', 'fixture')
            engine = call('port', 'engine', '8080'); assert engine.startswith('127.0.0.1:')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(path, data, username, password):
                auth = base64.b64encode((username + ':' + password).encode()).decode()
                request = urllib.request.Request('http://' + engine + '/v1/' + path,
                    data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
                with opener.open(request, timeout=15) as response:
                    return json.load(response)
            user = api('users', {'username': 't27_collector', 'password': 'synthetic-collector', 'is_admin': False}, 't00_admin', 'synthetic-t00-admin')
            assert user['id'] == 2 and not user['is_admin']
            token = api('api-keys', {'description': 'isolated T27'}, 't27_collector', 'synthetic-collector')['token']
            secret = state / 'collector-token'; secret.write_text(token); secret.chmod(0o600)
            app_port, ui_port = port(), port()
            common = {'PATH': os.environ['PATH'], 'LANG': 'C.UTF-8', 'PYTHONPATH': str(ROOT / 'backend') + ':' + str(ROOT / 'crawler'),
                'RUN_MAIN': 'true', 'DJANGO_ENV': 'development', 'DJANGO_DEBUG': '1',
                'DJANGO_SECRET_KEY': 'synthetic-t27-only-abcdefghijklmnopqrstuvwxyz0123456789',
                'DJANGO_DB_PATH': str(state / 'db.sqlite3'), 'DJANGO_ALLOWED_HOSTS': '127.0.0.1,localhost',
                'DJANGO_CSRF_TRUSTED_ORIGINS': f'http://127.0.0.1:{ui_port},http://127.0.0.1:{app_port}',
                'RSS_ENGINE_INSTANCE_UUID': str(uuid.uuid4()), 'RSS_ENGINE_ACCOUNT_ID': '2',
                'RSS_RUNTIME_DIR': str(state / 'runtime'), 'T27_STATE_DIR': str(state),
                'T27_APP_ADDRESS': f'127.0.0.1:{app_port}', 'CHATGPT_AUTH_MODE': 'disabled',
                'RSS_FULL_CONTENT_ENABLED': '1'}
            worker_env = {**common, 'NEWSHUB_RUNTIME_ROLE': 'rss_sync', 'RSS_ENGINE_BASE_URL': 'http://' + engine, 'RSS_ENGINE_TOKEN_FILE': str(secret)}
            fixture = json.loads(run([PYTHON, str(ROOT / 'ops/rss/T27/bootstrap.py')], env=worker_env, cwd=ROOT).stdout)
            config = {**fixture, 'origin': f'http://127.0.0.1:{ui_port}', 'app_origin': f'http://127.0.0.1:{app_port}',
                'project': project, 'state_dir': str(state), 'output': str(args.output.resolve()), 'engine_address': engine,
                'database': common['DJANGO_DB_PATH'], 'tested_sha': run(['git', 'rev-parse', 'HEAD'], cwd=ROOT).stdout.strip()}
            config_path = state / 'browser-config.json'; config_path.write_text(json.dumps(config))
            (state / 'worker-env.json').write_text(json.dumps(worker_env))
            def start(command, env, name, cwd=ROOT):
                handle = (state / (name + '.log')).open('w'); logs.append(handle)
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
                processes.append(process)
            start([PYTHON, str(ROOT / 'ops/rss/T27/server.py')], common, 'app')
            start([PYTHON, str(ROOT / 'backend/manage.py'), 'rss_sync_worker'], worker_env, 'sync')
            modules = ROOT / 'frontend/node_modules'
            if not modules.exists():
                modules.symlink_to(os.environ.get('RSS_T27_NODE_MODULES', '/tmp/newshub-rss-integration-20261016/frontend/node_modules'), target_is_directory=True)
            config_js = state / 'vite.config.mjs'
            config_js.write_text('import base from ' + json.dumps(str(ROOT / 'frontend/vite.config.js')) + '; export default {...base,root:' + json.dumps(str(ROOT / 'frontend')) + ',cacheDir:' + json.dumps(str(state / 'vite-cache')) + ',server:{...base.server,host:"127.0.0.1",port:' + str(ui_port) + ',strictPort:true,proxy:{"/api":{target:' + json.dumps(f'http://127.0.0.1:{app_port}') + ',changeOrigin:true}}}};')
            start(['node', str(modules / 'vite/bin/vite.js'), '--config', str(config_js), '--configLoader', 'native'], common, 'vite', ROOT / 'frontend')
            for _ in range(90):
                try:
                    with opener.open(config['origin'] + '/api/auth/csrf/', timeout=1) as response:
                        if response.status == 200: break
                except Exception:
                    time.sleep(1)
            else:
                raise RuntimeError('app startup failed: ' + (state / 'app.log').read_text()[-3000:] + (state / 'vite.log').read_text()[-3000:])
            print('T27_CONFIG=' + str(config_path), flush=True)
            if args.hold:
                while True: time.sleep(1)
            browser_script = args.browser_script or ('browser_automatic.py' if args.automatic_summary else 'browser.py')
            result = run([PYTHON, str(ROOT / 'ops/rss/T27' / browser_script), str(config_path)], cwd=ROOT, timeout=600)
            print(result.stdout, flush=True)
            if not args.automatic_summary and browser_script == 'browser.py':
                chats = [json.loads(line) for line in (state / 'ai-contexts.jsonl').read_text().splitlines()]
                assert chats and all('T27 B ONLY SECRET' not in json.dumps(chat) for chat in chats)
                (args.output / 'ai-boundary.json').write_text(json.dumps({'fake_provider_calls':len(chats),'bob_private_title_absent':True,'real_paid_provider_calls':0}))
            (args.output / 'fixture-metrics.json').write_text(json.dumps({'collection_to_visible_seconds':fixture['collection_to_visible_seconds'],'native_mode':'feed','restricted_mode':'feed'}))
            (args.output / 'publisher-requests.jsonl').write_text((audit / 'requests.jsonl').read_text())
        finally:
            for process in reversed(processes): process.terminate()
            for process in reversed(processes):
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            for handle in logs: handle.close()
            for name in ('app', 'sync', 'vite'):
                path = state / (name + '.log')
                if path.exists(): (args.output / (name + '.log')).write_text(path.read_text())
            call('down', '--volumes', '--remove-orphans')
            assert not call('ps', '-aq')
            for kind in ('network', 'volume'):
                assert not run(['docker', kind, 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
            (args.output / 'cleanup.json').write_text(json.dumps({'project': project, 'resources_removed': True}))
if __name__ == '__main__': main()
