"""Source-neutral durable research execution contract.

The job manager and agent loop depend on this module, while each credential
source owns its snapshot, fencing, transport, and continuation details.
"""
from __future__ import annotations

from . import byok_execution, subscription_execution


class ResearchExecutionError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(code)


def snapshot_source(snapshot) -> str:
    if type(snapshot) is dict and snapshot.get('source') == 'chatgpt_subscription':
        return 'chatgpt_subscription'
    if (type(snapshot) is dict and set(snapshot) == {'schema_version', 'consent', 'model'}):
        return 'byok'
    raise ResearchExecutionError('authorization_changed', '研究模型授权记录无效，任务已停止。')


def _wrap(operation):
    try:
        return operation()
    except byok_execution.ResearchBYOKError as exc:
        raise ResearchExecutionError(exc.code, exc.message) from None
    except subscription_execution.ResearchSubscriptionError as exc:
        raise ResearchExecutionError(exc.code, exc.message) from None


def capture_snapshot(user, execution_source: str, model_config_id=None):
    if execution_source == 'byok':
        return _wrap(lambda: byok_execution.capture_snapshot(user, model_config_id))
    if execution_source == 'chatgpt_subscription' and model_config_id is None:
        return _wrap(lambda: subscription_execution.capture_snapshot(user))
    raise ResearchExecutionError('model_unavailable', '所选研究模型来源不可用。')


def followup_snapshot(session, user, execution_source: str, model_config_id=None):
    native = session.native_continuation if type(session.native_continuation) is dict else {}
    snapshot = native.get('execution_snapshot')
    if snapshot_source(snapshot) != execution_source:
        raise ResearchExecutionError('authorization_changed', '续问必须继续使用会话原模型来源。')
    if execution_source == 'byok':
        return _wrap(lambda: byok_execution.followup_snapshot(session, user, model_config_id))
    if model_config_id is not None:
        raise ResearchExecutionError('authorization_changed', '续问模型来源与会话不一致。')
    return _wrap(lambda: subscription_execution.followup_snapshot(session, user))


def verify_snapshot(snapshot, *, owner_id: int):
    source = snapshot_source(snapshot)
    if source == 'byok':
        return _wrap(lambda: byok_execution.verify_snapshot(snapshot, owner_id=owner_id))
    return _wrap(lambda: subscription_execution.verify_snapshot(snapshot, owner_id=owner_id))


def commit_with_snapshot(snapshot, *, owner_id: int, persist):
    source = snapshot_source(snapshot)
    if source == 'byok':
        return _wrap(lambda: byok_execution.commit_with_snapshot(
            snapshot, owner_id=owner_id, persist=persist,
        ))
    return _wrap(lambda: subscription_execution.commit_with_snapshot(
        snapshot, owner_id=owner_id, persist=persist,
    ))


def call_model_once(snapshot, *, owner_id: int, messages, tools, execution_guard=None):
    source = snapshot_source(snapshot)
    if source == 'byok':
        return _wrap(lambda: byok_execution.call_model_once(
            snapshot, owner_id=owner_id, messages=messages, tools=tools,
            execution_guard=execution_guard,
        ))
    return _wrap(lambda: subscription_execution.call_model_once(
        snapshot, owner_id=owner_id, messages=messages, tools=tools,
        execution_guard=execution_guard,
    ))


def validate_tool_batch(raw_tool_calls, available_tools):
    return _wrap(lambda: byok_execution.validate_tool_batch(raw_tool_calls, available_tools))


def continuation_payload(snapshot, messages):
    if snapshot_source(snapshot) == 'byok':
        return _wrap(lambda: byok_execution.continuation_payload(snapshot, messages))
    return _wrap(lambda: subscription_execution.continuation_payload(snapshot, messages))


def native_messages(session, snapshot):
    if snapshot_source(snapshot) == 'byok':
        return _wrap(lambda: byok_execution.native_messages(session, snapshot))
    return _wrap(lambda: subscription_execution.native_messages(session, snapshot))


def visible_messages(messages):
    return byok_execution.visible_messages(messages)


def preserve_native_fields(message, target):
    return byok_execution.preserve_native_fields(message, target)


def research_model_payload(snapshot, *, owner_id: int):
    source = snapshot_source(snapshot)
    if source == 'byok':
        model = byok_execution.decode_snapshot(snapshot, owner_id=owner_id)
        return {
            'source': 'byok',
            'model_config_id': model.model_config_id,
            'model_id': model.model_id,
        }
    model = subscription_execution.decode_snapshot(snapshot, owner_id=owner_id)
    return {
        'source': 'chatgpt_subscription',
        'model_config_id': None,
        'model_id': model.model_slug,
    }
