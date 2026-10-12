"""Resolve a user's BYOK model choice into a secret-free immutable snapshot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from django.db import transaction

from api.models import USER_AI_TASK_PREFERENCE_CHOICES, UserAIConnection, UserAIModelConfig, UserAITaskPreference


TASK_KINDS = tuple(kind for kind, _label in USER_AI_TASK_PREFERENCE_CHOICES)
TASK_SPECIFIC_KINDS = tuple(kind for kind in TASK_KINDS if kind != 'default')


class ModelSelectionError(Exception):
    """A safe, user-actionable model selection error with no provider details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionSnapshot:
    user_id: int
    task_kind: str
    selected_by_task_kind: str
    model_config_id: str
    connection_id: str
    provider_id: str
    endpoint_profile: str
    endpoint_profile_version: int
    credential_epoch: int
    config_revision: int
    model_id: str
    digest: str


def _active_config_for_user(*, user_id: int, model_config_id) -> UserAIModelConfig:
    connection_id = UserAIModelConfig.objects.filter(
        pk=model_config_id,
        connection__user_id=user_id,
    ).values_list('connection_id', flat=True).first()
    if connection_id is None:
        raise ModelSelectionError('model_not_found')
    connection = UserAIConnection.objects.select_for_update().filter(
        pk=connection_id,
        user_id=user_id,
    ).first()
    if connection is None:
        raise ModelSelectionError('model_not_found')
    config = UserAIModelConfig.objects.select_for_update().filter(
        pk=model_config_id,
        connection_id=connection.pk,
    ).first()
    if config is None:
        raise ModelSelectionError('model_not_found')
    config.connection = connection
    if (
        connection.is_deleted
        or not connection.is_enabled
        or not connection.credential_ciphertext
        or not connection.encryption_key_id
    ):
        raise ModelSelectionError('model_unavailable')
    return config


def _snapshot(*, user_id: int, task_kind: str, selected_by_task_kind: str, config: UserAIModelConfig) -> ExecutionSnapshot:
    connection = config.connection
    values = {
        'user_id': user_id,
        'task_kind': task_kind,
        'selected_by_task_kind': selected_by_task_kind,
        'model_config_id': str(config.pk),
        'connection_id': str(connection.pk),
        'provider_id': connection.provider_id,
        'endpoint_profile': connection.endpoint_profile,
        'endpoint_profile_version': connection.endpoint_profile_version,
        'credential_epoch': connection.credential_epoch,
        'config_revision': config.config_revision,
        'model_id': config.model_id,
    }
    digest = hashlib.sha256(
        json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8'),
    ).hexdigest()
    return ExecutionSnapshot(**values, digest=digest)


def resolve_execution(user, task_kind: str, model_config_id=None) -> ExecutionSnapshot:
    """Resolve an explicit override or saved preference without any credential fallback.

    A task-specific null preference inherits the user's explicit default. A missing,
    deleted, or disabled selected model fails closed. Platform and subscription
    credentials are outside this resolver's contract.
    """
    if not getattr(user, 'is_authenticated', False) or not getattr(user, 'pk', None):
        raise ModelSelectionError('authentication_required')
    if task_kind not in TASK_KINDS:
        raise ModelSelectionError('invalid_task_kind')

    user_id = user.pk
    with transaction.atomic():
        if model_config_id is not None:
            config = _active_config_for_user(user_id=user_id, model_config_id=model_config_id)
            return _snapshot(
                user_id=user_id,
                task_kind=task_kind,
                selected_by_task_kind='explicit',
                config=config,
            )

        preference_kinds = (task_kind,) if task_kind == 'default' else (task_kind, 'default')
        preferences_by_kind = {
            preference.task_kind: preference
            for preference in UserAITaskPreference.objects.select_for_update().filter(
                user_id=user_id,
                task_kind__in=preference_kinds,
            ).order_by('task_kind')
        }
        preference = preferences_by_kind.get(task_kind)
        selected_by = task_kind
        if preference is not None and preference.requires_reselection:
            raise ModelSelectionError('model_reselection_required')

        config = preference.model_config if preference is not None else None
        if config is None and task_kind != 'default':
            default_preference = preferences_by_kind.get('default')
            if default_preference is not None and default_preference.requires_reselection:
                raise ModelSelectionError('model_reselection_required')
            config = default_preference.model_config if default_preference is not None else None
            selected_by = 'default'

        if config is None:
            raise ModelSelectionError('model_not_configured')
        config = _active_config_for_user(user_id=user_id, model_config_id=config.pk)
        return _snapshot(
            user_id=user_id,
            task_kind=task_kind,
            selected_by_task_kind=selected_by,
            config=config,
        )
