"""Synthetic-only compatible Chat service; records labels, never credentials."""
import json
import gzip
from http.server import BaseHTTPRequestHandler
import socket
import threading
import time


def handler_type(provider_keys):
    records, lock = [], threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        cancel_closed = threading.Event()
        stream_override = None
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            auth = self.headers.get('Authorization')
            label = 'none' if auth is None else next((label for label, key in provider_keys.items()
                                                      if auth == 'Bearer ' + key), 'unapproved')
            model = body.get('model')
            with lock:
                records.append({'model': model, 'stream': body.get('stream') is True, 'auth_label': label,
                                'path': self.path, 'json_object_mode': body.get('response_format') == {'type': 'json_object'}})
            if model == 'nh-redirect':
                self.send_response(307)
                self.send_header('Location', '/redirect-target')
                self.end_headers()
                return
            if model == 'nh-truncated':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '1000')
                self.end_headers()
                self.wfile.write(b'{')
                return
            if model == 'nh-reset':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if model == 'nh-cancel':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                wire = b'data: {"choices":[{"index":0,"delta":{"content":"synthetic delta"},"finish_reason":null}]}\n\n'
                try:
                    for _ in range(400):
                        self.wfile.write(wire)
                        self.wfile.flush()
                        time.sleep(0.01)
                except (BrokenPipeError, ConnectionResetError):
                    self.cancel_closed.set()
                return
            choice = {'index': 0, 'message': {'role': 'assistant', 'content': 'synthetic completed answer'},
                      'finish_reason': 'stop'}
            result = {'id': 'chatcmpl-synthetic', 'object': 'chat.completion', 'model': model,
                      'created': 1, 'choices': [choice],
                      'usage': {'prompt_tokens': 2, 'completion_tokens': 2, 'total_tokens': 4}}
            if body.get('stream'):
                mode = type(self).stream_override or model
                def chunk(delta, reason=None):
                    return ('data: ' + json.dumps({'id': result['id'], 'object': 'chat.completion.chunk',
                            'model': model, 'created': 1, 'choices': [{'index': 0, 'delta': delta,
                            'finish_reason': reason}]}) + '\n\n').encode()
                wire = chunk({'role': 'assistant', 'content': 'synthetic delta'})
                if mode != 'nh-no-stop':
                    wire += chunk({}, 'length' if mode == 'nh-length' else 'stop')
                if mode == 'nh-error':
                    wire += b'data: {"error":{"message":"synthetic"}}\n\n'
                if mode != 'nh-eof':
                    wire += b'data: [DONE]\n\n'
                if mode == 'nh-double-done':
                    wire += b'data: [DONE]\n\n'
                content_type = 'text/event-stream'
            else:
                if model == 'nh-refusal':
                    choice['message']['refusal'] = 'synthetic refusal with partial text'
                if model == 'nh-no-finish':
                    choice.pop('finish_reason')
                if model == 'nh-length':
                    choice['finish_reason'] = 'length'
                if model == 'nh-tools' or body.get('tools') and body['tools'][0].get('function', {}).get('name') == 'byok_probe':
                    choice.update(finish_reason='tool_calls', message={'role': 'assistant', 'content': None,
                                  'tool_calls': [{'id': 'call-synthetic', 'type': 'function',
                                                 'function': {'name': 'byok_probe', 'arguments': '{"ok":true}'}}]})
                wire = json.dumps(result).encode()
                if model == 'nh-duplicate':
                    wire = wire.replace(b'"finish_reason": "stop"', b'"finish_reason": null,"finish_reason": "stop"')
                content_type = 'application/json'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            if model == 'nh-compressed':
                wire = gzip.compress(wire)
                self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

    return Handler, records
