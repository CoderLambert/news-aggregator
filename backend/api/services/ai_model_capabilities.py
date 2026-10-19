"""Shared T02 capability receipts used by T03 without importing API views."""
from api.services.ai_model_registry import get_trusted_route, supports_task_route
from api.ai_model_models import AIModelProbeAttempt

CAPABILITY_KINDS = ('text', 'tools')


def current_capabilities(model):
    connection = model.connection
    result = {}
    for kind in CAPABILITY_KINDS:
        receipt = model.capability_results.get(kind)
        last_attempt = getattr(model, f'last_{kind}_attempt')
        valid = (
            not model.is_deleted
            and isinstance(receipt, dict)
            and receipt.get('attempt_id') == str(last_attempt)
            and receipt.get('config_revision') == model.config_revision
            and receipt.get('credential_epoch') == connection.credential_epoch
            and receipt.get('credential_version') == connection.credential_version
            and receipt.get('endpoint_profile') == connection.endpoint_profile
            and receipt.get('endpoint_profile_version') == connection.endpoint_profile_version
            and connection.is_enabled and not connection.is_deleted
            and get_trusted_route(connection, model.model_id) is not None
        )
        value = receipt.get('status') if valid else 'unknown'
        result[kind] = value if value in ('supported', 'unsupported') else 'unknown'
    return result


def verified_for_task(model, task_kind):
    """T03 requires an actual current successful T02 audit receipt for each capability."""
    route = get_trusted_route(model.connection, model.model_id)
    if not route or not supports_task_route(model.connection, model.model_id, task_kind):
        return False
    required = ('text', 'tools') if task_kind == 'deep_research' else ('text',)
    capabilities = current_capabilities(model)
    for kind in required:
        if capabilities[kind] != 'supported':
            return False
        attempt_id = getattr(model, f'last_{kind}_attempt')
        if not AIModelProbeAttempt.objects.filter(
            pk=attempt_id, user_id=model.connection.user_id,
            model_config_id=model.pk, connection_id=model.connection_id,
            model_id=model.model_id, model_revision=model.config_revision,
            credential_epoch=model.connection.credential_epoch,
            credential_version=model.connection.credential_version,
            endpoint_profile=model.connection.endpoint_profile,
            endpoint_profile_version=model.connection.endpoint_profile_version,
            proxy_alias=route['proxy_alias'],
            probe_kind=kind, status='succeeded',
        ).exists():
            return False
    return True
