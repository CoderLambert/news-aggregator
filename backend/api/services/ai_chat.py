"""Owner-bound article chat through the fixed BYOK LiteLLM route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

import httpx2
from django.conf import settings
from openai import APIConnectionError, APIStatusError, OpenAI

from api.models import UserAIModelConfig
from api.services.ai_credentials import (
    CredentialEncryptionUnavailable,
    CredentialUnavailable,
    decrypt_credential,
    require_active_connection,
)
from api.services.ai_execution import ExecutionSnapshot, ModelSelectionError, resolve_execution
from api.services.ai_model_registry import get_model_preset
from api.services.ai_model_test import gateway_is_configured
from api.services.ai_registry import get_profile
from api.services.chat_history import ChatConflict


CHAT_OUTPUT_TOKEN_LIMIT = 2048
CHAT_TIMEOUT_SECONDS = 120


class ArticleChatError(RuntimeError):
    """A safe error code for an explicitly selected BYOK article-chat turn."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


ARTICLE_CHAT_ERRORS = {
    'model_not_found': (404, '所选模型不存在或无权访问。'),
    'model_not_configured': (409, '请先配置可用的模型。'),
    'model_unavailable': (409, '所选模型或凭据已停用，请检查模型设置。'),
    'model_reselection_required': (409, '所选模型已变更，请到模型设置中重新选择。'),
    'model_route_unavailable': (409, '所选模型暂不支持新闻问答流式请求。'),
    'gateway_unavailable': (503, 'BYOK 模型网关当前不可用，本次未发送。'),
    'provider_unavailable': (502, '模型服务暂时不可用，本次回答未保存。'),
    'provider_rejected': (502, '模型服务拒绝了本次请求，本次回答未保存。'),
    'incomplete_response': (502, '回答流未正常完成，本次内容未保存。'),
    'empty_response': (502, '模型没有返回可保存的回答。'),
    'execution_changed': (409, '模型连接已变更，本次回答未保存。'),
}


@dataclass(frozen=True)
class ArticleChatExecution:
    snapshot: ExecutionSnapshot
    gateway_url: str
    project_key: str
    provider_key: str
    model_alias: str
    model_source: dict[str, str]


def article_chat_error_payload(error: ArticleChatError) -> tuple[int, dict[str, str]]:
    status_code, message = ARTICLE_CHAT_ERRORS.get(
        error.code,
        ARTICLE_CHAT_ERRORS['provider_unavailable'],
    )
    return status_code, {'error_code': error.code, 'error': message}


def prepare_article_chat_execution(user, model_config_id: str) -> ArticleChatExecution:
    """Resolve ownership, a server-owned catalog alias, the gateway and the key."""
    try:
        snapshot = resolve_execution(user, 'article_qa', model_config_id=model_config_id)
    except ModelSelectionError as error:
        code = error.code if error.code in ARTICLE_CHAT_ERRORS else 'model_unavailable'
        raise ArticleChatError(code) from None

    gateway_url = settings.AI_BYOK_GATEWAY_URL
    project_key = settings.AI_BYOK_GATEWAY_PROJECT_KEY
    if not gateway_is_configured(gateway_url, project_key):
        raise ArticleChatError('gateway_unavailable')

    config = UserAIModelConfig.objects.select_related('connection').filter(
        pk=snapshot.model_config_id,
        connection__user_id=snapshot.user_id,
        connection__is_deleted=False,
    ).first()
    if config is None:
        raise ArticleChatError('model_not_found')
    connection = config.connection
    if (
        str(config.connection_id) != snapshot.connection_id
        or config.config_revision != snapshot.config_revision
        or config.model_id != snapshot.model_id
        or connection.provider_id != snapshot.provider_id
        or connection.endpoint_profile != snapshot.endpoint_profile
        or connection.endpoint_profile_version != snapshot.endpoint_profile_version
        or connection.credential_epoch != snapshot.credential_epoch
    ):
        raise ArticleChatError('execution_changed')

    preset = get_model_preset(config.catalog_model_id, connection.provider_id)
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if (
        preset is None
        or config.catalog_version != preset['catalog_version']
        or config.model_id != preset['model_id']
        or config.proxy_model_alias != preset['proxy_model_alias']
        or profile is None
        or profile['version'] != connection.endpoint_profile_version
    ):
        raise ArticleChatError('model_route_unavailable')

    try:
        active_connection = require_active_connection(
            user_id=snapshot.user_id,
            connection_id=snapshot.connection_id,
            expected_epoch=snapshot.credential_epoch,
        )
        provider_key = decrypt_credential(active_connection)
    except (CredentialEncryptionUnavailable, CredentialUnavailable):
        raise ArticleChatError('model_unavailable') from None

    return ArticleChatExecution(
        snapshot=snapshot,
        gateway_url=gateway_url.rstrip('/'),
        project_key=project_key,
        provider_key=provider_key,
        model_alias=preset['proxy_model_alias'],
        model_source={
            'provider': profile['provider_name'],
            'model': config.display_name,
        },
    )


def assert_article_chat_execution_current(execution: ArticleChatExecution) -> None:
    """Fence each stream step against model edits, key rotation, disable or delete."""
    snapshot = execution.snapshot
    config = UserAIModelConfig.objects.select_related('connection').filter(
        pk=snapshot.model_config_id,
        connection__user_id=snapshot.user_id,
        connection__is_deleted=False,
    ).first()
    if config is None:
        raise ArticleChatError('execution_changed')
    connection = config.connection
    if (
        str(config.connection_id) != snapshot.connection_id
        or config.config_revision != snapshot.config_revision
        or config.model_id != snapshot.model_id
        or connection.provider_id != snapshot.provider_id
        or connection.endpoint_profile != snapshot.endpoint_profile
        or connection.endpoint_profile_version != snapshot.endpoint_profile_version
        or connection.credential_epoch != snapshot.credential_epoch
    ):
        raise ArticleChatError('execution_changed')
    try:
        require_active_connection(
            user_id=snapshot.user_id,
            connection_id=snapshot.connection_id,
            expected_epoch=snapshot.credential_epoch,
        )
    except CredentialUnavailable:
        raise ArticleChatError('execution_changed') from None


def stream_article_chat(
    execution: ArticleChatExecution,
    messages: list[dict[str, str]],
    *,
    execution_guard: Callable[[], None],
) -> Iterator[str]:
    """Use one OpenAI Responses SDK stream; only a completed terminal can succeed."""
    base_url = f'{execution.gateway_url}/v1'
    http_client = None
    client = None
    stream = None
    completed = False
    emitted_text = False
    collected: list[str] = []
    try:
        try:
            http_client = httpx2.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx2.Timeout(CHAT_TIMEOUT_SECONDS, connect=10),
            )
            client = OpenAI(
                api_key=execution.project_key,
                base_url=base_url,
                http_client=http_client,
                max_retries=0,
                timeout=CHAT_TIMEOUT_SECONDS,
            )
        except Exception:
            raise ArticleChatError('gateway_unavailable') from None
        execution_guard()
        stream = client.responses.create(
            model=execution.model_alias,
            input=messages,
            max_output_tokens=CHAT_OUTPUT_TOKEN_LIMIT,
            store=False,
            stream=True,
            extra_body={'api_key': execution.provider_key},
        )
        with stream:
            for event in stream:
                execution_guard()
                event_type = getattr(event, 'type', None)
                if event_type == 'response.output_text.delta':
                    delta = getattr(event, 'delta', None)
                    if isinstance(delta, str) and delta:
                        emitted_text = True
                        collected.append(delta)
                        yield delta
                elif event_type == 'response.completed':
                    response = getattr(event, 'response', None)
                    if getattr(response, 'status', None) != 'completed':
                        raise ArticleChatError('incomplete_response')
                    completed = True
                    final_text = getattr(response, 'output_text', None)
                    if not emitted_text and isinstance(final_text, str) and final_text:
                        collected.append(final_text)
                        yield final_text
                    break
                elif event_type in {'response.incomplete', 'response.failed', 'error'}:
                    code = 'incomplete_response' if event_type == 'response.incomplete' else 'provider_rejected'
                    raise ArticleChatError(code)

        if not completed:
            raise ArticleChatError('incomplete_response')
        if not ''.join(collected).strip():
            raise ArticleChatError('empty_response')
    except (ArticleChatError, ChatConflict):
        raise
    except APIStatusError:
        raise ArticleChatError('provider_rejected') from None
    except APIConnectionError:
        raise ArticleChatError('gateway_unavailable') from None
    except Exception:
        # SDK, HTTP and provider details can contain request material or secrets.
        raise ArticleChatError('provider_unavailable') from None
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if client is not None:
            client.close()
        elif http_client is not None:
            http_client.close()
