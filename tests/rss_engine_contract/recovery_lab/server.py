from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
from datetime import datetime, timezone
from email.utils import format_datetime
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        if self.path == '/feed':
            body=b'<rss version="2.0"><channel><title>Synthetic recovery</title><link>https://fixture.example/</link><description>Isolated</description></channel></rss>'
        elif self.path == '/self-service':
            published=format_datetime(datetime.now(timezone.utc))
            body=f'<rss version="2.0"><channel><title>Synthetic reader feed</title><link>https://fixture.example/</link><description>Isolated acceptance</description><item><title>Public fixture article</title><link>https://fixture.example/article</link><guid>synthetic-public-article</guid><pubDate>{published}</pubDate><description>Only a public feed summary.</description></item></channel></rss>'.encode()
        else:
            body=b'<rss>invalid synthetic response'
        self.send_response(200)
        self.send_header('Content-Type','application/rss+xml')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)
server=ThreadingHTTPServer(('0.0.0.0',443),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/certs/ca.pem','/certs/key.pem')
server.socket=context.wrap_socket(server.socket,server_side=True)
server.serve_forever()
