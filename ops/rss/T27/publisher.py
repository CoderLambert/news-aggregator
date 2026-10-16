"""Synthetic HTTPS publisher; request audit proves which process fetched content."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import time
from html import escape
BASE = 'https://publisher.example:8443'
CODE = 'def greet(name):\n    # keep  two spaces\n    return f"hello {name}"\n'
BODY = '<h1>T27 stored article</h1><p>Background collected content, ready before first visit.</p><pre><code>' + escape(CODE) + '</code></pre><table><thead><tr><th>Item</th><th>Value</th></tr></thead><tbody><tr><td>alpha</td><td>42</td></tr></tbody></table><p><img src="https://publisher.example:8443/pixel.png" alt="Synthetic image"></p>'

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_GET(self):
        with open('/fixture/audit/requests.jsonl', 'a') as handle:
            handle.write(json.dumps({'path': self.path, 'host': self.headers.get('Host'), 'time': time.time()}) + '\n')
        zero = self.headers.get('Host', '').startswith('zero.publisher.example')
        path = self.path
        if zero and path not in {'/', '/zero'}:
            self.send_error(404)
            return
        if path.startswith('/feed/'):
            name = path.rsplit('/', 1)[-1]
            title = {'public': 'T27 Public Code Table', 'private-a': 'T27 A ONLY SECRET',
                'private-b': 'T27 B ONLY SECRET', 'restricted': 'T27 Summary Restricted'}.get(name, 'T27 Connected ' + name)
            html = '<p>Restricted summary only.</p>' if name == 'restricted' else BODY
            body = f'<rss version="2.0"><channel><title>{title}</title><link>{BASE}</link><description>Synthetic</description><item><title>{title}</title><guid>t27-{name}</guid><link>{BASE}/article/{name}</link><pubDate>Fri, 16 Oct 2026 00:00:00 GMT</pubDate><description><![CDATA[{html}]]></description></item></channel></rss>'
            kind = 'application/rss+xml'
        elif path.startswith('/article/'):
            body = '<html><head><title>T27 canonical article</title></head><body><article>' + BODY + '<p>' + ('Expanded synthetic content. ' * 80) + '</p></article></body></html>'
            kind = 'text/html'
        elif path in {'/', '/zero', '/one', '/many'}:
            count = 0 if zero else {'/one': 1, '/many': 3}.get(path, 0)
            body = '<html><head>' + ''.join(f'<link rel="alternate" type="application/rss+xml" title="Candidate {i}" href="{BASE}/feed/discovered-{i}">' for i in range(count)) + '</head><body>Discovery fixture</body></html>'
            kind = 'text/html'
        else:
            self.send_error(404)
            return
        raw = body.encode()
        self.send_response(200); self.send_header('Content-Type', kind); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

server = ThreadingHTTPServer(('0.0.0.0', 8443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/tls/cert.pem', '/fixture/tls/key.pem')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
