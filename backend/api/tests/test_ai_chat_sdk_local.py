from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from api.services.ai_chat import ArticleChatError, ArticleChatExecution, stream_article_chat
from api.services.ai_execution import ExecutionSnapshot


SYNTHETIC_PROJECT_KEY = 'sk-' + ('p' * 32)
SYNTHETIC_PROVIDER_KEY = 'sk-t04-sdk-local-provider-key-never-real'


class _ResponsesHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    events = []
    requests = []

    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get('content-length', '0'))
        body = self.rfile.read(length)
        type(self).requests.append({
            'path': self.path,
            'authorization': self.headers.get('authorization'),
            'body': json.loads(body),
        })
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.send_header('cache-control', 'no-cache')
        self.end_headers()
        for event in type(self).events:
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode('utf-8'))
            self.wfile.flush()


@pytest.fixture
def sdk_responses_server():
    _ResponsesHandler.requests = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), _ResponsesHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _execution(gateway_url):
    snapshot = ExecutionSnapshot(
        user_id=1,
        task_kind='article_qa',
        selected_by_task_kind='explicit',
        model_config_id='00000000-0000-0000-0000-000000000001',
        connection_id='00000000-0000-0000-0000-000000000002',
        provider_id='deepseek',
        endpoint_profile='deepseek_default',
        endpoint_profile_version=1,
        credential_epoch=1,
        config_revision=1,
        model_id='deepseek-flash',
        digest='sdk-local-snapshot',
    )
    return ArticleChatExecution(
        snapshot=snapshot,
        gateway_url=gateway_url,
        project_key=SYNTHETIC_PROJECT_KEY,
        provider_key=SYNTHETIC_PROVIDER_KEY,
        model_alias='news.deepseek-flash',
        model_source={'provider': 'DeepSeek', 'model': 'DeepSeek V4.1 Flash'},
    )


def _completed(text='SDK local answer'):
    return {
        'type': 'response.completed',
        'response': {
            'id': 'resp_t04_sdk',
            'object': 'response',
            'created_at': 1,
            'status': 'completed',
            'model': 'deepseek-flash',
            'output': [{
                'id': 'msg_t04_sdk',
                'type': 'message',
                'role': 'assistant',
                'status': 'completed',
                'content': [{'type': 'output_text', 'text': text, 'annotations': []}],
            }],
        },
    }


def test_official_openai_sdk_streams_responses_and_sends_only_fixed_route_credentials(sdk_responses_server):
    _ResponsesHandler.events = [
        {'type': 'response.created', 'response': {'id': 'resp_t04_sdk', 'object': 'response', 'created_at': 1, 'status': 'in_progress'}},
        {'type': 'response.output_text.delta', 'item_id': 'msg_t04_sdk', 'output_index': 0, 'content_index': 0, 'delta': 'SDK local '},
        {'type': 'response.output_text.delta', 'item_id': 'msg_t04_sdk', 'output_index': 0, 'content_index': 0, 'delta': 'answer'},
        _completed(),
    ]
    execution = _execution(sdk_responses_server)
    chunks = list(stream_article_chat(
        execution,
        [{'role': 'system', 'content': 'synthetic system'}, {'role': 'user', 'content': 'synthetic question'}],
        execution_guard=lambda: None,
    ))

    assert chunks == ['SDK local ', 'answer']
    assert len(_ResponsesHandler.requests) == 1
    request = _ResponsesHandler.requests[0]
    assert request['path'] == '/v1/responses'
    assert request['authorization'] == f'Bearer {SYNTHETIC_PROJECT_KEY}'
    assert request['body']['model'] == 'news.deepseek-flash'
    assert request['body']['api_key'] == SYNTHETIC_PROVIDER_KEY
    assert request['body']['stream'] is True
    assert request['body']['store'] is False


def test_official_openai_sdk_treats_eof_without_completed_as_failure(sdk_responses_server):
    _ResponsesHandler.events = [
        {'type': 'response.output_text.delta', 'item_id': 'msg_t04_sdk', 'output_index': 0, 'content_index': 0, 'delta': 'partial'},
    ]

    with pytest.raises(ArticleChatError, match='incomplete_response'):
        list(stream_article_chat(
            _execution(sdk_responses_server),
            [{'role': 'user', 'content': 'synthetic question'}],
            execution_guard=lambda: None,
        ))
    assert len(_ResponsesHandler.requests) == 1
