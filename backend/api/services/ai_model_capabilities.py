"""Shared T02 capability receipts used by T03 without importing API views."""
from api.services.ai_model_registry import get_trusted_preset

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
            and get_trusted_preset(connection, model.model_id) is not None
        )
        value = receipt.get('status') if valid else 'unknown'
        result[kind] = value if value in ('supported', 'unsupported') else 'unknown'
    return result


def verified_for_task(model, task_kind):
    capabilities = current_capabilities(model)
    return capabilities['text'] == 'supported' and (
        task_kind != 'deep_research' or capabilities['tools'] == 'supported'
    )
