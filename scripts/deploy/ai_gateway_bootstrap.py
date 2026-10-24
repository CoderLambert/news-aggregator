#!/usr/bin/env python3
"""Bootstrap a local LiteLLM project key from inside its private namespace."""

import json
from pathlib import Path
import re
import urllib.error
import urllib.request


PENDING = 'pending-local-bootstrap'
MODELS = (
    'openai/*', 'anthropic/*', 'deepseek/*', 'gemini/*', 'dashscope/*',
    'zai/*', 'moonshot/*', 'mistral/*', 'groq/*', 'xai/*', 'openrouter/*',
    'newshub/*',
)


def read_secret(path):
    value = Path(path).read_text(encoding='utf-8').strip()
    if not value:
        raise RuntimeError('required bootstrap secret is empty')
    return value


def request_json(path, *, method='GET', payload=None, token):
    data = None if payload is None else json.dumps(payload, separators=(',', ':')).encode()
    request = urllib.request.Request(
        'http://127.0.0.1:4000' + path, data=data, method=method,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + token},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15) as response:
        raw = response.read(1024 * 1024 + 1)
        if response.status < 200 or response.status >= 300 or len(raw) > 1024 * 1024:
            raise RuntimeError('gateway bootstrap returned an invalid response')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError('gateway bootstrap returned invalid JSON')
    return value


def main():
    project_key = read_secret('/run/secrets/ai_byok_gateway_project_key')
    if project_key != PENDING:
        models = request_json('/v1/models', token=project_key)
        if not isinstance(models.get('data'), list):
            raise RuntimeError('existing gateway project key is invalid')
        print(json.dumps({'status': 'reused'}))
        return
    result = request_json('/key/generate', method='POST',
        token=read_secret('/run/secrets/litellm_master_key'), payload={
            'models': list(MODELS),
            'key_alias': 'newshub-local-main',
            'allowed_routes': ['llm_api_routes', '/newshub/models/discover'],
            'max_budget': 5.0, 'budget_duration': '1d', 'rpm_limit': 60,
            'tpm_limit': 120000, 'max_parallel_requests': 4, 'duration': '90d',
        })
    key = result.get('key')
    if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,256}', key):
        raise RuntimeError('gateway did not return a valid project key')
    print(json.dumps({'status': 'created', 'key': key}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
        raise SystemExit('ai-gateway-bootstrap: ' + str(error)) from None
