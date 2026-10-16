"""Synthetic gateway upstream: no remote fetches and no header-value recording."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

REQUESTS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path == '/state':
            data = json.dumps(REQUESTS).encode()
        else:
            REQUESTS.append({'path': self.path, 'method': self.command,
                'authorization': bool(self.headers.get('Authorization')),
                'proxy_authorization': bool(self.headers.get('Proxy-Authorization')),
                'cookie': bool(self.headers.get('Cookie'))})
            if '/weekly/' in self.path:
                self.send_response(302)
                self.send_header('Location', 'http://fixture:8000/leak')
                self.end_headers()
                return
            if '/monthly/' in self.path:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'SYNTHETIC_UPSTREAM_SECRET')
                return
            data = b'<rss version="2.0"><channel><title>Synthetic gateway fixture</title></channel></rss>'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if self.path == '/state' else 'application/rss+xml')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)


ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
