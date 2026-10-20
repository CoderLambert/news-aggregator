"""Synthetic RSS/article and failure endpoints. No arbitrary target fetches."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

STATE = {"version": 1, "requests": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/state":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", 0))
        if size > 256:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(size))
        STATE["version"] = int(data["version"])
        STATE["requests"] = []
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        # Record presence only: never echo synthetic Authorization values.
        STATE["requests"].append({"path": self.path, "auth": bool(self.headers.get("Authorization"))})
        if self.path == "/state":
            body, kind = json.dumps(STATE), "application/json"
        elif self.path == "/redirect-other":
            self.send_response(302)
            self.send_header("Location", "http://fixture-other:8000/feed")
            self.end_headers()
            return
        elif self.path == "/error":
            self.send_error(503, "Synthetic failure")
            return
        elif self.path == "/invalid":
            body, kind = "<rss>broken", "application/rss+xml"
        elif self.path.startswith("/article/"):
            number = self.path.rsplit("/", 1)[1]
            paragraph = f"Synthetic article {number} version {STATE['version']}. " * 80
            body, kind = f"<html><head><title>T00 article</title></head><body><article><h1>T00 article</h1><p>{paragraph}</p></article></body></html>", "text/html"
        elif self.path == "/date-feed":
            dates = [('old', '2026-10-13T23:59:59Z'), ('boundary', '2026-10-14T00:00:00Z'),
                     ('offset-old', '2026-10-14T07:59:59+08:00'),
                     ('offset-boundary', '2026-10-14T08:00:00+08:00'), ('new', '2026-10-20T00:00:00Z')]
            items = ''.join(f'<entry><title>Date {key}</title><id>date-{key}</id>'
                f'<link href="http://fixture:8000/article/date-{key}"/>'
                f'<published>{date}</published><updated>{date}</updated><summary>Summary</summary></entry>'
                for key, date in dates)
            body, kind = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Frozen boundary</title>'
                          '<id>urn:date-test</id>' + items + '</feed>'), 'application/atom+xml'
        elif self.path == "/feed":
            items = "".join(f"<item><title>Item {i}</title><guid>t00-{i}</guid><link>http://fixture:8000/article/{i}</link><description>Feed summary {i}</description><pubDate>Mon, 01 Jan 2001 00:00:00 GMT</pubDate></item>" for i in range(1, 9))
            body, kind = f"<rss version='2.0'><channel><title>T00 synthetic</title><link>http://fixture:8000</link><description>Contract fixture</description>{items}</channel></rss>", "application/rss+xml"
        else:
            self.send_error(404)
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
