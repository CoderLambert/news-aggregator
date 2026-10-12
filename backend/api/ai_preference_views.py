"""Owner-scoped, explicit BYOK task model preferences."""

from __future__ import annotations

from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import AnonymousCsrfSessionAuthentication
from api.models import USER_AI_TASK_PREFERENCE_CHOICES, UserAIModelConfig, UserAITaskPreference
from api.public_policy import policy_error


TASK_KINDS = tuple(kind for kind, _label in USER_AI_TASK_PREFERENCE_CHOICES)


class _StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({'request': '请求字段无效'})
        return super().to_internal_value(data)


class PreferenceEntrySerializer(_StrictSerializer):
    task_kind = serializers.ChoiceField(choices=TASK_KINDS)
    model_config_id = serializers.UUIDField(allow_null=True)


class TaskPreferencesPatchSerializer(_StrictSerializer):
    preferences = PreferenceEntrySerializer(many=True, allow_empty=False)

    def validate_preferences(self, entries):
        kinds = [entry['task_kind'] for entry in entries]
        if len(kinds) != len(TASK_KINDS) or set(kinds) != set(TASK_KINDS):
            raise serializers.ValidationError('必须完整提交五种用途的偏好')
        return entries


def _require_feature():
    if not settings.AI_BYOK_ENABLED:
        return policy_error('byok_disabled')
    return None


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    return response


def _selected_config_is_active(config: UserAIModelConfig) -> bool:
    connection = config.connection
    return bool(
        not connection.is_deleted
        and connection.is_enabled
        and connection.credential_ciphertext
        and connection.encryption_key_id
    )


def _preference_payload(preference) -> dict:
    config = preference.model_config
    if config is not None and config.connection.user_id != preference.user_id:
        config = None
        selection_state = 'needs_reselection'
    elif preference.requires_reselection:
        selection_state = 'needs_reselection'
    elif config is None:
        selection_state = 'unset' if preference.task_kind == 'default' else 'inherit_default'
    elif _selected_config_is_active(config):
        selection_state = 'available'
    else:
        selection_state = 'needs_reselection'

    model = None
    if config is not None:
        model = {
            'id': str(config.pk),
            'model_id': config.model_id,
            'display_name': config.display_name,
            'connection_id': str(config.connection_id),
        }
    return {
        'task_kind': preference.task_kind,
        'model_config_id': str(config.pk) if config is not None else None,
        'selection_state': selection_state,
        'model': model,
    }


def _preferences_payload(user):
    rows = {
        row.task_kind: row
        for row in UserAITaskPreference.objects.select_related('model_config__connection').filter(user=user)
    }
    payload = []
    for task_kind in TASK_KINDS:
        row = rows.get(task_kind)
        if row is None:
            row = SimpleNamespace(
                task_kind=task_kind,
                model_config=None,
                requires_reselection=False,
            )
        payload.append(_preference_payload(row))
    return {'preferences': payload}


class UserAITaskPreferencesView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response

    def get(self, request):
        denied = _require_feature()
        if denied:
            return denied
        if (
            set(request.query_params) - {'lang'}
            or len(request.query_params.getlist('lang')) > 1
            or request.query_params.get('lang') not in (None, 'zh', 'en')
        ):
            return _no_store(Response({'error_code': 'invalid_query'}, status=status.HTTP_400_BAD_REQUEST))
        return _no_store(Response(_preferences_payload(request.user)))

    def patch(self, request):
        denied = _require_feature()
        if denied:
            return denied
        serializer = TaskPreferencesPatchSerializer(data=request.data)
        if not serializer.is_valid():
            return _no_store(Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST))

        entries = serializer.validated_data['preferences']
        model_ids = {entry['model_config_id'] for entry in entries if entry['model_config_id'] is not None}
        with transaction.atomic():
            get_user_model().objects.select_for_update().only('pk').get(pk=request.user.pk)
            configs = list(
                UserAIModelConfig.objects.select_for_update().select_related('connection').filter(
                    pk__in=model_ids,
                    connection__user=request.user,
                )
            )
            configs_by_id = {config.pk: config for config in configs}
            if len(configs_by_id) != len(model_ids):
                return _no_store(Response({'error_code': 'model_not_found'}, status=status.HTTP_404_NOT_FOUND))
            if any(not _selected_config_is_active(config) for config in configs):
                return _no_store(Response({'error_code': 'model_connection_unavailable'}, status=status.HTTP_409_CONFLICT))
            for entry in entries:
                preference, _created = UserAITaskPreference.objects.select_for_update().get_or_create(
                    user=request.user,
                    task_kind=entry['task_kind'],
                )
                preference.model_config = configs_by_id.get(entry['model_config_id'])
                preference.requires_reselection = False
                preference.save(update_fields=['model_config', 'requires_reselection', 'updated_at'])

        return _no_store(Response(_preferences_payload(request.user)))
