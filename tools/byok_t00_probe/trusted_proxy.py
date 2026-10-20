"""Real pinned Proxy + synthetic compatible upstream; no real-provider option."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading

from local_runtime import LocalProxy
from protocol_cases import openai_client
from trusted_upstream import handler_type


def run(python):
    keys = {owner: 'synthetic-' + secrets.token_hex(20) for owner in ('owner-a', 'owner-b')}
    Handler, records = handler_type(keys)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    item = {'profile_id': 'synthetic_compatible', 'version': 1, 'provider_id': 'ollama',
            'display_name': 'Synthetic only', 'protocol_family': 'chat_completions_v1',
            'api_base': url + '/v1', 'network_zone': 'same_host', 'allowed_ips': ['127.0.0.1'],
            'auth_modes': ['none', 'api_key'], 'allowed_user_ids': [7, 8], 'enabled': True}
    checks = []
    clients = []

    def check(name, condition, **facts):
        checks.append({'case': name, 'status': 'PASS' if condition else 'FAIL', 'facts': facts})

    try:
        with LocalProxy(python, url, trusted_profiles=[item]) as proxy:
            prefix = proxy.trusted_profiles[0]['route_prefix']
            for tenant in ('tenant-a', 'tenant-b'):
                clients.append(openai_client(proxy.project_keys[tenant], proxy.url + '/v1', timeout=20))

            def call(model, *, stream=False, key=None, owner=7, auth_mode=None, client=None, **extra):
                client = client or clients[0]
                arguments = {'model': prefix + '/' + model, 'messages': [{'role': 'user', 'content': 'synthetic'}],
                             'stream': stream, 'max_tokens': 16, 'extra_body': {'api_key': key,
                             'metadata': {'newshub_owner_id': owner,
                                          'newshub_auth_mode': auth_mode or ('none' if key is None else 'api_key')}, **extra}}
                reasons = []
                try:
                    result = client.chat.completions.create(**arguments)
                    if stream:
                        with result:
                            for chunk in result:
                                reasons.extend(choice.finish_reason for choice in chunk.choices if choice.finish_reason)
                        return {'success': True, 'reasons': reasons}
                    return {'success': True, 'reasons': [result.choices[0].finish_reason]}
                except Exception as error:
                    return {'success': False, 'status_code': getattr(error, 'status_code', None),
                            'error_type': type(error).__name__, 'reasons': reasons}

            for key, owner, expected in ((None, 7, 'none'), (keys['owner-a'], 7, 'owner-a'), (keys['owner-b'], 8, 'owner-b')):
                for stream in (False, True):
                    before = len(records)
                    result = call('org/model:cloud', key=key, owner=owner, stream=stream)
                    rows = records[before:]
                    check(f'auth_{expected}_stream_{stream}', result['success'] and result['reasons'] == ['stop']
                          and len(rows) == 1 and rows[0]['auth_label'] == expected
                          and rows[0]['model'] == 'org/model:cloud', result=result, upstream_count=len(rows))
            for model, stream in (('nh-no-finish', False), ('nh-refusal', False), ('nh-duplicate', False), ('nh-truncated', False),
                                   ('nh-redirect', False), ('nh-reset', False), ('nh-eof', True),
                                   ('nh-no-stop', True), ('nh-length', True), ('nh-error', True), ('nh-double-done', True),
                                   ('nh-compressed', False), ('nh-compressed', True)):
                before = len(records)
                result = call(model, stream=stream)
                check(model + str(stream), not result['success'] and 'stop' not in result['reasons']
                      and len(records) - before == 1, result=result, upstream_count=len(records) - before)
            for label, fields in (('owner_acl', {'owner': 9}), ('key_none_forged', {'key': keys['owner-a'], 'auth_mode': 'none'}),
                                   ('key_missing', {'auth_mode': 'api_key'}), ('url_override', {'api_base': 'http://127.0.0.1:1'})):
                before = len(records)
                result = call('org/model:cloud', **fields)
                check(label, result['success'] is False and result.get('status_code') in (400, 401)
                      and len(records) == before, result=result, upstream_count=len(records) - before)
            for label, fields in (
                ('media_download', {'messages': [{'role': 'user', 'content': [{'type': 'file', 'file': {
                    'file_id': 'https://unapproved.invalid/document.pdf'}}]}]}),
                ('builtin_network_tool', {'tools': [{'type': 'web_search'}]}),
            ):
                before = len(records)
                result = call('org/model:cloud', **fields)
                check(label, not result['success'] and len(records) == before, result=result,
                      upstream_count=len(records) - before)
            before = len(records)
            canceled = clients[0].chat.completions.create(
                model=prefix + '/nh-cancel', messages=[{'role': 'user', 'content': 'synthetic'}], stream=True,
                extra_body={'api_key': None, 'metadata': {'newshub_owner_id': 7, 'newshub_auth_mode': 'none'}})
            reasons = []
            with canceled:
                for chunk in canceled:
                    reasons.extend(choice.finish_reason for choice in chunk.choices if choice.finish_reason)
                    if any(choice.delta.content for choice in chunk.choices):
                        break
            check('cancel_closes_producer', Handler.cancel_closed.wait(3) and not reasons
                  and len(records) - before == 1, upstream_count=len(records) - before,
                  observed_terminal=reasons)
            result = call('nh-tools')
            check('one_shot_function_tool_terminal', result['success'] and result['reasons'] == ['tool_calls'],
                  result=result)
            before = len(records)
            result = call('org/model:cloud', response_format={'type': 'json_object'})
            check('bounded_json_object_format', result['success'] and len(records) - before == 1
                  and records[-1]['json_object_mode'], result=result, upstream_count=len(records) - before)
            before = len(records)
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(call, 'shared/model:tag', key=keys['owner-a'], owner=7)
                b = pool.submit(call, 'shared/model:tag', key=keys['owner-b'], owner=8, client=clients[1])
                results = [a.result(), b.result()]
            check('same_model_concurrent_credentials', all(result['success'] for result in results)
                  and sorted(row['auth_label'] for row in records[before:]) == ['owner-a', 'owner-b'],
                  upstream_count=len(records) - before, results=results)
            revoked = {**item, 'enabled': False}
            replacement = proxy.runtime / 'trusted-endpoints.next.json'
            replacement.write_text(json.dumps([revoked]))
            os.replace(replacement, proxy.runtime / 'trusted-endpoints.json')
            before = len(records)
            result = call('org/model:cloud')
            check('revoked_manifest', not result['success'] and len(records) == before,
                  result=result, upstream_count=len(records) - before)
        check('proxy_cleanup', proxy.cleanup_complete)
    finally:
        for client in clients:
            client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return {'scope': 'PINNED_PROXY_COMPATIBLE_SYNTHETIC_ONLY', 'PROVIDER_REAL': 'NOT_RUN',
            'checks': checks, 'passed': sum(check['status'] == 'PASS' for check in checks),
            'failed': sum(check['status'] != 'PASS' for check in checks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy-python', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        report = run(args.proxy_python)
    except Exception as error:
        report = {'scope': 'PINNED_PROXY_COMPATIBLE_SYNTHETIC_ONLY', 'passed': 0, 'failed': 1,
                  'runner_error_type': type(error).__name__}
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'checks'}))
    return int(report['failed'] != 0)


if __name__ == '__main__':
    raise SystemExit(main())
