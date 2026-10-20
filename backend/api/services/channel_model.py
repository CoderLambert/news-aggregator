"""AG-05 immutable T03 model selection using the existing T01 credential fence."""
from dataclasses import asdict
from uuid import UUID

from django.conf import settings
from django.db import transaction
from api.services.ai_credentials import CredentialUnavailable, lock_owner, decode_connection_snapshot
from api.services.ai_task_preferences import TaskModelSnapshot, ModelSelectionError, resolve_task_model, require_task_model_snapshot
from api.services.ai_worker_fencing import check_at_claim, commit_result


class ClassificationAuthorizationChanged(ValueError):
    def __init__(self):
        super().__init__('authorization_changed')


def _feature():
    if (settings.PUBLIC_SITE_MODE != 'full' or not settings.PUBLIC_AI_ENABLED
            or not getattr(settings, 'AI_BYOK_ENABLED', False)):
        raise ClassificationAuthorizationChanged()


def capture_model(user, *, scope, model_config_id=None):
    _feature()
    if scope not in ('personal', 'site') or not user.is_active:
        raise ClassificationAuthorizationChanged()
    try:
        explicit_id = UUID(model_config_id) if model_config_id is not None else None
        if explicit_id is not None and str(explicit_id) != model_config_id:
            raise ValueError
        with transaction.atomic():
            lock_owner(user.pk)
            model = resolve_task_model(user, 'default', explicit_model_id=explicit_id)
            require_task_model_snapshot(model, owner_id=user.pk)
            return {'schema_version': 1, 'scope': scope, 'consent': True, 'model': asdict(model)}
    except (ValueError, TypeError, AttributeError, ModelSelectionError, CredentialUnavailable):
        raise ClassificationAuthorizationChanged() from None


def verify_model(payload, *, owner_id, scope):
    _feature()
    try:
        if (type(payload) is not dict or set(payload) != {'schema_version', 'scope', 'consent', 'model'}
                or type(payload['schema_version']) is not int or payload['schema_version'] != 1
                or payload['scope'] != scope or scope not in ('personal', 'site') or payload['consent'] is not True):
            raise ValueError
        raw = payload['model']
        if type(raw) is not dict or set(raw) != set(TaskModelSnapshot.__dataclass_fields__):
            raise ValueError
        raw = dict(raw)
        raw['connection'] = decode_connection_snapshot(raw.get('connection'))
        model = TaskModelSnapshot(**raw)
        if model.user_id != owner_id or model.task_kind != 'default':
            raise ValueError
        check_at_claim(connection_fence(model), task_owner_id=owner_id)
        require_task_model_snapshot(model, owner_id=owner_id)
        return model
    except (ValueError, TypeError, AttributeError, KeyError, ModelSelectionError, CredentialUnavailable):
        raise ClassificationAuthorizationChanged() from None


def connection_fence(model):
    return {'schema_version': 1, **asdict(model.connection)}


def commit_classification(payload, *, owner_id, scope, persist):
    model = verify_model(payload, owner_id=owner_id, scope=scope)
    def checked():
        verify_model(payload, owner_id=owner_id, scope=scope)
        return persist()
    return commit_result(connection_fence(model), task_owner_id=owner_id, persist=checked)
