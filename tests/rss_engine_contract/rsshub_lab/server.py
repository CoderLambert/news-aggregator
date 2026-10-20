"""Fixed authenticated TLS lab gateway; synthetic Twitter and real public GitHub."""
import base64
from datetime import datetime,timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import ssl
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,HTTPRedirectHandler

AUTH='Basic '+base64.b64encode(b'synthetic-gateway:synthetic-gateway-only').decode()
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.headers.get('Authorization')!=AUTH:
            self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Synthetic RSSHub"');self.end_headers();return
        if self.path=='/twitter/user/elonmusk':
            date=format_datetime(datetime.now(timezone.utc))
            body=f'<rss version="2.0"><channel><title>Synthetic Twitter timeline</title><link>https://example.com/</link><description>Isolated test only</description><item><title>Synthetic public timeline item</title><link>https://example.com/public-timeline</link><guid>rsshub-synthetic-one</guid><pubDate>{date}</pubDate><description>Public synthetic feed summary.</description></item></channel></rss>'.encode()
            status=200
        elif self.path=='/github/issue/DIYgod/RSSHub/open':
            try:
                with build_opener(NoRedirect).open(Request('http://rsshub:1200/github/issue/DIYgod/RSSHub/open'),timeout=25) as response:
                    body=response.read(2*1024*1024+1);status=response.status
                    if len(body)>2*1024*1024:body=b'bounded lab response';status=502
            except (HTTPError,URLError,TimeoutError):body=b'RSSHub public route unavailable';status=502
        else:body=b'Unsupported lab route';status=404
        self.send_response(status);self.send_header('Content-Type','application/rss+xml');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('0.0.0.0',443),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain('/certs/ca.pem','/certs/key.pem')
server.socket=context.wrap_socket(server.socket,server_side=True);server.serve_forever()
