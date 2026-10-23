"""ChatGPT Subscription capability proof and durable research execution."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from django.db import transaction

from api.models import (
    ChatGPTSubscriptionCapabilityReceipt,
    ChatGPTSubscriptionConnection,
)
from api.services import chatgpt_subscription as auth
from api.services.ai_credentials import lock_owner
from api.services.ai_responses_protocol import (
    RESPONSES_PROTOCOL,
    ResponsesProtocolError,
    completion_object,
    responses_completion,
    responses_input,
)
from api.services.chatgpt_subscription_llm import (
    SubscriptionExecutionSnapshot,
    complete_response,
    snapshot_for_connection,
    snapshot_for_user,
    verify_snapshot as verify_llm_snapshot,
)
from .access import require_session_evidence

SNAPSHOT_SCHEMA_VERSION = 1
MAX_CONTINUATION_BYTES = 4 * 1024 * 1024
PROBE_TOOL_NAME = 'newshub_subscription_tools_probe'
_SAFE_MESSAGES = {
    'authorization_changed': 'ChatGPT 订阅账号、模型或授权已变化，研究任务已停止。',
    'model_unavailable': '所选 ChatGPT 订阅模型当前不可用。',
    'model_not_verified': '请先验证当前 ChatGPT 订阅模型的工具调用能力。',
    'provider_unavailable': 'ChatGPT 订阅模型暂时无法完成研究，请稍后明确重试。',
    'invalid_response': 'ChatGPT 订阅模型返回了不完整或无法验证的响应。',
    'invalid_tool_call': 'ChatGPT 订阅模型返回了无法验证的工具请求，未执行该批工具。',
    'tool_failed': '研究工具未能安全完成，研究报告未保存。',
}


class ResearchSubscriptionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in _SAFE_MESSAGES else 'provider_unavailable'
        self.message = _SAFE_MESSAGES[self.code]
        super().__init__(self.code)


@dataclass(frozen=True)
class SubscriptionResearchSnapshot:
    user_id: int
    connection_id: str
    connection_generation: int
    model_slug: str
    receipt_id: str


def _receipt_payload(receipt):
    return {
        'id': str(receipt.pk),
        'status': receipt.status,
        'safe_error_code': receipt.safe_error_code,
        'model_slug': receipt.model_slug,
        'created_at': receipt.created_at.isoformat(),
    }


def current_tools_receipt(connection):
    if connection is None or not connection.selected_model:
        return None
    return ChatGPTSubscriptionCapabilityReceipt.objects.filter(
        connection=connection,
        model_slug=connection.selected_model,
        connection_generation=connection.generation,
        capability='tools',
    ).order_by('-created_at').first()


def tools_supported(connection) -> bool:
    receipt = current_tools_receipt(connection)
    return receipt is not None and receipt.status == 'supported'


def _research_input(messages):
    try:
        items = responses_input(messages)
    except ResponsesProtocolError:
        raise ResearchSubscriptionError('invalid_response') from None
    for item in items:
        if item.get('role') == 'system':
            item['role'] = 'developer'
    return items


def _research_tools(tools):
    if type(tools) is not list:
        raise ResearchSubscriptionError('invalid_response')
    converted = []
    for tool in tools:
        function = tool.get('function') if type(tool) is dict and tool.get('type') == 'function' else None
        if type(function) is not dict:
            raise ResearchSubscriptionError('invalid_response')
        name = function.get('name')
        parameters = function.get('parameters')
        if not isinstance(name, str) or not name or type(parameters) is not dict:
            raise ResearchSubscriptionError('invalid_response')
        converted.append({
            'type': 'function',
            'name': name,
            'description': str(function.get('description') or ''),
            'parameters': copy.deepcopy(parameters),
            'strict': False,
        })
    return converted


def _save_probe_receipt(snapshot, status, safe_error_code=''):
    with transaction.atomic():
        lock_owner(snapshot.user_id)
        connection = verify_llm_snapshot(snapshot)
        return ChatGPTSubscriptionCapabilityReceipt.objects.create(
            connection=connection,
            model_slug=snapshot.model_slug,
            connection_generation=snapshot.generation,
            credential_generation=connection.credential_generation,
            capability='tools',
            status=status,
            safe_error_code=safe_error_code,
        )


def probe_tools(connection, *, consent):
    if consent is not True:
        raise auth.SubscriptionError(
            '主动测试可能使用订阅额度，请明确确认后重试。',
            'subscription_probe_consent_required', 400,
        )
    snapshot = snapshot_for_connection(connection)
    tools = [{
        'type': 'function',
        'name': PROBE_TOOL_NAME,
        'description': 'Return the required fixed capability probe payload.',
        'parameters': {
            'type': 'object',
            'properties': {'supported': {'type': 'boolean', 'const': True}},
            'required': ['supported'],
            'additionalProperties': False,
        },
        'strict': True,
    }]
    try:
        response = complete_response(
            snapshot,
            [{'role': 'developer', 'content': 'This is a capability probe. Call the required tool exactly once.'}],
            tools=tools,
            tool_choice={'type': 'function', 'name': PROBE_TOOL_NAME},
        )
        parsed = responses_completion(response)
        calls = parsed['choices'][0]['message'].get('tool_calls') or []
        if len(calls) != 1 or calls[0]['function']['name'] != PROBE_TOOL_NAME:
            raise ResearchSubscriptionError('invalid_tool_call')
        try:
            arguments = json.loads(calls[0]['function']['arguments'])
        except (TypeError, ValueError):
            raise ResearchSubscriptionError('invalid_tool_call') from None
        if arguments != {'supported': True}:
            raise ResearchSubscriptionError('invalid_tool_call')
    except auth.SubscriptionError as exc:
        status = 'unsupported' if exc.error_code == 'subscription_sharing_unsupported_capability' else 'unknown'
        receipt = _save_probe_receipt(snapshot, status, exc.error_code)
        if status == 'unsupported':
            return _receipt_payload(receipt)
        raise
    except (ResponsesProtocolError, ResearchSubscriptionError):
        receipt = _save_probe_receipt(snapshot, 'unknown', 'invalid_tool_response')
        raise auth.SubscriptionError(
            '订阅模型未返回可验证的工具调用，研究能力保持未验证。',
            'subscription_tools_unverified', 409,
        ) from None
    return _receipt_payload(_save_probe_receipt(snapshot, 'supported'))


def capture_snapshot(user) -> dict:
    try:
        with transaction.atomic():
            lock_owner(user.pk)
            llm = snapshot_for_user(user)
            connection = ChatGPTSubscriptionConnection.objects.select_for_update().get(
                pk=llm.connection_id, user_id=user.pk,
            )
            receipt = current_tools_receipt(connection)
            if receipt is None or receipt.status != 'supported':
                raise ResearchSubscriptionError('model_not_verified')
            payload = {
                'schema_version': SNAPSHOT_SCHEMA_VERSION,
                'source': 'chatgpt_subscription',
                'consent': True,
                'subscription': {
                    'user_id': user.pk,
                    'connection_id': str(connection.pk),
                    'connection_generation': connection.generation,
                    'model_slug': connection.selected_model,
                    'receipt_id': str(receipt.pk),
                },
            }
            verify_snapshot(payload, owner_id=user.pk)
            return payload
    except ResearchSubscriptionError:
        raise
    except (auth.SubscriptionError, ChatGPTSubscriptionConnection.DoesNotExist):
        raise ResearchSubscriptionError('model_unavailable') from None


def decode_snapshot(payload, *, owner_id: int) -> SubscriptionResearchSnapshot:
    if (type(payload) is not dict or set(payload) != {
            'schema_version', 'source', 'consent', 'subscription'}
            or payload.get('schema_version') != SNAPSHOT_SCHEMA_VERSION
            or payload.get('source') != 'chatgpt_subscription'
            or payload.get('consent') is not True
            or type(owner_id) is not int or owner_id < 1):
        raise ResearchSubscriptionError('authorization_changed')
    raw = payload.get('subscription')
    if type(raw) is not dict or set(raw) != {
            'user_id', 'connection_id', 'connection_generation', 'model_slug', 'receipt_id'}:
        raise ResearchSubscriptionError('authorization_changed')
    if (raw.get('user_id') != owner_id
            or type(raw.get('connection_id')) is not str or not raw['connection_id']
            or type(raw.get('connection_generation')) is not int
            or raw['connection_generation'] < 0
            or type(raw.get('model_slug')) is not str or not raw['model_slug']
            or type(raw.get('receipt_id')) is not str or not raw['receipt_id']):
        raise ResearchSubscriptionError('authorization_changed')
    return SubscriptionResearchSnapshot(
        user_id=owner_id,
        connection_id=raw['connection_id'],
        connection_generation=raw['connection_generation'],
        model_slug=raw['model_slug'],
        receipt_id=raw['receipt_id'],
    )


def verify_snapshot(payload, *, owner_id: int) -> SubscriptionResearchSnapshot:
    decoded = decode_snapshot(payload, owner_id=owner_id)
    llm = SubscriptionExecutionSnapshot(
        user_id=decoded.user_id,
        connection_id=decoded.connection_id,
        generation=decoded.connection_generation,
        model_slug=decoded.model_slug,
    )
    try:
        connection = verify_llm_snapshot(llm)
    except auth.SubscriptionError:
        raise ResearchSubscriptionError('authorization_changed') from None
    receipt = ChatGPTSubscriptionCapabilityReceipt.objects.filter(
        pk=decoded.receipt_id,
        connection=connection,
        model_slug=decoded.model_slug,
        connection_generation=decoded.connection_generation,
        capability='tools', status='supported',
    ).first()
    if receipt is None:
        raise ResearchSubscriptionError('authorization_changed')
    return decoded


def commit_with_snapshot(payload, *, owner_id: int, persist):
    with transaction.atomic():
        lock_owner(owner_id)
        verify_snapshot(payload, owner_id=owner_id)
        return persist()


def call_model_once(payload, *, owner_id: int, messages, tools, execution_guard=None):
    decoded = verify_snapshot(payload, owner_id=owner_id)
    llm = SubscriptionExecutionSnapshot(
        user_id=decoded.user_id,
        connection_id=decoded.connection_id,
        generation=decoded.connection_generation,
        model_slug=decoded.model_slug,
    )
    try:
        native = complete_response(
            llm, _research_input(messages), tools=_research_tools(tools),
            tool_choice='auto', execution_guard=execution_guard,
        )
        parsed = responses_completion(native)
        response = completion_object(parsed)
    except auth.ConnectionChangedError:
        raise ResearchSubscriptionError('authorization_changed') from None
    except auth.SubscriptionError:
        raise ResearchSubscriptionError('provider_unavailable') from None
    except ResponsesProtocolError:
        raise ResearchSubscriptionError('invalid_response') from None
    verify_snapshot(payload, owner_id=owner_id)
    return response


def continuation_payload(snapshot, messages):
    payload = {
        'schema_version': 1,
        'protocol': RESPONSES_PROTOCOL,
        'execution_snapshot': snapshot,
        'messages': messages,
    }
    try:
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError):
        raise ResearchSubscriptionError('invalid_response') from None
    if size > MAX_CONTINUATION_BYTES:
        raise ResearchSubscriptionError('invalid_response')
    return payload


def native_messages(session, snapshot):
    native = session.native_continuation
    if (type(native) is not dict or native.get('schema_version') != 1
            or native.get('protocol') != RESPONSES_PROTOCOL
            or native.get('execution_snapshot') != snapshot
            or type(native.get('messages')) is not list):
        raise ResearchSubscriptionError('authorization_changed')
    continuation_payload(snapshot, native['messages'])
    return copy.deepcopy(native['messages'])


def followup_snapshot(session, user):
    if session.user_id != user.pk or not session.native_continuation:
        raise ResearchSubscriptionError('authorization_changed')
    snapshot = session.native_continuation.get('execution_snapshot')
    verify_snapshot(snapshot, owner_id=user.pk)
    native_messages(session, snapshot)
    require_session_evidence(session, user)
    return snapshot
