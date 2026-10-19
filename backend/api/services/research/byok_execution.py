"""T09 owner-scoped BYOK execution for the first durable research run.

This module binds the existing T03 model+tools receipt to the T01 credential
snapshot. It never selects a fallback model/provider and never retries a model
request. Secrets are passed only to a request-scoped gateway client.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from uuid import UUID

from django.conf import settings
from django.db import transaction

from api.services.ai_credentials import (
    ConnectionSnapshot, CredentialUnavailable, lock_owner,
)
from api.services.ai_task_preferences import (
    ModelSelectionError, TaskModelSnapshot, require_task_model_snapshot,
    resolve_task_model,
)
from api.services.ai_worker_fencing import (
    SNAPSHOT_SCHEMA_VERSION, check_at_claim, commit_result, dispatch_once,
)
from api.services.ai_gateway import AIGatewayError, build_gateway_client

logger = logging.getLogger(__name__)

RESEARCH_SNAPSHOT_SCHEMA_VERSION = 1
MAX_TOOL_CALLS = 8
_CALL_ID_RE = re.compile(r"^[\x21-\x7e]{1,128}$")
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "consent", "model"})
_MODEL_FIELDS = frozenset(TaskModelSnapshot.__dataclass_fields__)
_CONNECTION_FIELDS = frozenset({
    "user_id", "connection_id", "credential_epoch", "credential_version",
    "provider_id", "endpoint_profile", "endpoint_profile_version",
})
_SAFE_ERROR_MESSAGES = {
    "authorization_changed": "个人模型授权或配置已变化，研究任务已停止。",
    "model_unavailable": "所选个人研究模型当前不可用。",
    "provider_unavailable": "个人模型暂时无法完成研究，请检查配置后重新发起。",
    "invalid_response": "个人模型返回了不完整或无法验证的响应。",
    "invalid_tool_call": "个人模型返回了无法验证的工具请求，未执行该批工具。",
    "tool_failed": "研究工具未能安全完成，研究报告未保存。",
    "feature_disabled": "个人模型研究当前未启用。",
}


class ResearchBYOKError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in _SAFE_ERROR_MESSAGES else "provider_unavailable"
        self.message = _SAFE_ERROR_MESSAGES[self.code]
        super().__init__(self.code)


def _require_feature():
    if settings.PUBLIC_SITE_MODE != "full" or not getattr(settings, "AI_BYOK_ENABLED", False):
        raise ResearchBYOKError("feature_disabled")


def capture_snapshot(user, model_config_id: str) -> dict:
    """Resolve the explicitly selected deep-research model under the owner lock.

    Call from the same outer atomic block that creates ResearchRun/session, so
    the T01 owner lock and captured capability receipt bind the enqueue row.
    """
    _require_feature()
    if (not user or not getattr(user, "is_authenticated", False)
            or not getattr(user, "is_active", False)):
        raise ResearchBYOKError("authorization_changed")
    if type(model_config_id) is not str or len(model_config_id) != 36:
        raise ResearchBYOKError("model_unavailable")
    try:
        parsed_id = UUID(model_config_id)
        if str(parsed_id) != model_config_id:
            raise ValueError
    except (ValueError, TypeError):
        raise ResearchBYOKError("model_unavailable") from None
    try:
        with transaction.atomic():
            lock_owner(user.pk)
            selection = resolve_task_model(
                user, "deep_research", explicit_model_id=parsed_id,
            )
            if selection.task_kind != "deep_research" or selection.selected_by != "explicit":
                raise ResearchBYOKError("model_unavailable")
            if not selection.tools_attempt_id:
                raise ResearchBYOKError("model_unavailable")
            require_task_model_snapshot(selection, owner_id=user.pk)
            payload = {
                "schema_version": RESEARCH_SNAPSHOT_SCHEMA_VERSION,
                "consent": True,
                "model": asdict(selection),
            }
            # Run the strict decoder before the payload can enter durable state.
            decode_snapshot(payload, owner_id=user.pk)
            return payload
    except ResearchBYOKError:
        raise
    except (ModelSelectionError, CredentialUnavailable):
        raise ResearchBYOKError("model_unavailable") from None


def decode_snapshot(payload, *, owner_id: int) -> TaskModelSnapshot:
    """Strictly decode a secret-free, versioned T03+T01 execution snapshot."""
    if (type(payload) is not dict or set(payload) != _TOP_LEVEL_FIELDS
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != RESEARCH_SNAPSHOT_SCHEMA_VERSION
            or payload.get("consent") is not True
            or type(owner_id) is not int or owner_id < 1):
        raise ResearchBYOKError("authorization_changed")
    raw_model = payload.get("model")
    if type(raw_model) is not dict or set(raw_model) != _MODEL_FIELDS:
        raise ResearchBYOKError("authorization_changed")
    raw_connection = raw_model.get("connection")
    if type(raw_connection) is not dict or set(raw_connection) != _CONNECTION_FIELDS:
        raise ResearchBYOKError("authorization_changed")
    if (type(raw_model.get("user_id")) is not int
            or raw_model["user_id"] != owner_id
            or raw_model.get("task_kind") != "deep_research"
            or raw_model.get("selected_by") != "explicit"
            or type(raw_model.get("preference_revision")) is not int
            or raw_model["preference_revision"] < 0
            or type(raw_model.get("model_revision")) is not int
            or raw_model["model_revision"] < 1
            or type(raw_model.get("model_config_id")) is not str
            or type(raw_model.get("model_id")) is not str or not raw_model["model_id"]
            or type(raw_model.get("proxy_alias")) is not str or not raw_model["proxy_alias"]
            or type(raw_model.get("text_attempt_id")) is not str
            or type(raw_model.get("tools_attempt_id")) is not str
            or not raw_model["tools_attempt_id"]):
        raise ResearchBYOKError("authorization_changed")
    try:
        config_id = UUID(raw_model["model_config_id"])
        if str(config_id) != raw_model["model_config_id"]:
            raise ValueError
    except (ValueError, TypeError):
        raise ResearchBYOKError("authorization_changed") from None
    connection = raw_connection
    if (type(connection.get("user_id")) is not int or connection["user_id"] != owner_id
            or type(connection.get("connection_id")) is not str
            or type(connection.get("credential_epoch")) is not int
            or type(connection.get("credential_version")) is not int
            or type(connection.get("provider_id")) is not str or not connection["provider_id"]
            or type(connection.get("endpoint_profile")) is not str or not connection["endpoint_profile"]
            or type(connection.get("endpoint_profile_version")) is not int):
        raise ResearchBYOKError("authorization_changed")
    snapshot = TaskModelSnapshot(
        user_id=raw_model["user_id"],
        task_kind=raw_model["task_kind"],
        selected_by=raw_model["selected_by"],
        preference_revision=raw_model["preference_revision"],
        model_config_id=raw_model["model_config_id"],
        model_revision=raw_model["model_revision"],
        model_id=raw_model["model_id"],
        proxy_alias=raw_model["proxy_alias"],
        connection=ConnectionSnapshot(**connection),
        text_attempt_id=raw_model["text_attempt_id"],
        tools_attempt_id=raw_model["tools_attempt_id"],
    )
    return snapshot


def _connection_fence(snapshot: TaskModelSnapshot) -> dict:
    return {"schema_version": SNAPSHOT_SCHEMA_VERSION, **asdict(snapshot.connection)}


def verify_snapshot(payload, *, owner_id: int) -> TaskModelSnapshot:
    _require_feature()
    try:
        model = decode_snapshot(payload, owner_id=owner_id)
        check_at_claim(_connection_fence(model), task_owner_id=owner_id)
        require_task_model_snapshot(model, owner_id=owner_id)
        return model
    except ResearchBYOKError:
        raise
    except (CredentialUnavailable, ModelSelectionError, TypeError, ValueError):
        raise ResearchBYOKError("authorization_changed") from None


def commit_with_snapshot(payload, *, owner_id: int, persist):
    """Fence a short DB-only research result commit with T01 and T03."""
    model = verify_snapshot(payload, owner_id=owner_id)

    def checked_persist():
        _require_feature()
        require_task_model_snapshot(model, owner_id=owner_id)
        return persist()

    try:
        return commit_result(
            _connection_fence(model), task_owner_id=owner_id, persist=checked_persist,
        )
    except ResearchBYOKError:
        raise
    except (CredentialUnavailable, ModelSelectionError, TypeError, ValueError):
        raise ResearchBYOKError("authorization_changed") from None


def _get(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _reject_constant(_value):
    raise ValueError("non-finite JSON number")


def _unique_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _json_type_matches(value, expected):
    if expected == "object":
        return type(value) is dict
    if expected == "array":
        return type(value) is list
    if expected == "string":
        return type(value) is str
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return type(value) in (int, float)
    if expected == "boolean":
        return type(value) is bool
    if expected == "null":
        return value is None
    return False


def _validate_json_schema(value, schema, *, depth=0):
    if depth > 8 or type(schema) is not dict:
        return False
    expected = schema.get("type")
    if expected is not None and not _json_type_matches(value, expected):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if type(value) is str:
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 20_000):
            return False
    if type(value) in (int, float) and (type(value) is not bool):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "maximum" in schema and value > schema["maximum"]:
            return False
    if type(value) is list:
        if len(value) > schema.get("maxItems", 100):
            return False
        item_schema = schema.get("items")
        if item_schema is not None and any(
            not _validate_json_schema(item, item_schema, depth=depth + 1) for item in value
        ):
            return False
    if type(value) is dict:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if type(properties) is not dict or type(required) is not list:
            return False
        if any(type(key) is not str for key in value):
            return False
        # Current research tools do not opt into arbitrary extension fields;
        # enforce declared properties even if a provider omits additionalProperties.
        if any(key not in properties for key in value):
            return False
        if any(key not in value for key in required):
            return False
        for key, item in value.items():
            if not _validate_json_schema(item, properties[key], depth=depth + 1):
                return False
    return True


def validate_tool_batch(tool_calls, available_tools):
    """Validate every proposed tool call before emitting/performing any effect."""
    if type(tool_calls) not in (list, tuple) or not 1 <= len(tool_calls) <= MAX_TOOL_CALLS:
        raise ResearchBYOKError("invalid_tool_call")
    allowed = {
        tool["function"]["name"]: tool["function"]["parameters"]
        for tool in available_tools
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    }
    normalized = []
    seen_ids = set()
    for call in tool_calls:
        call_id = _get(call, "id")
        call_type = _get(call, "type")
        function = _get(call, "function")
        name = _get(function, "name")
        raw_arguments = _get(function, "arguments")
        if (call_type != "function" or type(call_id) is not str
                or not _CALL_ID_RE.fullmatch(call_id) or call_id in seen_ids
                or type(name) is not str or name not in allowed
                or type(raw_arguments) is not str or len(raw_arguments) > 20_000):
            raise ResearchBYOKError("invalid_tool_call")
        seen_ids.add(call_id)
        try:
            arguments = json.loads(
                raw_arguments,
                object_pairs_hook=_unique_object_pairs,
                parse_constant=_reject_constant,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ResearchBYOKError("invalid_tool_call") from None
        if not _validate_json_schema(arguments, allowed[name]):
            raise ResearchBYOKError("invalid_tool_call")
        normalized.append({
            "id": call_id, "name": name, "raw_arguments": raw_arguments,
            "arguments": arguments,
        })
    return normalized


def _validated_completion(response):
    choices = _get(response, "choices")
    if type(choices) not in (list, tuple) or len(choices) != 1:
        raise ResearchBYOKError("invalid_response")
    choice = choices[0]
    message = _get(choice, "message")
    finish_reason = _get(choice, "finish_reason")
    if message is None:
        raise ResearchBYOKError("invalid_response")
    raw_calls = _get(message, "tool_calls") or []
    content = _get(message, "content")
    if finish_reason == "tool_calls":
        if content not in (None, "") or not raw_calls:
            raise ResearchBYOKError("invalid_response")
    elif finish_reason == "stop":
        if raw_calls or type(content) is not str or not content.strip():
            raise ResearchBYOKError("invalid_response")
    else:
        raise ResearchBYOKError("invalid_response")
    return message, raw_calls


def call_model_once(payload, *, owner_id: int, messages, tools, execution_guard):
    """One exact configured-model request through the trusted local Proxy."""
    model = verify_snapshot(payload, owner_id=owner_id)
    try:
        response = dispatch_once(
            _connection_fence(model), task_owner_id=owner_id,
            send=lambda key: _send_once(
                key, model, messages=messages, tools=tools,
                payload=payload, owner_id=owner_id, execution_guard=execution_guard,
            ),
        )
        execution_guard()
        verify_snapshot(payload, owner_id=owner_id)
        _validated_completion(response)
        return response
    except ResearchBYOKError:
        raise
    except Exception as exc:
        # Preserve run cancellation/lease failures from the business guard.
        execution_guard()
        # Provider/SDK error detail may contain private prompt or response text.
        logger.info("Research BYOK request failed (%s).", type(exc).__name__)
        raise ResearchBYOKError("provider_unavailable") from None


def _send_once(provider_key, model, *, messages, tools, payload, owner_id, execution_guard):
    execution_guard()
    verify_snapshot(payload, owner_id=owner_id)
    gateway = None
    try:
        gateway = build_gateway_client(provider_key)
        response = gateway.chat.completions.create(
            model=model.proxy_alias, messages=messages, tools=tools,
            tool_choice="auto", temperature=0.3, max_tokens=8000,
        )
        return response
    except AIGatewayError:
        raise ResearchBYOKError("provider_unavailable") from None
    except ResearchBYOKError:
        raise
    except Exception:
        raise ResearchBYOKError("provider_unavailable") from None
    finally:
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass
