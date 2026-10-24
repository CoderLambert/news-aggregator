"""T03 owner-scoped, atomic model preferences and immutable task selections.

A saved preference cannot authorize inference by itself. The resolver checks
T01 credential identity and T02 *current* proof receipts. A future business
worker must also apply the T01 enqueue/claim/dispatch/commit fence on its own
lease, and recheck this model selection before publishing any result.
"""
from dataclasses import dataclass

from django.db import transaction

from api.ai_model_models import UserAIModelConfig
from api.ai_preference_models import TASK_KINDS, UserAITaskPreference


from api.services.ai_credentials import (
    ConnectionSnapshot, CredentialUnavailable, CredentialEncryptionUnavailable, lock_owner,
    require_active_snapshot, snapshot_connection, execution_credential,
)
from api.services.ai_model_capabilities import verified_for_task
from api.services.ai_model_registry import get_trusted_route, supports_task_route

SUBSCRIPTION_TASKS = frozenset({
    'article_qa', 'full_translation', 'question_suggestions', 'deep_research',
})


class ModelSelectionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _rows(user_id):
    entries = list(
        UserAITaskPreference.objects.filter(user_id=user_id).select_related(
            'model_config__connection',
        )
    )
    kinds = {entry.task_kind for entry in entries}
    if entries and (len(entries) != len(TASK_KINDS) or kinds != set(TASK_KINDS)
                    or len({entry.revision for entry in entries}) != 1):
        raise ModelSelectionError('preferences_inconsistent')
    return {entry.task_kind: entry for entry in entries}, entries[0].revision if entries else 0


def _subscription_info(user):
    from api.services.chatgpt_subscription import active_connection_for_user
    from api.services.research.subscription_execution import tools_supported
    connection = active_connection_for_user(user)
    if connection is None:
        return {
            'state': 'not_connected', 'model_id': None,
            'display_name': None, 'research_eligible': False,
        }
    if connection.needs_reauth or not connection.connected:
        state = 'needs_reauth'
    elif not connection.selected_model:
        state = 'model_required'
    else:
        state = 'available'
    return {
        'state': state,
        'model_id': connection.selected_model or None,
        'display_name': connection.selected_model or None,
        'research_eligible': state == 'available' and tools_supported(connection),
    }


def _selected_state(preference, kind, owner_id, subscription):
    source = preference.selection_source if preference is not None else (
        'unset' if kind == 'default' else 'inherit'
    )
    if source in {'unset', 'inherit'}:
        expected = 'unset' if kind == 'default' else 'inherit'
        state = 'unset' if kind == 'default' else 'inherit_default'
        return (
            state if source == expected else 'needs_reselection',
            None,
            source,
        )
    if source == 'chatgpt_subscription':
        if kind not in SUBSCRIPTION_TASKS:
            return 'needs_verification', None, source
        state = subscription['state']
        available = state == 'available' and (
            kind != 'deep_research' or subscription['research_eligible']
        )
        return 'available' if available else 'needs_verification', None, source
    if source != 'byok' or preference is None or preference.model_config_id is None:
        return 'needs_reselection', None, source
    model = preference.model_config
    if model is None or model.connection.user_id != owner_id:
        return 'needs_reselection', None, source
    info = {
        'id': str(model.pk), 'connection_id': str(model.connection_id),
        'model_id': model.model_id, 'display_name': model.display_name,
        'research_eligible': verified_for_task(model, 'deep_research'),
    }
    connection = model.connection
    if (model.is_deleted or connection.is_deleted or not connection.is_enabled
            or not supports_task_route(connection, model.model_id, kind)):
        return 'needs_reselection', info, source
    try:
        execution_credential(connection)
    except (CredentialUnavailable, CredentialEncryptionUnavailable):
        return 'needs_reselection', info, source
    if not verified_for_task(model, kind):
        return 'needs_verification', info, source
    return 'available', info, source


def read_preferences(user):
    if not user or not getattr(user, 'is_authenticated', False) or not user.is_active:
        raise ModelSelectionError('authentication_required')
    rows, revision = _rows(user.pk)
    subscription = _subscription_info(user)
    preferences = []
    for kind in TASK_KINDS:
        row = rows.get(kind)
        status, info, source = _selected_state(
            row, kind, user.pk, subscription,
        )
        selected_id = str(row.model_config_id) if info is not None else None
        preferences.append({
            'task_kind': kind, 'selection_source': source,
            'model_config_id': selected_id,
            'selection_state': status, 'model': info,
        })
    return {
        'revision': revision, 'preferences': preferences,
        'subscription': subscription,
    }


def _require_model(owner_id, config):
    connection = config.connection
    if config.is_deleted or connection.user_id != owner_id:
        raise ModelSelectionError('model_not_found')
    try:
        identity = snapshot_connection(connection)
        require_active_snapshot(identity)
    except CredentialUnavailable:
        raise ModelSelectionError('model_connection_unavailable') from None
    route = get_trusted_route(connection, config.model_id)
    if route is None:
        raise ModelSelectionError('model_not_approved')
    return identity, route


def _require_for_task(owner_id, config, task_kind):
    identity, route = _require_model(owner_id, config)
    if not supports_task_route(config.connection, config.model_id, task_kind):
        raise ModelSelectionError('model_task_unavailable')
    if not verified_for_task(config, task_kind):
        raise ModelSelectionError('model_not_verified')
    return identity, route


def _validate_entry(entry, subscription):
    kind = entry['task_kind']
    source = entry['selection_source']
    model_id = entry['model_config_id']
    if kind == 'default':
        if source not in {'unset', 'byok'}:
            raise ModelSelectionError('selection_source_unavailable')
    elif source not in {'inherit', 'byok', 'chatgpt_subscription'}:
        raise ModelSelectionError('selection_source_unavailable')
    if source == 'byok':
        if model_id is None:
            raise ModelSelectionError('model_not_found')
    elif model_id is not None:
        raise ModelSelectionError('selection_source_invalid')
    if source == 'chatgpt_subscription':
        if kind not in SUBSCRIPTION_TASKS:
            raise ModelSelectionError('model_not_verified')
        if subscription['state'] != 'available':
            raise ModelSelectionError('subscription_unavailable')
        if kind == 'deep_research' and not subscription['research_eligible']:
            raise ModelSelectionError('model_not_verified')


@transaction.atomic
def save_preferences(user, expected_revision, entries):
    lock_owner(user.pk)
    stored, revision = _rows(user.pk)
    if revision != expected_revision:
        raise ModelSelectionError('preferences_changed')
    subscription = _subscription_info(user)
    for entry in entries:
        _validate_entry(entry, subscription)
    selected_ids = {
        entry['model_config_id'] for entry in entries
        if entry['selection_source'] == 'byok'
    }
    available = {
        model.pk: model for model in UserAIModelConfig.objects.select_related('connection').filter(
            pk__in=selected_ids, connection__user_id=user.pk, is_deleted=False,
        )
    }
    if len(available) != len(selected_ids):
        raise ModelSelectionError('model_not_found')
    for entry in entries:
        model_id = entry['model_config_id']
        if entry['selection_source'] == 'byok':
            _require_for_task(user.pk, available[model_id], entry['task_kind'])
    next_revision = revision + 1
    for entry in entries:
        row = stored.get(entry['task_kind'])
        model = available.get(entry['model_config_id'])
        if row is None:
            UserAITaskPreference.objects.create(
                user=user, task_kind=entry['task_kind'],
                selection_source=entry['selection_source'],
                model_config=model, revision=next_revision,
            )
        else:
            row.selection_source = entry['selection_source']
            row.model_config = model
            row.revision = next_revision
            row.save(update_fields=[
                'selection_source', 'model_config', 'revision', 'updated_at',
            ])
    return read_preferences(user)


@dataclass(frozen=True)
class TaskModelSnapshot:
    """Secret-free immutable selection; not a credential or billing approval."""
    user_id: int
    task_kind: str
    selected_by: str
    preference_revision: int
    model_config_id: str
    model_revision: int
    model_id: str
    proxy_alias: str
    connection: ConnectionSnapshot
    text_attempt_id: str
    tools_attempt_id: str | None


def resolve_task_model(user, task_kind, explicit_model_id=None):
    """Resolve for future T04+ workers; T03 never sends a provider request.

    A task-specific NULL inherits only the explicitly saved personal default.
    An explicit but invalid selection never falls back. An in-flight snapshot
    remains independent of later preference edits, but credential/model
    revocation still invalidates its eventual dispatch/commit.
    """
    if (not user or not getattr(user, 'is_authenticated', False)
            or type(getattr(user, 'pk', None)) is not int or not user.is_active):
        raise ModelSelectionError('authentication_required')
    if task_kind not in TASK_KINDS:
        raise ModelSelectionError('invalid_task_kind')
    with transaction.atomic():
        lock_owner(user.pk)
        stored, revision = _rows(user.pk)
        selected_by = 'explicit' if explicit_model_id is not None else task_kind
        if explicit_model_id is None:
            preference = stored.get(task_kind)
            source = preference.selection_source if preference is not None else (
                'unset' if task_kind == 'default' else 'inherit'
            )
            selected_id = preference.model_config_id if source == 'byok' and preference else None
            if source == 'chatgpt_subscription':
                raise ModelSelectionError('subscription_selected')
            if source == 'inherit' and task_kind != 'default':
                default = stored.get('default')
                if default is not None and default.selection_source == 'byok':
                    selected_id = default.model_config_id
                    selected_by = 'default'
            elif source not in {'byok', 'unset'}:
                raise ModelSelectionError('preferences_inconsistent')
        else:
            selected_id = explicit_model_id
        if selected_id is None:
            raise ModelSelectionError('model_not_configured')
        try:
            model = UserAIModelConfig.objects.select_related('connection').filter(
                pk=selected_id, connection__user_id=user.pk, is_deleted=False,
            ).first()
        except (ValueError, TypeError):
            model = None
        if model is None:
            raise ModelSelectionError('model_not_found')
        identity, route = _require_for_task(user.pk, model, task_kind)
        return TaskModelSnapshot(
            user_id=user.pk, task_kind=task_kind,
            selected_by=selected_by, preference_revision=revision,
            model_config_id=str(model.pk), model_revision=model.config_revision,
            model_id=model.model_id, proxy_alias=route['proxy_alias'],
            connection=identity, text_attempt_id=str(model.last_text_attempt),
            tools_attempt_id=str(model.last_tools_attempt) if task_kind == 'deep_research' else None,
        )


def require_task_model_snapshot(snapshot, *, owner_id):
    """Pure DB/fence verification for a future business worker's own short lock.

    Do not re-resolve preferences for old tasks; in-flight selection is fixed.
    Model revision, current receipt, endpoint and epoch MUST remain current.
    """
    if (type(snapshot) is not TaskModelSnapshot or type(owner_id) is not int
            or snapshot.user_id != owner_id or snapshot.task_kind not in TASK_KINDS
            or type(snapshot.connection) is not ConnectionSnapshot
            or snapshot.connection.user_id != owner_id):
        raise ModelSelectionError('execution_snapshot_invalid')
    try:
        connection = require_active_snapshot(snapshot.connection)
    except CredentialUnavailable:
        raise ModelSelectionError('execution_revoked') from None
    try:
        model = UserAIModelConfig.objects.select_related('connection').filter(
            pk=snapshot.model_config_id, connection=connection, is_deleted=False,
        ).first()
    except (ValueError, TypeError):
        model = None
    if (model is None or model.config_revision != snapshot.model_revision
            or model.model_id != snapshot.model_id
            or str(model.last_text_attempt) != snapshot.text_attempt_id
            or (snapshot.task_kind == 'deep_research'
                and str(model.last_tools_attempt) != snapshot.tools_attempt_id)):
        raise ModelSelectionError('execution_model_changed')
    route = get_trusted_route(connection, model.model_id)
    if route is None or route['proxy_alias'] != snapshot.proxy_alias or not verified_for_task(model, snapshot.task_kind):
        raise ModelSelectionError('execution_model_unverified')
    return model
