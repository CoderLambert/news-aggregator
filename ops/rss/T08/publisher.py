"""Synthetic HTTPS publisher for this experiment; Miniflux is its only reader."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
import time

BASE = 'https://publisher.example:8443'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        zero_host = self.headers.get('Host', '').split(':')[0] == 'zero.publisher.example'
        if self.path == '/slow':
            time.sleep(5)
        if self.path not in {'/feed', '/feed/0', '/feed/1', '/feed/2', '/article',
                             '/discover-zero', '/discover-one', '/discover-many', '/slow', '/'}:
            self.send_error(404)
            return
        if zero_host and self.path not in {'/', '/discover-zero'}:
            self.send_error(404)
            return
        if self.path in {'/feed', '/feed/0', '/feed/1', '/feed/2'}:
            kind = 'application/rss+xml'
            body = f'''<rss version="2.0"><channel><title>T08 synthetic</title><link>{BASE}</link><description>Fixture</description><item><title>Synthetic article</title><guid>t08-one</guid><link>{BASE}/article</link><description>Feed summary</description></item></channel></rss>'''
        elif self.path == '/article':
            kind = 'text/html'
            body = '<html><head><title>Synthetic article</title></head><body><article><h1>Synthetic article</h1><p>' + ('Synthetic extracted body. ' * 100) + '</p></article></body></html>'
        else:
            kind = 'text/html'
            count = {'/discover-zero': 0, '/discover-one': 1, '/discover-many': 3}.get(self.path, 0)
            links = ''.join(f'<link rel="alternate" type="application/rss+xml" title="Candidate {i}" href="{BASE}/feed/{i}">' for i in range(count))
            body = '<html><head>' + links + '</head><body>Discovery fixture</body></html>'
        data = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass


server = ThreadingHTTPServer(('0.0.0.0', 8443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/tls/cert.pem', '/fixture/tls/key.pem')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
