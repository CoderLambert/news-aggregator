"""Synthetic immutable HTTPS feed; publisher network is used by Miniflux only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
BASE = 'https://publisher.example:8443'

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_GET(self):
        if self.path != '/feed':
            self.send_error(404)
            return
        items = ''.join(f'<item><title>Synthetic {i}</title><guid>t09-{i}</guid><link>{BASE}/article-{i}</link>'
            f'<pubDate>Wed, 01 Jan 2020 00:00:00 GMT</pubDate><description><![CDATA[<p>Body for article {i}.</p>]]></description></item>' for i in range(4))
        body = f'<rss version="2.0"><channel><title>T09</title><link>{BASE}</link><description>Fixture</description>{items}</channel></rss>'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/rss+xml')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

server = ThreadingHTTPServer(('0.0.0.0', 8443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/tls/cert.pem', '/fixture/tls/key.pem')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
