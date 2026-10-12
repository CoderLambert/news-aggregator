"""Owner-scoped BYOK model catalog and configuration CRUD."""

from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from django.conf import settings
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import AnonymousCsrfSessionAuthentication
from api.models import UserAIConnection, UserAIModelConfig
from api.public_policy import policy_error
from api.services.ai_model_registry import (
    MODEL_CATALOG_SOURCES,
    MODEL_CATALOG_VERSION,
    find_model_preset,
    get_model_preset,
    model_catalog,
)
from api.services.ai_registry import PROFILES_BY_ID


CAPABILITY_NAMES = ('text', 'tools', 'structured_output', 'thinking', 'stream')
UNKNOWN_CAPABILITIES = {name: 'unknown' for name in CAPABILITY_NAMES}
MODEL_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$')
SECRET_LIKE_PATTERN = re.compile(r'(?i)(?:bearer\s|(?:sk|ark|AIza)[-_])|[A-Za-z0-9_-]{24,}')


class NoStoreAPIView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response


class _StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            extra = set(data) - set(self.fields)
            if extra:
                raise serializers.ValidationError({'request': '请求字段无效'})
        return super().to_internal_value(data)


class ModelCreateSerializer(_StrictSerializer):
    connection_id = serializers.UUIDField()
    model_id = serializers.CharField(max_length=160, required=False, trim_whitespace=False)
    catalog_model_id = serializers.CharField(max_length=160, required=False, trim_whitespace=False)
    display_name = serializers.CharField(max_length=64, required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        has_model_id = 'model_id' in attrs
        has_catalog_id = 'catalog_model_id' in attrs
        if has_model_id == has_catalog_id:
            raise serializers.ValidationError({'request': '请选择目录模型或输入模型 ID'})
        if has_model_id:
            attrs['model_id'] = _validate_model_id(attrs['model_id'])
        if attrs.get('display_name'):
            _validate_display_name(attrs['display_name'])
        return attrs


class ModelPatchSerializer(_StrictSerializer):
    model_id = serializers.CharField(max_length=160, required=False, trim_whitespace=False)
    display_name = serializers.CharField(max_length=64, required=False, allow_blank=False, trim_whitespace=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({'request': '至少需要一个可更新字段'})
        if 'model_id' in attrs:
            attrs['model_id'] = _validate_model_id(attrs['model_id'])
        if 'display_name' in attrs:
            _validate_display_name(attrs['display_name'])
        return attrs


def _validate_model_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or '://' in value
        or re.match(r'(?i)^(?:sk|ark|AIza)[-_]', value)
        or not MODEL_ID_PATTERN.fullmatch(value)
    ):
        raise serializers.ValidationError('模型 ID 格式无效')
    return value


def _validate_display_name(value: str) -> str:
    if SECRET_LIKE_PATTERN.search(value):
        raise serializers.ValidationError('名称不能包含凭据内容')
    return value


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    return response


def _require_feature():
    if not settings.AI_BYOK_ENABLED:
        return policy_error('byok_disabled')
    return None


def _current_verification_status(config: UserAIModelConfig) -> str:
    if config.verification_status == 'not_tested':
        return 'not_tested'
    connection = config.connection
    if (
        config.verified_credential_epoch != connection.credential_epoch
        or config.verified_config_revision != config.config_revision
        or config.verified_endpoint_profile_version != connection.endpoint_profile_version
    ):
        return 'stale'
    return config.verification_status


def _model_payload(config: UserAIModelConfig) -> dict:
    return {
        'id': str(config.pk),
        'connection_id': str(config.connection_id),
        'model_id': config.model_id,
        'display_name': config.display_name,
        'source': 'catalog' if config.catalog_model_id else 'manual',
        'catalog_model_id': config.catalog_model_id,
        'catalog_version': config.catalog_version,
        'catalog_source_url': config.catalog_source_url,
        'provider_claims': config.catalog_claims,
        'context_window_tokens': config.context_window_tokens,
        'max_output_tokens': config.max_output_tokens,
        'has_trusted_context_limit': config.context_window_tokens is not None,
        'config_revision': config.config_revision,
        'verification_status': _current_verification_status(config),
        'capabilities': config.capability_snapshot,
        'last_tested_at': config.last_tested_at.isoformat() if config.last_tested_at else None,
        'updated_at': config.updated_at.isoformat(),
    }


def _catalog_metadata(provider_id: str, *, catalog_model_id: str = '', model_id: str = '') -> dict:
    preset = (
        get_model_preset(catalog_model_id, provider_id)
        if catalog_model_id
        else find_model_preset(model_id, provider_id)
    )
    if preset is None:
        return {
            'catalog_model_id': '',
            'catalog_version': '',
            'proxy_model_alias': '',
            'catalog_source_url': '',
            'catalog_claims': {},
            'context_window_tokens': None,
            'max_output_tokens': None,
        }
    return {
        'catalog_model_id': preset['catalog_model_id'],
        'catalog_version': preset['catalog_version'],
        'proxy_model_alias': preset['proxy_model_alias'],
        'catalog_source_url': preset['source_url'],
        'catalog_claims': preset['provider_claims'],
        'context_window_tokens': preset['context_window_tokens'],
        'max_output_tokens': preset['max_output_tokens'],
    }


class AIModelCatalogView(NoStoreAPIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _require_feature()
        if denied:
            return denied
        if set(request.query_params) - {'provider_id'}:
            return _no_store(Response({'error_code': 'invalid_query'}, status=status.HTTP_400_BAD_REQUEST))
        provider_id = request.query_params.get('provider_id')
        if provider_id and not any(item['provider_id'] == provider_id for item in PROFILES_BY_ID.values()):
            return _no_store(Response({'error_code': 'invalid_provider'}, status=status.HTTP_400_BAD_REQUEST))
        sources = {provider_id: MODEL_CATALOG_SOURCES[provider_id]} if provider_id in MODEL_CATALOG_SOURCES else {}
        try:
            models = model_catalog(provider_id)
        except Exception:
            return _no_store(Response(
                {
                    'catalog_version': MODEL_CATALOG_VERSION,
                    'provider_id': provider_id,
                    'sources': sources,
                    'models': [],
                    'catalog_available': False,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            ))
        return _no_store(Response({
            'catalog_version': MODEL_CATALOG_VERSION,
            'provider_id': provider_id,
            'sources': sources,
            'models': models,
            'catalog_available': True,
        }))


class UserAIModelListCreateView(NoStoreAPIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _require_feature()
        if denied:
            return denied
        if request.query_params:
            return _no_store(Response({'error_code': 'invalid_query'}, status=status.HTTP_400_BAD_REQUEST))
        rows = UserAIModelConfig.objects.select_related('connection').filter(
            connection__user=request.user,
            connection__is_deleted=False,
        ).order_by('created_at', 'id')
        return _no_store(Response({'models': [_model_payload(row) for row in rows]}))

    def post(self, request):
        denied = _require_feature()
        if denied:
            return denied
        serializer = ModelCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _no_store(Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST))
        values = serializer.validated_data
        connection = UserAIConnection.objects.filter(
            pk=values['connection_id'], user=request.user, is_deleted=False,
        ).first()
        if connection is None:
            return _no_store(Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND))

        preset = None
        if 'catalog_model_id' in values:
            preset = get_model_preset(values['catalog_model_id'], connection.provider_id)
            if preset is None:
                return _no_store(Response({'error_code': 'catalog_model_unavailable'}, status=status.HTTP_400_BAD_REQUEST))
            model_id = preset['model_id']
        else:
            model_id = values['model_id']
            preset = find_model_preset(model_id, connection.provider_id)

        if preset is None:
            display_name = values.get('display_name') or model_id[:64]
            metadata = _catalog_metadata(connection.provider_id, model_id=model_id)
        else:
            display_name = values.get('display_name') or preset['display_name']
            metadata = _catalog_metadata(connection.provider_id, catalog_model_id=preset['catalog_model_id'])
        _validate_display_name(display_name)
        model = UserAIModelConfig(
            connection=connection,
            model_id=model_id,
            display_name=display_name,
            capability_snapshot=dict(UNKNOWN_CAPABILITIES),
            **metadata,
        )
        try:
            with transaction.atomic():
                model.save(force_insert=True)
        except IntegrityError:
            return _no_store(Response({'error_code': 'model_already_exists'}, status=status.HTTP_409_CONFLICT))
        model.connection = connection
        return _no_store(Response(_model_payload(model), status=status.HTTP_201_CREATED))


class UserAIModelDetailView(NoStoreAPIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, model_id):
        denied = _require_feature()
        if denied:
            return denied
        with transaction.atomic():
            model = UserAIModelConfig.objects.select_for_update().select_related('connection').filter(
                pk=model_id,
                connection__user=request.user,
                connection__is_deleted=False,
            ).first()
            if model is None:
                return _no_store(Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND))
            serializer = ModelPatchSerializer(data=request.data)
            if not serializer.is_valid():
                return _no_store(Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST))
            values = serializer.validated_data
            if 'model_id' in values and values['model_id'] != model.model_id:
                model.model_id = values['model_id']
                model.config_revision += 1
                model.verification_status = 'not_tested'
                model.verified_credential_epoch = None
                model.verified_config_revision = None
                model.verified_endpoint_profile_version = None
                model.last_tested_at = None
                model.last_safe_error_code = ''
                model.capability_snapshot = dict(UNKNOWN_CAPABILITIES)
                model.display_name = values.get('display_name') or model.model_id[:64]
                model_metadata = _catalog_metadata(model.connection.provider_id, model_id=model.model_id)
                for field, value in model_metadata.items():
                    setattr(model, field, value)
            if 'display_name' in values:
                model.display_name = values['display_name']
            try:
                model.save()
            except IntegrityError:
                return _no_store(Response({'error_code': 'model_already_exists'}, status=status.HTTP_409_CONFLICT))
        return _no_store(Response(_model_payload(model)))

    def delete(self, request, model_id):
        denied = _require_feature()
        if denied:
            return denied
        deleted, _ = UserAIModelConfig.objects.filter(
            pk=model_id,
            connection__user=request.user,
            connection__is_deleted=False,
        ).delete()
        if not deleted:
            return _no_store(Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND))
        return _no_store(Response({'deleted': True}))
