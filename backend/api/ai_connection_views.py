"""Session-bound CRUD for a user's encrypted BYOK provider credentials."""

from __future__ import annotations

import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import AnonymousCsrfSessionAuthentication
from api.models import UserAIConnection
from api.public_policy import policy_error
from api.services.ai_credentials import (
    CredentialEncryptionUnavailable,
    CredentialUnavailable,
    decrypt_credential,
    encrypt_credential,
)
from api.services.ai_registry import PROFILES_BY_ID, get_profile, provider_catalog


class _StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            extra = set(data) - set(self.fields)
            if extra:
                raise serializers.ValidationError({'request': '请求字段无效'})
        return super().to_internal_value(data)


def _validate_display_name(value, *, api_key=''):
    if (
        (api_key and api_key in value)
        or re.search(r'(?i)(?:bearer\s|(?:sk|ark|AIza)[-_])', value)
        or re.search(r'[A-Za-z0-9_-]{24,}', value)
    ):
        raise serializers.ValidationError('名称不能包含凭据内容')
    return value


class ConnectionCreateSerializer(_StrictSerializer):
    provider_id = serializers.ChoiceField(choices=sorted({item['provider_id'] for item in PROFILES_BY_ID.values()}))
    endpoint_profile = serializers.ChoiceField(choices=sorted(PROFILES_BY_ID))
    display_name = serializers.CharField(max_length=64, allow_blank=True, required=False, trim_whitespace=True)
    api_key = serializers.CharField(max_length=4096, write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        profile = get_profile(attrs['provider_id'], attrs['endpoint_profile'])
        if profile is None:
            raise serializers.ValidationError({'endpoint_profile': '所选服务商端点无效'})
        api_key = attrs['api_key']
        if not api_key or api_key != api_key.strip() or any(ord(char) < 32 or ord(char) == 127 for char in api_key):
            raise serializers.ValidationError({'api_key': 'Key 格式无效'})
        display_name = attrs.get('display_name', '')
        _validate_display_name(display_name, api_key=api_key)
        attrs['profile'] = profile
        return attrs


class CredentialReplaceSerializer(_StrictSerializer):
    api_key = serializers.CharField(max_length=4096, write_only=True, trim_whitespace=False)

    def validate_api_key(self, value):
        if not value or value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise serializers.ValidationError('Key 格式无效')
        return value


class ConnectionPatchSerializer(_StrictSerializer):
    display_name = serializers.CharField(max_length=64, allow_blank=False, required=False, trim_whitespace=True)
    is_enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({'request': '至少需要一个可更新字段'})
        if 'display_name' in attrs:
            _validate_display_name(attrs['display_name'])
        return attrs


def _no_store(response):
    response['Cache-Control'] = 'no-store'
    return response


def _connection_payload(connection):
    profile = get_profile(connection.provider_id, connection.endpoint_profile)
    return {
        'id': str(connection.pk),
        'provider_id': connection.provider_id,
        'provider_name': profile['provider_name'] if profile else connection.provider_id,
        'endpoint_profile': connection.endpoint_profile,
        'region_name': profile['region_name'] if profile else '不可用',
        'display_name': connection.display_name,
        'key_saved': bool(connection.credential_ciphertext),
        'masked_key': '••••••••' if connection.credential_ciphertext else '',
        'is_enabled': connection.is_enabled,
        'verification_status': 'not_tested',
        'updated_at': connection.updated_at.isoformat(),
    }


def _require_feature():
    if not settings.AI_BYOK_ENABLED:
        return policy_error('byok_disabled')
    return None


def _storage_error():
    return Response(
        {
            'error_code': 'credential_storage_unavailable',
            'error': '当前无法安全使用凭据，请联系站点管理员。',
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _lock_owned_connection(user, connection_id):
    """Lock only a live row belonging to this owner; callers use it in atomic()."""
    return UserAIConnection.objects.select_for_update().filter(
        pk=connection_id, user=user, is_deleted=False,
    ).first()


class AIProviderCatalogView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _require_feature()
        if denied:
            return denied
        return _no_store(Response({'providers': provider_catalog()}))


class UserAIConnectionListCreateView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _require_feature()
        if denied:
            return denied
        rows = UserAIConnection.objects.filter(
            user=request.user, is_deleted=False,
        ).order_by('-updated_at', 'id')
        return _no_store(Response({'connections': [_connection_payload(row) for row in rows]}))

    def post(self, request):
        denied = _require_feature()
        if denied:
            return denied
        serializer = ConnectionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _no_store(Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST))
        values = serializer.validated_data
        profile = values['profile']
        connection = UserAIConnection(
            user=request.user,
            provider_id=values['provider_id'],
            endpoint_profile=profile['profile_id'],
            endpoint_profile_version=profile['version'],
            display_name=values.get('display_name') or f"{profile['provider_name']} · 个人",
        )
        try:
            ciphertext, key_id = encrypt_credential(connection, values['api_key'])
        except CredentialEncryptionUnavailable:
            return _no_store(_storage_error())
        connection.credential_ciphertext = ciphertext
        connection.encryption_key_id = key_id
        connection.save(force_insert=True)
        return _no_store(Response(_connection_payload(connection), status=status.HTTP_201_CREATED))


class UserAIConnectionDetailView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, connection_id):
        denied = _require_feature()
        if denied:
            return denied
        serializer = ConnectionPatchSerializer(data=request.data)
        if not serializer.is_valid():
            return _no_store(Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST))
        with transaction.atomic():
            connection = _lock_owned_connection(request.user, connection_id)
            if connection is None:
                return _no_store(Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND))
            values = serializer.validated_data
            if 'display_name' in values:
                connection.display_name = values['display_name']
            if 'is_enabled' in values and values['is_enabled'] != connection.is_enabled:
                if values['is_enabled']:
                    try:
                        decrypt_credential(connection)
                    except (CredentialEncryptionUnavailable, CredentialUnavailable):
                        return _no_store(_storage_error())
                connection.is_enabled = values['is_enabled']
                connection.credential_epoch += 1
            connection.save(update_fields=['display_name', 'is_enabled', 'credential_epoch', 'updated_at'])
        return _no_store(Response(_connection_payload(connection)))

    def delete(self, request, connection_id):
        denied = _require_feature()
        if denied:
            return denied
        with transaction.atomic():
            connection = _lock_owned_connection(request.user, connection_id)
            if connection is None:
                return _no_store(Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND))
            connection.is_enabled = False
            connection.is_deleted = True
            connection.deleted_at = timezone.now()
            connection.credential_epoch += 1
            connection.credential_ciphertext = ''
            connection.encryption_key_id = ''
            connection.save(update_fields=[
                'is_enabled', 'is_deleted', 'deleted_at', 'credential_epoch',
                'credential_ciphertext', 'encryption_key_id', 'updated_at',
            ])
        return _no_store(Response({'deleted': True}))


class UserAIConnectionKeyView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, connection_id):
        denied = _require_feature()
        if denied:
            return denied
        serializer = CredentialReplaceSerializer(data=request.data)
        if not serializer.is_valid():
            return _no_store(Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST))
        try:
            with transaction.atomic():
                connection = _lock_owned_connection(request.user, connection_id)
                if connection is None:
                    return _no_store(Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND))
                connection.credential_epoch += 1
                connection.credential_version += 1
                ciphertext, key_id = encrypt_credential(connection, serializer.validated_data['api_key'])
                connection.credential_ciphertext = ciphertext
                connection.encryption_key_id = key_id
                connection.save(update_fields=[
                    'credential_epoch', 'credential_version', 'credential_ciphertext',
                    'encryption_key_id', 'updated_at',
                ])
        except CredentialEncryptionUnavailable:
            return _no_store(_storage_error())
        return _no_store(Response(_connection_payload(connection)))
