#!/usr/bin/env python3
"""Run T09 through an isolated LiteLLM Proxy and synthetic tool-calling upstream."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / 'backend'
T02_STUBS = Path('/tmp/byok-t02-test-stubs')
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'byok'))
import run_t02_proxy_local as gateway_runner  # noqa: E402


SYNTHETIC_UPSTREAM = r'''from __future__ import annotations
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
PROVIDER_KEYS = {}
PROJECT_KEYS = set()
MASTER_KEY = ""
RECORDS = []

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

class Handler(BaseHTTPRequestHandler):
    server_version = "T09-Synthetic-Upstream"
    def log_message(self, _format, *_args):
        return
    def send_json(self, status, body):
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
    def do_GET(self):
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok"})
        elif self.path == "/test/records":
            with LOCK:
                rows = list(RECORDS)
            self.send_json(200, {"records": rows})
        else:
            self.send_json(404, {"error": "not_found"})
    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "invalid_request"})
            return
        if self.path == "/test/expectations":
            hashes = payload.get("provider_key_hashes", {})
            projects = payload.get("project_key_hashes", [])
            master_hash = payload.get("master_key_hash", "")
            if not isinstance(hashes, dict) or not isinstance(projects, list) or not isinstance(master_hash, str):
                self.send_json(400, {"error": "invalid_expectations"})
                return
            with LOCK:
                PROVIDER_KEYS.clear()
                PROVIDER_KEYS.update({value: label for label, value in hashes.items()})
                PROJECT_KEYS.clear()
                PROJECT_KEYS.update(projects)
                global MASTER_KEY
                MASTER_KEY = master_hash
                RECORDS.clear()
            self.send_json(200, {"registered": len(hashes) + len(projects) + 1})
            return
        if self.path not in {"/v1/chat/completions", "/chat/completions"}:
            self.send_json(404, {"error": "not_found"})
            return
        authorization = self.headers.get_all("authorization", [])
        bearer = authorization[0][7:] if authorization and authorization[0].lower().startswith("bearer ") else ""
        provider_label = ""
        with LOCK:
            provider_label = PROVIDER_KEYS.get(digest(bearer), "") if bearer else ""
            prompt_marker = any(
                isinstance(item, dict)
                and isinstance(item.get("content"), str)
                and item["content"].startswith("T09_PROXY_LOCAL_PRIVATE_PROMPT_")
                for item in payload.get("messages", [])
            )
            tool_result_seen = any(
                isinstance(item, dict) and item.get("role") == "tool"
                for item in payload.get("messages", [])
            )
            tool_names = [
                item.get("function", {}).get("name", "")
                for item in payload.get("tools", [])
                if isinstance(item, dict) and isinstance(item.get("function"), dict)
            ]
            RECORDS.append({
                "ordinal": len(RECORDS) + 1,
                "provider_label": provider_label or "unknown",
                "authorization_class": "provider_key" if provider_label else "other_or_missing",
                "authorization_header_count": len(authorization),
                "model": payload.get("model"),
                "tool_names": tool_names,
                "tool_result_seen": tool_result_seen,
                "prompt_marker_seen": prompt_marker,
                "body_api_key_present": "api_key" in payload,
                "project_key_forwarded": digest(bearer) in PROJECT_KEYS if bearer else False,
                "master_key_forwarded": bool(MASTER_KEY and digest(bearer) == MASTER_KEY),
            })
            ordinal = len(RECORDS)
        if not provider_label:
            self.send_json(401, {"error": {"message": "synthetic provider credential rejected"}})
            return
        if tool_result_seen:
            message = {
                "role": "assistant",
                "content": "## T09 controlled research report\n\nThe isolated upstream completed after one persisted tool result.",
            }
            finish_reason = "stop"
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_t09_proxy_local_1",
                    "type": "function",
                    "function": {
                        "name": "search_news",
                        "arguments": "{\"query\":\"controlled news result\",\"mode\":\"keyword\"}",
                    },
                }],
            }
            finish_reason = "tool_calls"
        self.send_json(200, {
            "id": "chatcmpl-t09-" + str(ordinal),
            "object": "chat.completion",
            "created": 1791763200,
            "model": payload.get("model", "test-model"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26},
        })

ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _run_test(gateway_root: Path) -> dict:
    for dotenv in (REPO_ROOT / '.env', BACKEND_DIR / '.env'):
        if dotenv.exists():
            raise ValueError('dotenv_present_test_refused')
    if (gateway_root / '.env').exists() or (gateway_root / 'ops' / 'shared-litellm-proxy' / '.env').exists():
        raise ValueError('gateway_dotenv_present_test_refused')
    if not (T02_STUBS / 'chromadb.py').is_file():
        raise ValueError('isolated_test_stub_missing')

    original = gateway_runner._validate_gateway_source(gateway_root)
    project = f'byok-t09-{secrets.token_hex(4)}'
    provider_key = 'sk-t09-provider-' + secrets.token_hex(20)
    master_key = 'sk-' + secrets.token_hex(32)
    secret_values = {
        'postgres_password': secrets.token_hex(32),
        'litellm_master_key': master_key,
        'litellm_salt_key': secrets.token_hex(32),
    }
    summary = {
        'scope': 'T09_PROXY_LOCAL_SYNTHETIC_ONLY',
        'provider_real': 'NOT_RUN',
        'gateway_source': str(gateway_root),
        'model_alias': 'news.deepseek-flash',
        'tool_calls': 'NOT_RUN',
        'upstream_request_count': 0,
        'provider_key_only_at_upstream': False,
        'secret_leak_check': 'NOT_RUN',
    }

    with tempfile.TemporaryDirectory(prefix=f'{project}-') as temporary:
        temp = Path(temporary)
        isolated_gateway = temp / 'gateway'
        proxy_source = isolated_gateway / 'ops' / 'shared-litellm-proxy'
        shutil.copytree(original[0].parent, proxy_source)
        (proxy_source / 'tests' / 'upstream.py').write_text(SYNTHETIC_UPSTREAM, encoding='utf-8')
        compose_files = [proxy_source / 'compose.yaml', proxy_source / 'compose.test.yaml']

        secrets_dir = temp / 'secrets'
        secrets_dir.mkdir(mode=0o700)
        secret_paths = {}
        for name, value in secret_values.items():
            path = secrets_dir / name
            path.write_text(value, encoding='utf-8')
            path.chmod(0o600)
            secret_paths[name] = path

        env_file = temp / 'compose.env'
        env_values = {
            'POSTGRES_DB': 'litellm',
            'POSTGRES_USER': 'litellm',
            'POSTGRES_PASSWORD_FILE': str(secret_paths['postgres_password']),
            'LITELLM_MASTER_KEY_FILE': str(secret_paths['litellm_master_key']),
            'LITELLM_SALT_KEY_FILE': str(secret_paths['litellm_salt_key']),
            'GATEWAY_BACKEND_NETWORK': f'{project}-backend',
            'GATEWAY_EGRESS_NETWORK': f'{project}-provider-egress',
            'PROVIDER_EGRESS_INTERNAL': 'true',
            'T00G_TEST_PROVIDER_KEY_HASHES': json.dumps({'t09-provider': _sha(provider_key)}, separators=(',', ':')),
        }
        env_file.write_text(''.join(f'{name}={value}\n' for name, value in env_values.items()), encoding='utf-8')
        env_file.chmod(0o600)

        attempted_start = False
        try:
            attempted_start = True
            up = gateway_runner._compose(
                compose_files, project, env_file,
                '--profile', 'test', 'up', '-d', '--wait', '--wait-timeout', '240', timeout=300,
            )
            if up.returncode != 0:
                raise ValueError('proxy_stack_start_failed')
            proxy_ids = gateway_runner._compose(compose_files, project, env_file, 'ps', '-q', 'proxy', timeout=30)
            container_id = proxy_ids.stdout.decode('utf-8', errors='replace').strip()
            if proxy_ids.returncode != 0 or not container_id:
                raise ValueError('proxy_container_lookup_failed')
            inspected = gateway_runner._run(['docker', 'inspect', container_id], cwd=compose_files[0].parent, timeout=30)
            if inspected.returncode != 0:
                raise ValueError('proxy_container_inspect_failed')
            try:
                container = json.loads(inspected.stdout)[0]
                network = container['NetworkSettings']['Networks'][f'{project}-backend']
                bridge_ip = ipaddress.ip_address(network['IPAddress'])
            except (IndexError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ValueError('proxy_gateway_network_lookup_failed') from None
            if not bridge_ip.is_private:
                raise ValueError('proxy_gateway_network_not_private')
            proxy_url = f'http://{bridge_ip.compressed}:4000'
            if not gateway_runner._wait_ready(proxy_url + '/health/readiness'):
                raise ValueError('proxy_readiness_timeout')

            key_status, key_response = gateway_runner._json_request(
                proxy_url + '/key/generate',
                method='POST',
                payload={
                    'models': ['news.deepseek-flash'],
                    'key_alias': 't09-local-test',
                    'metadata': {'project': 't09-local-test'},
                    'max_budget': 1.0,
                    'budget_duration': '1d',
                    'rpm_limit': 10,
                    'tpm_limit': 120000,
                    'max_parallel_requests': 1,
                    'duration': '1d',
                },
                bearer=master_key,
            )
            project_key = key_response.get('key') if key_status == 200 and isinstance(key_response, dict) else ''
            if not isinstance(project_key, str) or not project_key.startswith('sk-'):
                raise ValueError('project_virtual_key_provision_failed')

            setup_status, _setup = gateway_runner._client_request(
                compose_files, project, env_file,
                target='test-upstream',
                path='/test/expectations',
                method='POST',
                payload={
                    'provider_key_hashes': {'t09-provider': _sha(provider_key)},
                    'project_key_hashes': [_sha(project_key)],
                    'master_key_hash': _sha(master_key),
                },
            )
            if setup_status != 200:
                raise ValueError('synthetic_upstream_setup_failed')

            test_env = {
                'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                'HOME': str(temp / 'home'),
                'PYTHONPATH': os.pathsep.join((str(T02_STUBS), str(BACKEND_DIR))),
                'DJANGO_ENV': 'development',
                'DJANGO_SECRET_KEY': 't09-proxy-local-synthetic-django-secret-only',
                'AI_BYOK_ENABLED': '1',
                'AI_CONNECTION_ENCRYPTION_KEY': base64.urlsafe_b64encode(b'0123456789abcdef0123456789abcdef').decode('ascii').rstrip('='),
                'AI_CONNECTION_ENCRYPTION_KEY_ID': 't09-proxy-local-v1',
                'PUBLIC_SITE_MODE': 'full',
                'PUBLIC_AI_ENABLED': '0',
                'PUBLIC_SIGNUP_ENABLED': '0',
                'CHATGPT_AUTH_MODE': 'local_oss',
                'CHATGPT_PLAN_USAGE_ENABLED': '0',
                'T09_PROXY_LOCAL': '1',
                'T09_SYNTHETIC_PROVIDER_KEY': provider_key,
                'AI_BYOK_GATEWAY_URL': proxy_url,
                'AI_BYOK_GATEWAY_PROJECT_KEY': project_key,
                'DJANGO_DB_PATH': str(temp / 't09-proxy-local.sqlite3'),
                'CHROMA_DATA_DIR': str(temp / 'chroma'),
                'TTS_CACHE_DIR': str(temp / 'tts-cache'),
                'XDG_CACHE_HOME': str(temp / 'xdg-cache'),
            }
            for directory_name in ('home', 'chroma', 'tts-cache', 'xdg-cache'):
                (temp / directory_name).mkdir(mode=0o700)

            test = gateway_runner._run(
                [sys.executable, '-m', 'pytest', '-q', 'api/tests/test_research_byok_proxy_local.py'],
                cwd=BACKEND_DIR,
                env=test_env,
                timeout=180,
            )
            if test.returncode != 0:
                diagnostic = test.stdout.decode('utf-8', errors='replace') + test.stderr.decode('utf-8', errors='replace')
                for value in [provider_key, project_key, master_key, *secret_values.values()]:
                    diagnostic = diagnostic.replace(value, '[redacted]')
                raise ValueError('django_proxy_integration_failed:' + diagnostic[-3500:])
            test_output = test.stdout.decode('utf-8', errors='replace')
            if '1 passed' not in test_output:
                raise ValueError('django_proxy_integration_not_executed')

            records_status, records_payload = gateway_runner._client_request(
                compose_files, project, env_file, target='test-upstream', path='/test/records',
            )
            rows = records_payload.get('records', []) if records_status == 200 else []
            summary['upstream_request_count'] = len(rows) if isinstance(rows, list) else 0
            summary['tool_calls'] = 'PASS' if (
                isinstance(rows, list)
                and len(rows) == 2
                and rows[0].get('provider_label') == 't09-provider'
                and rows[0].get('authorization_class') == 'provider_key'
                and 'search_news' in rows[0].get('tool_names', [])
                and rows[0].get('prompt_marker_seen') is True
                and rows[1].get('provider_label') == 't09-provider'
                and rows[1].get('authorization_class') == 'provider_key'
                and rows[1].get('tool_result_seen') is True
            ) else 'FAIL'
            summary['provider_key_only_at_upstream'] = (
                isinstance(rows, list)
                and len(rows) == 2
                and all(row.get('authorization_header_count') == 1 for row in rows)
                and all(row.get('authorization_class') == 'provider_key' for row in rows)
                and not any(row.get('body_api_key_present') for row in rows)
                and not any(row.get('project_key_forwarded') or row.get('master_key_forwarded') for row in rows)
            )
            leaked = any(
                value and value in json.dumps(rows, ensure_ascii=True)
                for value in [provider_key, project_key, master_key, *secret_values.values()]
            )
            summary['secret_leak_check'] = 'FAIL' if leaked else 'PASS'
            if summary['tool_calls'] != 'PASS' or not summary['provider_key_only_at_upstream'] or leaked:
                raise ValueError('research_proxy_boundary_or_tool_flow_failed')

            logs = gateway_runner._compose(compose_files, project, env_file, 'logs', '--no-color', 'proxy', 'test-upstream', timeout=30)
            log_text = logs.stdout.decode('utf-8', errors='replace') + logs.stderr.decode('utf-8', errors='replace')
            if any(value and value in log_text for value in [provider_key, project_key, master_key, *secret_values.values()]):
                summary['secret_leak_check'] = 'FAIL'
                raise ValueError('secret_found_in_local_proxy_logs')
            summary['provider_real'] = 'NOT_RUN'
            summary['status'] = 'PASS'
            return summary
        finally:
            if attempted_start:
                down = gateway_runner._compose(
                    compose_files, project, env_file, '--profile', 'test', 'down',
                    '--volumes', '--remove-orphans', timeout=120,
                )
                summary['cleanup'] = 'PASS' if down.returncode == 0 else 'FAIL'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-worktree', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary = _run_test(args.gateway_worktree.resolve())
    except Exception as error:
        summary = {
            'scope': 'T09_PROXY_LOCAL_SYNTHETIC_ONLY',
            'status': 'FAIL',
            'error_code': str(error) if isinstance(error, ValueError) else 'runner_error',
            'provider_real': 'NOT_RUN',
        }
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
        return 1
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary.get('status') == 'PASS' and summary.get('cleanup') == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
