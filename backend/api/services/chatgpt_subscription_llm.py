"""Fenced ChatGPT-plan Responses transport for owner-scoped business inference.

OAuth credentials stay in ``chatgpt_subscription``.  This module accepts only a
secret-free immutable connection/model snapshot and exposes normalized text
operations to business consumers.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

import requests

from api.models import ChatGPTSubscriptionConnection
from api.services import chatgpt_subscription as auth

MAX_OUTPUT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class SubscriptionExecutionSnapshot:
    user_id: int
    connection_id: str
    generation: int
    model_slug: str


def snapshot_for_connection(connection: ChatGPTSubscriptionConnection) -> SubscriptionExecutionSnapshot:
    if (not connection.is_active or connection.needs_reauth or not connection.connected
            or not connection.selected_model or not connection.user_id):
        raise auth.SubscriptionError('ChatGPT 订阅未连接或尚未选择模型。')
    return SubscriptionExecutionSnapshot(
        user_id=connection.user_id,
        connection_id=str(connection.pk),
        generation=connection.generation,
        model_slug=connection.selected_model,
    )


def snapshot_for_user(user) -> SubscriptionExecutionSnapshot:
    connection = auth.active_connection_for_user(user)
    if connection is None:
        raise auth.SubscriptionError('请先连接 ChatGPT 订阅账号。')
    return snapshot_for_connection(connection)


def verify_snapshot(snapshot: SubscriptionExecutionSnapshot) -> ChatGPTSubscriptionConnection:
    if (type(snapshot) is not SubscriptionExecutionSnapshot or type(snapshot.user_id) is not int
            or snapshot.user_id < 1 or not snapshot.connection_id or not snapshot.model_slug):
        raise auth.ConnectionChangedError('ChatGPT 订阅执行身份无效，请重新发起。')
    connection = ChatGPTSubscriptionConnection.objects.filter(
        pk=snapshot.connection_id, user_id=snapshot.user_id, is_active=True,
        generation=snapshot.generation, selected_model=snapshot.model_slug,
        needs_reauth=False,
    ).first()
    if connection is None or not connection.connected or not connection.user.is_active:
        raise auth.ConnectionChangedError('订阅账号、模型或授权已变化，请重新发起。')
    return connection


def _normalize_messages(messages) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise auth.SubscriptionError('模型请求缺少有效消息。')
    normalized = []
    for message in messages:
        role = message.get('role') if isinstance(message, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        if role not in {'system', 'developer', 'user', 'assistant'} or not isinstance(content, str):
            raise auth.SubscriptionError('模型请求包含格式无效的消息。')
        # ChatGPT plan usage rejects explicit system-role message items.
        normalized.append({'role': 'developer' if role == 'system' else role, 'content': content})
    return normalized


def _extract_response_text(response_data: dict) -> str:
    direct = response_data.get('output_text')
    if isinstance(direct, str) and direct:
        return direct
    pieces = []
    output = response_data.get('output', [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get('content', [])
            if not isinstance(content, list):
                continue
            for part in content:
                if (isinstance(part, dict) and part.get('type') == 'output_text'
                        and isinstance(part.get('text'), str)):
                    pieces.append(part['text'])
    return ''.join(pieces)


def _structured_error(status_code: int, response=None) -> auth.SubscriptionError:
    code = ''
    param = ''
    try:
        payload = response.json() if response is not None else {}
        detail = payload.get('error') if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            subscription_codes = {
                'subscription_sharing_usage_limit_exceeded',
                'subscription_sharing_usage_unavailable',
                'subscription_sharing_user_unavailable',
                'subscription_sharing_user_not_eligible',
                'subscription_sharing_unsupported_capability',
                'subscription_sharing_invalid_user',
            }
            recognized_codes = subscription_codes | {
                'model_not_found', 'invalid_model', 'unsupported_model',
                'unsupported_parameter', 'unsupported_value',
                'context_length_exceeded', 'input_too_long',
                'invalid_request_error', 'invalid_value', 'parameter_missing',
                'rate_limit_exceeded',
            }
            for candidate in (detail.get('code'), detail.get('type')):
                if isinstance(candidate, str) and candidate in recognized_codes:
                    code = candidate
                    break
            raw_param = detail.get('param')
            if isinstance(raw_param, str) and raw_param in {
                'model', 'input', 'stream', 'store', 'temperature',
                'text', 'max_output_tokens', 'max_tokens', 'tools', 'tool_choice',
            }:
                param = raw_param
    except Exception:
        pass
    if code == 'subscription_sharing_usage_limit_exceeded':
        return auth.SubscriptionError('ChatGPT 订阅共享额度已达上限，请在 ChatGPT 用量设置中查看。', code, 429)
    if code in {'subscription_sharing_usage_unavailable', 'subscription_sharing_user_unavailable'}:
        return auth.SubscriptionError('暂时无法确认 ChatGPT 订阅额度，请稍后明确重试。', code, 503)
    if code == 'subscription_sharing_user_not_eligible':
        return auth.SubscriptionError('当前 ChatGPT 账号或工作区不能使用订阅共享调用。', code, 403)
    if code == 'subscription_sharing_unsupported_capability':
        suffix = f'（{param}）' if param else ''
        return auth.SubscriptionError(f'当前订阅模型不支持此调用能力{suffix}。', code, 400)
    if code == 'subscription_sharing_invalid_user':
        return auth.SubscriptionError('ChatGPT 订阅身份无法验证，请重新授权。', code, 401)
    if status_code == 401:
        return auth.SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。', 'subscription_unauthorized', 401)
    if status_code == 403:
        return auth.SubscriptionError('订阅未允许此模型请求；请检查账号、区域或授权范围。', 'subscription_forbidden', 403)
    if status_code == 400:
        if code in {'context_length_exceeded', 'input_too_long'}:
            return auth.SubscriptionError('文章超过所选模型的输入长度限制（HTTP 400）。')
        if code in {'model_not_found', 'invalid_model', 'unsupported_model'}:
            return auth.SubscriptionError('所选模型拒绝了 Responses API 请求（HTTP 400）；请在订阅设置中确认所选模型。')
        if code in {'unsupported_parameter', 'unsupported_value', 'invalid_value', 'parameter_missing'}:
            suffix = f'，参数 {param}' if param else ''
            return auth.SubscriptionError(f'模型拒绝了当前请求参数（HTTP 400{suffix}）。')
        if code == 'invalid_request_error':
            suffix = f'，参数 {param}' if param else ''
            return auth.SubscriptionError(f'OpenAI 拒绝了翻译请求格式（HTTP 400{suffix}）。')
    if status_code == 429 or code == 'rate_limit_exceeded':
        return auth.SubscriptionError('模型请求受到速率或额度限制（HTTP 429），请稍后重试。', 'subscription_rate_limited', 429)
    if status_code >= 500:
        return auth.SubscriptionError(f'OpenAI 模型服务暂时不可用（HTTP {status_code}），请稍后重试。', 'subscription_unavailable', status_code)
    return auth.SubscriptionError(f'OpenAI 模型请求失败（HTTP {status_code}）。', 'subscription_request_failed', status_code)


def _run_guard(execution_guard):
    if execution_guard is not None:
        execution_guard()


def stream_text(
    snapshot: SubscriptionExecutionSnapshot,
    messages: list[dict[str, str]] | None,
    *,
    execution_guard=None,
    _on_completed=None,
    _input_items=None,
    _payload_fields=None,
    _require_text=True,
):
    """Yield verified text deltas and succeed only after response.completed."""
    if _input_items is None:
        input_items = _normalize_messages(messages)
    elif type(_input_items) is list and _input_items:
        input_items = _input_items
    else:
        raise auth.SubscriptionError('模型请求缺少有效输入。')
    if _payload_fields is not None and (
        type(_payload_fields) is not dict
        or set(_payload_fields) - {'tools', 'tool_choice'}
    ):
        raise auth.SubscriptionError('模型请求包含不支持的参数。')
    _run_guard(execution_guard)
    connection = verify_snapshot(snapshot)
    access_token = auth.access_token_for(
        connection, snapshot.generation, execution_guard=execution_guard,
    )
    _run_guard(execution_guard)
    connection = verify_snapshot(snapshot)
    payload = {
        'model': snapshot.model_slug,
        'input': input_items,
        'store': False,
        'stream': True,
        **(_payload_fields or {}),
    }
    try:
        response = requests.post(
            auth.RESPONSES_URL,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'text/event-stream',
                'Content-Type': 'application/json',
            },
            json=payload,
            stream=True,
            timeout=(10, 120),
        )
    except Exception as exc:
        raise auth.SubscriptionError('连接 OpenAI 模型服务失败。') from exc
    try:
        _run_guard(execution_guard)
        if response.status_code < 200 or response.status_code >= 300:
            if response.status_code == 401:
                auth.mark_needs_reauth(connection.pk, connection.credential_generation)
            raise _structured_error(response.status_code, response)

        completed_response = None
        completed_items = {}
        current_event = ''
        emitted = False
        output_bytes = 0
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                _run_guard(execution_guard)
                line = raw_line.decode('utf-8', errors='replace') if isinstance(raw_line, bytes) else raw_line
                if not line:
                    continue
                if line.startswith('event:'):
                    current_event = line[6:].strip()
                    continue
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    continue
                try:
                    event = json.loads(data)
                except (TypeError, ValueError):
                    raise auth.SubscriptionError('OpenAI 返回了无法解析的 SSE 事件。') from None
                if not isinstance(event, dict):
                    continue
                event_type = event.get('type') or current_event
                if event_type == 'response.output_text.delta':
                    delta = event.get('delta')
                    if isinstance(delta, str) and delta:
                        output_bytes += len(delta.encode('utf-8'))
                        if output_bytes > MAX_OUTPUT_BYTES:
                            raise auth.SubscriptionError('模型输出超过安全上限，结果未保存。', 'output_limit_exceeded', 413)
                        emitted = True
                        yield delta
                elif event_type == 'response.output_item.done':
                    output_index = event.get('output_index')
                    item = event.get('item')
                    if (type(output_index) is not int or not 0 <= output_index < 256
                            or type(item) is not dict or output_index in completed_items):
                        raise auth.SubscriptionError('OpenAI 返回了无效的输出项事件。')
                    completed_items[output_index] = item
                elif event_type == 'response.completed':
                    completed_response = event.get('response') if isinstance(event.get('response'), dict) else event
                    if completed_response.get('output') == [] and completed_items:
                        indexes = sorted(completed_items)
                        if indexes != list(range(len(indexes))):
                            raise auth.SubscriptionError('OpenAI 返回了不连续的输出项事件。')
                        completed_response = {
                            **completed_response,
                            'output': [completed_items[index] for index in indexes],
                        }
                    break
                elif event_type in {'response.failed', 'response.incomplete', 'error'}:
                    detail = event.get('error')
                    if not isinstance(detail, dict):
                        response_data = event.get('response')
                        detail = response_data.get('error') if isinstance(response_data, dict) else None
                    fake = type('EventError', (), {'json': lambda self: {'error': detail or {}}})()
                    raise _structured_error(400, fake)
        except auth.SubscriptionError:
            raise
        except Exception as exc:
            raise auth.SubscriptionError('模型 SSE 连接中断，结果未完整完成。') from exc

        if completed_response is None:
            raise auth.SubscriptionError('模型 SSE 流在 response.completed 前中断，结果未保存。')
        if not emitted and _require_text:
            final_text = _extract_response_text(completed_response)
            if not final_text.strip():
                raise auth.SubscriptionError('模型已完成响应，但没有返回文本。')
            if len(final_text.encode('utf-8')) > MAX_OUTPUT_BYTES:
                raise auth.SubscriptionError('模型输出超过安全上限，结果未保存。', 'output_limit_exceeded', 413)
            yield final_text
        if _on_completed is not None:
            _on_completed(completed_response)
        _run_guard(execution_guard)
        verify_snapshot(snapshot)
    finally:
        response.close()


def complete_text(snapshot, messages, *, on_delta=None, execution_guard=None) -> str:
    chunks = []
    completed = []
    for delta in stream_text(
        snapshot, messages, execution_guard=execution_guard,
        _on_completed=completed.append,
    ):
        chunks.append(delta)
        if on_delta is not None:
            on_delta(delta)
    final_text = _extract_response_text(completed[0]) if completed else ''
    return final_text or ''.join(chunks)


def complete_response(
    snapshot: SubscriptionExecutionSnapshot,
    input_items: list[dict],
    *,
    tools: list[dict] | None = None,
    tool_choice=None,
    execution_guard=None,
) -> dict:
    """Return the completed native Responses object for a fenced tool call."""
    payload_fields = {}
    if tools is not None:
        payload_fields['tools'] = tools
    if tool_choice is not None:
        payload_fields['tool_choice'] = tool_choice
    completed = []
    for _delta in stream_text(
        snapshot, None, execution_guard=execution_guard,
        _on_completed=completed.append, _input_items=input_items,
        _payload_fields=payload_fields, _require_text=False,
    ):
        pass
    if len(completed) != 1:
        raise auth.SubscriptionError('模型完成回执无效。')
    try:
        completed_bytes = len(json.dumps(
            completed[0], ensure_ascii=False, allow_nan=False,
        ).encode('utf-8'))
    except (TypeError, ValueError):
        raise auth.SubscriptionError('模型完成回执格式无效。') from None
    if completed_bytes > MAX_OUTPUT_BYTES:
        raise auth.SubscriptionError(
            '模型输出超过安全上限，结果未保存。', 'output_limit_exceeded', 413,
        )
    return completed[0]


def stream_chat_response(connection: ChatGPTSubscriptionConnection, messages: list[dict[str, str]]):
    yield from stream_text(snapshot_for_connection(connection), messages)


def stream_full_translation(
    connection_id,
    expected_generation: int,
    model_slug: str,
    article_markdown: str,
    on_delta,
    execution_guard=None,
) -> str:
    connection = ChatGPTSubscriptionConnection.objects.filter(pk=connection_id).first()
    if connection is None:
        raise auth.ConnectionChangedError('订阅连接已断开。')
    snapshot = SubscriptionExecutionSnapshot(
        user_id=connection.user_id,
        connection_id=str(connection_id),
        generation=expected_generation,
        model_slug=model_slug,
    )
    prompt = (
        '请将以下完整 Markdown 文章翻译成中文。保持所有 Markdown 结构、代码块、'
        '行内代码、链接和标识符原样；只返回翻译后的完整 Markdown。\n\n'
        f'{article_markdown}'
    )
    return complete_text(
        snapshot,
        [{'role': 'user', 'content': prompt}],
        on_delta=on_delta,
        execution_guard=execution_guard,
    )
