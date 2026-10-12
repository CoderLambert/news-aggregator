"""Resolve and execute one research run through a user's verified BYOK model."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import httpx2
from django.conf import settings
from django.db import transaction
from django.db.models import F
from openai import OpenAI

from api.models import UserAIConnection, UserAIModelConfig
from api.services.ai_credentials import (
    CredentialEncryptionUnavailable,
    CredentialUnavailable,
    decrypt_credential,
    require_active_connection,
)
from api.services.ai_execution import (
    ExecutionSnapshot,
    ModelSelectionError,
    deserialize_execution_snapshot,
    resolve_execution,
    serialize_execution_snapshot,
)
from api.services.ai_model_registry import get_model_preset
from api.services.ai_model_test import gateway_is_configured
from api.services.ai_registry import get_profile


PROXY_TIMEOUT_SECONDS = 120
MAX_RESEARCH_OUTPUT_TOKENS = 8000


class ResearchExecutionError(RuntimeError):
    """A fixed safe failure for a BYOK research execution."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ResearchExecution:
    snapshot: ExecutionSnapshot
    catalog_model_id: str
    catalog_version: str
    model_alias: str
    provider_key: str


def _safe_model_error(error: ModelSelectionError) -> ResearchExecutionError:
    code = error.code if error.code in {
        'authentication_required', 'invalid_task_kind', 'model_not_found',
        'model_not_configured', 'model_unavailable', 'model_reselection_required',
    } else 'model_unavailable'
    return ResearchExecutionError(code)


def _validate_document(document, *, user_id: int, decrypt_key: bool) -> ResearchExecution:
    if not isinstance(document, dict) or set(document) != {
        'version', 'execution', 'catalog_model_id', 'catalog_version',
    } or document.get('version') != 1:
        raise ResearchExecutionError('execution_changed')
    if not isinstance(document.get('catalog_model_id'), str) or not document['catalog_model_id']:
        raise ResearchExecutionError('execution_changed')
    if not isinstance(document.get('catalog_version'), str) or not document['catalog_version']:
        raise ResearchExecutionError('execution_changed')
    try:
        snapshot = deserialize_execution_snapshot(document['execution'])
    except ModelSelectionError:
        raise ResearchExecutionError('execution_changed') from None
    if snapshot.user_id != user_id or snapshot.task_kind != 'deep_research':
        raise ResearchExecutionError('execution_changed')

    config = UserAIModelConfig.objects.select_related('connection').filter(
        pk=snapshot.model_config_id,
        connection_id=snapshot.connection_id,
        connection__user_id=snapshot.user_id,
        connection__is_deleted=False,
    ).first()
    if config is None:
        raise ResearchExecutionError('execution_changed')
    connection = config.connection
    if (
        not connection.is_enabled
        or not connection.credential_ciphertext
        or not connection.encryption_key_id
        or connection.credential_epoch != snapshot.credential_epoch
        or connection.provider_id != snapshot.provider_id
        or connection.endpoint_profile != snapshot.endpoint_profile
        or connection.endpoint_profile_version != snapshot.endpoint_profile_version
        or config.config_revision != snapshot.config_revision
        or config.model_id != snapshot.model_id
    ):
        raise ResearchExecutionError('execution_changed')

    if (
        config.verification_status != 'verified'
        or config.verified_credential_epoch != snapshot.credential_epoch
        or config.verified_config_revision != snapshot.config_revision
        or config.verified_endpoint_profile_version != snapshot.endpoint_profile_version
        or not isinstance(config.capability_snapshot, dict)
        or config.capability_snapshot.get('tools') != 'supported'
    ):
        raise ResearchExecutionError('research_tools_unverified')

    preset = get_model_preset(document['catalog_model_id'], connection.provider_id)
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    if (
        preset is None
        or config.catalog_model_id != document['catalog_model_id']
        or config.catalog_version != document['catalog_version']
        or preset['catalog_version'] != document['catalog_version']
        or preset['model_id'] != snapshot.model_id
        or preset['proxy_model_alias'] != config.proxy_model_alias
        or profile is None
        or profile['version'] != snapshot.endpoint_profile_version
    ):
        raise ResearchExecutionError('model_route_unavailable')

    if not settings.AI_BYOK_ENABLED:
        raise ResearchExecutionError('byok_disabled')
    if not gateway_is_configured(
        settings.AI_BYOK_GATEWAY_URL,
        settings.AI_BYOK_GATEWAY_PROJECT_KEY,
    ):
        raise ResearchExecutionError('gateway_unavailable')

    provider_key = ''
    try:
        active_connection = require_active_connection(
            user_id=snapshot.user_id,
            connection_id=snapshot.connection_id,
            expected_epoch=snapshot.credential_epoch,
        )
        if decrypt_key:
            provider_key = decrypt_credential(active_connection)
    except CredentialEncryptionUnavailable:
        raise ResearchExecutionError('credential_storage_unavailable') from None
    except CredentialUnavailable:
        raise ResearchExecutionError('execution_changed') from None

    return ResearchExecution(
        snapshot=snapshot,
        catalog_model_id=document['catalog_model_id'],
        catalog_version=document['catalog_version'],
        model_alias=preset['proxy_model_alias'],
        provider_key=provider_key,
    )


def prepare_research_execution_snapshot(user) -> dict[str, object]:
    """Freeze the selected, verified model without storing the provider key."""
    try:
        snapshot = resolve_execution(user, 'deep_research')
    except ModelSelectionError as error:
        raise _safe_model_error(error) from None
    config = UserAIModelConfig.objects.filter(
        pk=snapshot.model_config_id,
        connection__user_id=snapshot.user_id,
        connection__is_deleted=False,
    ).first()
    if config is None:
        raise ResearchExecutionError('model_not_found')
    document = {
        'version': 1,
        'execution': serialize_execution_snapshot(snapshot),
        'catalog_model_id': config.catalog_model_id,
        'catalog_version': config.catalog_version,
    }
    _validate_document(document, user_id=user.pk, decrypt_key=False)
    return document


def load_research_execution(document, *, user_id: int) -> ResearchExecution:
    """Load the queued snapshot and decrypt only that owner's current key."""
    return _validate_document(document, user_id=user_id, decrypt_key=True)


def validate_research_execution_snapshot(document, *, user_id: int) -> None:
    """Validate a queued run before an explicit resume may dispatch it."""
    _validate_document(document, user_id=user_id, decrypt_key=False)


def assert_research_execution_current(execution: ResearchExecution) -> None:
    """Fence model edits, key rotation, route changes and feature disablement."""
    document = {
        'version': 1,
        'execution': serialize_execution_snapshot(execution.snapshot),
        'catalog_model_id': execution.catalog_model_id,
        'catalog_version': execution.catalog_version,
    }
    _validate_document(document, user_id=execution.snapshot.user_id, decrypt_key=False)


def lock_research_execution_for_commit(execution: ResearchExecution) -> None:
    """Serialize result commit with credential revocation and model edits.

    Call inside the result transaction. The conditional no-op connection update
    is the first SQLite write and a row lock on databases that support row
    locking; the selected model row is then locked before the final snapshot
    check. A revocation that commits first makes the epoch predicate fail.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('research execution commit fence requires an atomic transaction')
    snapshot = execution.snapshot
    changed = UserAIConnection.objects.filter(
        pk=snapshot.connection_id,
        user_id=snapshot.user_id,
        is_enabled=True,
        is_deleted=False,
        credential_epoch=snapshot.credential_epoch,
        credential_ciphertext__gt='',
        encryption_key_id__gt='',
        provider_id=snapshot.provider_id,
        endpoint_profile=snapshot.endpoint_profile,
        endpoint_profile_version=snapshot.endpoint_profile_version,
    ).update(credential_epoch=F('credential_epoch'))
    if not changed:
        raise ResearchExecutionError('execution_changed')

    config = UserAIModelConfig.objects.select_for_update().filter(
        pk=snapshot.model_config_id,
        connection_id=snapshot.connection_id,
        connection__user_id=snapshot.user_id,
    ).first()
    if config is None:
        raise ResearchExecutionError('execution_changed')
    assert_research_execution_current(execution)


@contextmanager
def open_proxy_client():
    """Open one no-retry SDK client pinned to the configured server-side Proxy."""
    if not gateway_is_configured(
        settings.AI_BYOK_GATEWAY_URL,
        settings.AI_BYOK_GATEWAY_PROJECT_KEY,
    ):
        raise ResearchExecutionError('gateway_unavailable')
    http_client = httpx2.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx2.Timeout(PROXY_TIMEOUT_SECONDS, connect=10),
    )
    client = None
    try:
        client = OpenAI(
            api_key=settings.AI_BYOK_GATEWAY_PROJECT_KEY,
            base_url=f'{settings.AI_BYOK_GATEWAY_URL.rstrip("/")}/v1',
            http_client=http_client,
            max_retries=0,
            timeout=PROXY_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        http_client.close()
        if isinstance(exc, ResearchExecutionError):
            raise
        # SDK/HTTP exceptions may include user content or credentials.
        raise ResearchExecutionError('gateway_unavailable') from None
    try:
        yield client
    finally:
        if client is not None:
            client.close()
