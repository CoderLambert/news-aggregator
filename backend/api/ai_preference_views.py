"""T03 owner-only, revisioned model purpose preferences; GET is side-effect free."""
from rest_framework import serializers
from rest_framework.response import Response

from api.ai_connection_views import ConnectionView, StrictSerializer, error
from api.ai_preference_models import TASK_KINDS
from api.services.ai_task_preferences import (
    ModelSelectionError, read_preferences, save_preferences,
)


class TaskSelectionSerializer(StrictSerializer):
    task_kind = serializers.ChoiceField(choices=TASK_KINDS)
    model_config_id = serializers.UUIDField(allow_null=True)


class TaskPreferencesPatchSerializer(StrictSerializer):
    revision = serializers.IntegerField(min_value=0)
    preferences = TaskSelectionSerializer(many=True, allow_empty=False)

    def validate_preferences(self, values):
        kinds = [entry['task_kind'] for entry in values]
        if len(kinds) != len(TASK_KINDS) or set(kinds) != set(TASK_KINDS):
            raise serializers.ValidationError('all_task_kinds_required')
        return values


def _selection_error(exc):
    status = 404 if exc.code == 'model_not_found' else (
        403 if exc.code == 'authentication_required' else 409
    )
    return error(exc.code, status)


class AITaskPreferencesView(ConnectionView):
    def get(self, request):
        query = request.query_params
        if (set(query) - {'lang'} or len(query.getlist('lang')) > 1
                or query.get('lang') not in (None, 'zh', 'en')):
            return error('invalid_query')
        try:
            return Response(read_preferences(request.user))
        except ModelSelectionError as exc:
            return _selection_error(exc)

    def patch(self, request):
        serializer = TaskPreferencesPatchSerializer(data=request.data)
        if not serializer.is_valid():
            return error('invalid_request')
        try:
            result = save_preferences(
                request.user, serializer.validated_data['revision'],
                serializer.validated_data['preferences'],
            )
        except ModelSelectionError as exc:
            return _selection_error(exc)
        return Response(result)
