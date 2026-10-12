"""Isolated synthetic Django -> Nginx -> real Axios/browser regression probe.
Run with a Python containing Django + Playwright, node, frontend deps, and
NEWS_TEST_NGINX pointing to a user-space nginx binary. No external services.
"""
import gzip
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import PropertyMock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from socketserver import ThreadingMixIn

ROOT = Path(__file__).resolve().parents[1]
NGINX = os.environ['NEWS_TEST_NGINX']
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'newsaggregator.settings'
# Use the repository's existing test-process guard before django.setup().
os.environ['PYTEST_CURRENT_TEST'] = 'isolated_news_slow_network'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
# Fail before any model load or inference, even if startup guards regress.
preload_guard = patch('api.services.embedding.EmbeddingService.preload', side_effect=AssertionError('Model preload forbidden')).start()
model_guard = patch('api.services.embedding.EmbeddingService.model', new_callable=PropertyMock, side_effect=AssertionError('Model load forbidden')).start()
encode_guard = patch('api.services.embedding.EmbeddingService.encode', side_effect=AssertionError('Model inference forbidden')).start()


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Server(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix='news-summary-') as directory:
    tmp = Path(directory)
    (tmp / 'logs').mkdir()
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = str(tmp / 'synthetic.sqlite3')
    settings.CHATGPT_DEPLOYMENT_INSTANCE_FILE = tmp / 'deployment-id'
    import django
    django.setup()
    preload_guard.assert_not_called()
    model_guard.assert_not_called()
    encode_guard.assert_not_called()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.utils import timezone
    from api.models import Category, Source, News
    call_command('migrate', verbosity=0)
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader
    loader = MigrationLoader(connection)
    api_leaves = [name for app_label, name in loader.graph.leaf_nodes() if app_label == 'api']
    assert api_leaves == ['0034_add_litellm_provider_fields'], api_leaves
    assert ('api', '0034_add_litellm_provider_fields') in loader.applied_migrations
    call_command('makemigrations', check=True, dry_run=True, verbosity=0)

    category = Category.objects.create(name='Synthetic', slug='synthetic')
    source = Source.objects.create(name='Synthetic', url='https://example.com')
    for i in range(20):
        News.objects.create(title=f'Synthetic article {i}', title_zh=f'合成文章{i}',
            content='Synthetic article paragraph. ' * 500, content_zh='合成新闻段落。' * 500,
            full_content='complete full body ' * 1000, source=source, category=category,
            url=f'https://example.com/{i}', publish_time=timezone.now())
    # Test-only reconstruction of the former list body, not a production legacy API.
    from rest_framework.test import APIClient
    from rest_framework.renderers import JSONRenderer
    baseline_data = APIClient().get('/api/news/?page_size=20').data
    bodies = {article.pk: article for article in News.objects.all()}
    baseline_data['results'] = [{
        ('content' if key == 'summary' else 'content_zh' if key == 'summary_zh' else key):
        (bodies[item['id']].content if key == 'summary' else
         bodies[item['id']].content_zh if key == 'summary_zh' else value)
        for key, value in item.items()
    } for item in baseline_data['results']]
    legacy_fixture = JSONRenderer().render(baseline_data)
    app = get_wsgi_application()

    def upstream(environ, start_response):
        if environ['PATH_INFO'] == '/api/test-baseline-news/':
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [legacy_fixture]
        if environ['PATH_INFO'] == '/api/news/1/chat/':
            start_response('200 OK', [('Content-Type', 'text/event-stream')])
            return [b'data: synthetic\n\n']
        if environ['PATH_INFO'] == '/api/auth/probe/':
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [b'{"synthetic_private":"' + b'x' * 5000 + b'"}']
        if 'test_delay=12' in environ['QUERY_STRING']:
            time.sleep(12)
        return app(environ, start_response)

    server = make_server('127.0.0.1', 0, upstream, server_class=Server, handler_class=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    upstream_port = server.server_port
    http_port, https_port, vite_port = port(), port(), port()
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(tmp / 'key.pem'), '-out', str(tmp / 'cert.pem'),
        '-days', '1', '-subj', '/CN=news.lambert.host'], check=True, capture_output=True)
    template = (ROOT / 'deploy/nginx/news.lambert.host.conf').read_text()
    template = template.replace('listen 80;', f'listen 127.0.0.1:{http_port};')
    template = template.replace('listen 443 ssl;', f'listen 127.0.0.1:{https_port} ssl;')
    template = template.replace('http://127.0.0.1:9527', f'http://127.0.0.1:{upstream_port}')
    template = template.replace('/etc/nginx/snippets/newshub-proxy.conf', str(ROOT / 'deploy/nginx/newshub-proxy.conf'))
    template = template.replace('/etc/letsencrypt/live/news.lambert.host/fullchain.pem', str(tmp / 'cert.pem'))
    template = template.replace('/etc/letsencrypt/live/news.lambert.host/privkey.pem', str(tmp / 'key.pem'))
    config = tmp / 'nginx.conf'
    config.write_text(f'pid {tmp}/nginx.pid;\nerror_log {tmp}/error.log;\nevents {{}}\nhttp {{ access_log off; client_body_temp_path {tmp}/body; proxy_temp_path {tmp}/proxy;\n' + template + '\n}')
    subprocess.run([NGINX, '-p', str(tmp), '-c', str(config), '-t'], check=True)
    nginx = subprocess.Popen([NGINX, '-p', str(tmp), '-c', str(config), '-g', 'daemon off;'])
    harness = ROOT / 'frontend' / f'{tmp.name}.html'
    harness.write_text("<script type='module'>import * as api from '/src/services/api.ts';import axios from 'axios';window.api=api;window.axios=axios;</script>")
    node_script = tmp / 'vite.mjs'
    node_script.write_text('''import {createServer} from %s;
const server = await createServer({root:%s, configFile:%s, server:{host:'127.0.0.1',port:%s,strictPort:true,proxy:{'/api':{target:%s,secure:false,changeOrigin:false,headers:{host:'news.lambert.host'},configure(proxy){proxy.on('proxyReq',(req,client)=>{if(client.url.includes('test_identity=1'))req.setHeader('accept-encoding','identity')})}}}}});
await server.listen(); console.log('READY');
''' % (json.dumps(str(ROOT / 'frontend/node_modules/vite/dist/node/index.js')), json.dumps(str(ROOT / 'frontend')), json.dumps(str(ROOT / 'frontend/vite.config.js')), vite_port, json.dumps(f'https://127.0.0.1:{https_port}')))
    vite = subprocess.Popen(['node', str(node_script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        context = ssl._create_unverified_context()
        def request(path, encoding='identity', accept='application/json', cookie=None):
            req = Request(f'https://127.0.0.1:{https_port}' + path,
                headers={'Host': 'news.lambert.host', 'Accept-Encoding': encoding, 'Accept': accept, **({'Cookie': cookie} if cookie else {})})
            with urlopen(req, context=context) as response:
                return response.read(), dict(response.headers)
        for attempt in range(50):
            try:
                legacy, _ = request('/api/test-baseline-news/?page_size=20')
                break
            except OSError:
                time.sleep(.1)
        compact, _ = request('/api/news/?page_size=20')
        explicit, _ = request('/api/news/?representation=summary&page_size=20')
        assert explicit == compact
        assert all(not {'content', 'content_zh', 'full_content'} & item.keys() for item in json.loads(compact)['results'])
        compressed, headers = request('/api/news/?representation=summary&page_size=20', 'gzip')
        assert headers.get('Content-Encoding') == 'gzip'
        assert 'Accept-Encoding' in headers.get('Vary', '')
        assert 'no-store' in headers.get('Cache-Control', '')
        assert gzip.decompress(compressed) == compact
        for path in ['/api/news/1/', '/api/news/1/chat/', '/api/auth/probe/']:
            _, private_headers = request(path, 'gzip')
            assert 'Content-Encoding' not in private_headers, path
        from django.contrib.auth import get_user_model
        session_client = APIClient()
        reader = get_user_model().objects.create_user(username='nginx-summary-session-reader', password='synthetic-only')
        session_client.force_login(reader)
        session_cookie = f'{settings.SESSION_COOKIE_NAME}={session_client.cookies[settings.SESSION_COOKIE_NAME].value}'
        negotiation_probes = []
        for scope, cookie in [('anonymous', None), ('session', session_cookie)]:
            for path, accept, expected in [('/api/news/', 'text/html', 406),
                                           ('/api/news/?format=api', 'application/json', 404)]:
                try:
                    request(path, 'gzip', accept, cookie)
                    raise AssertionError('Browsable HTML unexpectedly accepted')
                except HTTPError as error:
                    body = error.read()
                    assert error.code == expected
                    assert error.headers.get('Content-Type', '').startswith('application/json')
                    assert error.headers.get('Content-Encoding') is None
                    assert b'<html' not in body.lower()
                    assert b'csrfmiddlewaretoken' not in body
                    assert reader.username.encode() not in body
                    negotiation_probes.append({'scope': scope, 'accept': accept,
                        'path': path, 'status': error.code, 'content_type': error.headers.get('Content-Type'),
                        'content_encoding': None, 'result': 'PASS: JSON error, no HTML'})
        report = {'legacy_bytes': len(legacy), 'summary_bytes': len(compact),
            'nginx_gzip_bytes': len(compressed), 'gzip_round_trip': 'PASS',
            'detail_sse_private_uncompressed': 'PASS', 'html_negotiation_probes': negotiation_probes}
        print('PAYLOAD', json.dumps(report), flush=True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page()
            page.on('pageerror', lambda error: print('BROWSER_ERROR', error, flush=True))
            page.on('console', lambda message: print('BROWSER_CONSOLE', message.text, flush=True) if message.type == 'error' else None)
            page.on('requestfailed', lambda request: print('BROWSER_REQUEST_FAILED', request.url, request.failure, flush=True))
            for attempt in range(5):
                try:
                    page.goto(f'http://127.0.0.1:{vite_port}/{harness.name}', timeout=3000)
                    page.wait_for_function('window.api && window.axios', timeout=3000)
                    break
                except Exception as error:
                    print('HARNESS_LOAD_FAILED', type(error).__name__, page.url, page.content()[:300], flush=True)
                    if vite.poll() is not None:
                        raise RuntimeError(vite.stderr.read())
                    time.sleep(.1)
            page.wait_for_function('window.api && window.axios', timeout=3000)
            cdp = page.context.new_cdp_session(page)
            cdp.send('Network.enable')
            cdp.send('Network.emulateNetworkConditions', {'offline':False,'latency':100,
                'downloadThroughput':20480,'uploadThroughput':20480})
            tests = {
                'legacy_fixture_10s_identity': "window.axios.get('/api/test-baseline-news/',{timeout:10000,params:{page_size:20,test_identity:1}}).then(r=>r.data)",
                'default_list_10s_identity': "window.axios.get('/api/news/',{timeout:10000,params:{page_size:20,test_identity:1}}).then(r=>r.data)",
                'summary_30s_identity': "window.api.fetchNews({page_size:20,test_identity:1})",
                'summary_30s_gzip': "window.api.fetchNews({page_size:20})",
                'summary_30s_delay12': "window.api.fetchNews({page_size:20,test_delay:12})",
            }
            for name, expression in tests.items():
                result = page.evaluate('''async expression => {const start=performance.now();try {const data=await eval(expression);return {outcome:'SUCCESS',ms:Math.round(performance.now()-start),count:data.results.length,hasBody:'content' in data.results[0]}} catch(e){return {outcome:'FAILURE',ms:Math.round(performance.now()-start),code:e.code,message:e.message}}}''', expression)
                report[name] = result
                print(name, json.dumps(result), flush=True)
            assert report['legacy_fixture_10s_identity']['code'] == 'ECONNABORTED'
            for name in tests:
                if name.startswith('summary') or name.startswith('default_list'):
                    assert report[name]['outcome'] == 'SUCCESS'
                    assert report[name]['count'] == 20
                    assert report[name]['hasBody'] is False
            browser.close()
        preload_guard.assert_not_called()
        model_guard.assert_not_called()
        encode_guard.assert_not_called()
        report['model_preload_load_inference_guards'] = 'PASS: zero calls'
        report['api_migration_leaf'] = api_leaves[0]
        report['migration_state'] = 'PASS: migrations applied through 0034; no model changes'

        report['baseline_fixture'] = 'Former list reconstructed from synthetic full bodies; test-only endpoint'
        print(json.dumps(report, indent=2), flush=True)
        output = os.environ.get('NEWS_TEST_REPORT')
        if output:
            Path(output).write_text(json.dumps(report, indent=2) + '\n')
    finally:
        harness.unlink(missing_ok=True)
        vite.terminate()
        vite.wait(timeout=10)
        nginx.terminate()
        nginx.wait(timeout=10)
        server.shutdown()
        server.server_close()
