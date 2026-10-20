"""Synthetic redirect target; never parses a feed or fetches another URL."""
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header('Location','http://127.0.0.1:8080/v1/me')
        self.end_headers()
    def log_message(self,*args): pass
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
