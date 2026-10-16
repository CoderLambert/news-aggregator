"""Synthetic HTTPS publisher and local counters; never reaches public hosts."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
from threading import Lock, Thread

COUNTS = Counter()
LOCK = Lock()
BASE = 'https://publisher.example:8443'


class Publisher(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        with LOCK:
            COUNTS[self.headers.get('Host', '') + self.path] += 1
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', 'https://www.reuters.com:8443/redirect-target')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path.startswith('/feed'):
            targets = ([BASE + '/allowed', 'https://www.reuters.com:8443/denied', 'https://arxiv.org:8443/abstract']
                       if self.path == '/feed' else [BASE + '/redirect']
                       if self.path == '/feed-redirect' else [BASE + '/native', 'https://arxiv.org:8443/abstract']
                       if self.path == '/feed-only' else [BASE + '/native'])
            items = ''.join(f'<item><guid>{target}</guid><title>Synthetic item</title><link>{target}</link>'
                '<description>Feed summary</description></item>' for target in targets)
            body = f'<rss version="2.0"><channel><title>Synthetic Feed</title><link>{BASE}</link><description>Fixture</description>{items}</channel></rss>'
            kind = 'application/rss+xml'
        else:
            body = '<html><head><title>Publisher body</title></head><body><article><h1>Article</h1><p>' + ('Known synthetic article text. ' * 100) + '</p></article></body></html>'
            kind = 'text/html'
        data = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class State(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        with LOCK:
            data = json.dumps(dict(COUNTS)).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


state = ThreadingHTTPServer(('0.0.0.0', 8000), State)
Thread(target=state.serve_forever, daemon=True).start()
server = ThreadingHTTPServer(('0.0.0.0', 8443), Publisher)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/tls/cert.pem', '/fixture/tls/key.pem')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
