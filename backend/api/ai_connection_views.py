"""Original T01: bounded, owner-scoped connection CRUD, no provider requests."""
import hmac
import re
from django.conf import settings
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from api.authentication import AnonymousCsrfSessionAuthentication
from api.ai_connection_models import UserAIConnection
from api.services.ai_registry import get_profile, provider_catalog
from api.services.ai_endpoint_profiles import profile_allows_user
from api.services.ai_credentials import (CredentialEncryptionUnavailable, CredentialUnavailable,
    creation_digest, execution_credential, encrypt_credential, lock_owner)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError('invalid_request')
        return super().to_internal_value(data)


def validate_name(value):
    if (any(ord(char) < 32 or ord(char) == 127 for char in value)
            or re.search(r'(?i)(?:bearer\s|(?:sk|ark|AIza)[-_])', value)
            or re.search(r'[A-Za-z0-9_-]{24,}', value)):
        raise serializers.ValidationError('invalid_name')
    return value


class KeySerializer(StrictSerializer):
    api_key = serializers.CharField(min_length=8, max_length=4096, trim_whitespace=False, write_only=True)

    def validate_api_key(self, value):
        if any(ord(char) <= 32 or ord(char) >= 127 for char in value):
            raise serializers.ValidationError('invalid_key')
        return value


class CreateSerializer(KeySerializer):
    api_key = serializers.CharField(min_length=8, max_length=4096, trim_whitespace=False,
                                    write_only=True, required=False)
    auth_mode = serializers.ChoiceField(choices=('api_key', 'none'), default='api_key')
    provider_id = serializers.CharField(max_length=32)
    endpoint_profile = serializers.CharField(max_length=48)
    display_name = serializers.CharField(max_length=64)
    request_id = serializers.UUIDField()

    def validate_display_name(self, value):
        return validate_name(value)

    def validate(self, values):
        profile = get_profile(values['provider_id'], values['endpoint_profile'])
        if (profile is None or not profile_allows_user(profile, self.context['user_id'])
                or values['auth_mode'] not in profile.get('auth_modes', ['api_key'])):
            raise serializers.ValidationError('invalid_endpoint')
        if ((values['auth_mode'] == 'api_key' and not values.get('api_key'))
                or (values['auth_mode'] == 'none' and 'api_key' in values)):
            raise serializers.ValidationError('invalid_authentication')
        if values.get('api_key') and values['api_key'] in values['display_name']:
            raise serializers.ValidationError('invalid_name')
        self.validated_profile = profile
        return values


class PatchSerializer(StrictSerializer):
    revision = serializers.IntegerField(min_value=1)
    display_name = serializers.CharField(max_length=64, required=False)
    is_enabled = serializers.BooleanField(required=False)

    def validate_display_name(self, value):
        return validate_name(value)

    def validate(self, values):
        if set(values) == {'revision'}:
            raise serializers.ValidationError('empty_change')
        return values


class ReplaceSerializer(KeySerializer):
    revision = serializers.IntegerField(min_value=1)


class DeleteSerializer(StrictSerializer):
    revision = serializers.IntegerField(min_value=1)


def payload(row):
    profile = get_profile(row.provider_id, row.endpoint_profile)
    return {'id': str(row.pk), 'provider_id': row.provider_id,
        'provider_name': profile['provider_name'] if profile else row.provider_id,
        'endpoint_profile': row.endpoint_profile, 'endpoint_profile_version': row.endpoint_profile_version,
        'region_name': profile['region_name'] if profile else '不可用', 'display_name': row.display_name,
        'auth_mode': row.auth_mode,
        'key_saved': bool(row.credential_ciphertext), 'masked_key': '••••••••' if row.credential_ciphertext else '',
        'is_enabled': row.is_enabled, 'revision': row.revision, 'credential_epoch': row.credential_epoch,
        'verification_status': 'not_tested', 'updated_at': row.updated_at.isoformat()}


def error(code, status=400):
    # Never reflect serializer input, request bodies, ciphertext or exceptions.
    return Response({'error_code': code}, status=status)


class ConnectionView(APIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]
    allow_history_reads = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if settings.PUBLIC_SITE_MODE != 'full':
            raise PermissionDenied('只读模式不允许管理个人连接。')
        history_read = self.allow_history_reads and request.method in {'GET', 'HEAD'}
        if not getattr(settings, 'AI_BYOK_ENABLED', False) and not history_read:
            raise PermissionDenied('个人连接管理尚未启用。')

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

    def handle_exception(self, exc):
        if isinstance(exc, (CredentialEncryptionUnavailable, CredentialUnavailable, OperationalError)):
            return error('credential_unavailable', 503)
        if isinstance(exc, IntegrityError):
            return error('connection_conflict', 409)
        return super().handle_exception(exc)


class AIProviderCatalogView(ConnectionView):
    def get(self, request):
        return Response({'providers': provider_catalog(user_id=request.user.pk)})


class UserAIConnectionListCreateView(ConnectionView):
    def get(self, request):
        rows = UserAIConnection.objects.filter(user=request.user, is_deleted=False)
        return Response({'connections': [payload(row) for row in rows]})

    def post(self, request):
        serializer = CreateSerializer(data=request.data, context={'user_id': request.user.pk})
        if not serializer.is_valid():
            return error('invalid_request')
        values = serializer.validated_data
        with transaction.atomic():
            lock_owner(request.user.pk)
            digest = creation_digest(request.user.pk, values)
            existing = UserAIConnection.objects.filter(user=request.user, request_id=values['request_id']).first()
            if existing is not None:
                if existing.is_deleted or not hmac.compare_digest(existing.request_hash, digest):
                    return error('connection_conflict', 409)
                return Response(payload(existing))
            if UserAIConnection.objects.filter(user=request.user, is_deleted=False).count() >= 20:
                return error('connection_limit', 429)
            profile = get_profile(values['provider_id'], values['endpoint_profile'])
            validated_profile = serializer.validated_profile
            if (profile is None or not profile_allows_user(profile, request.user.pk)
                    or values['auth_mode'] not in profile.get('auth_modes', ['api_key'])
                    or (profile['version'], profile.get('policy_digest', '')) != (
                        validated_profile['version'], validated_profile.get('policy_digest', ''))):
                return error('endpoint_changed', 409)
            row = UserAIConnection(user=request.user, provider_id=values['provider_id'],
                endpoint_profile=values['endpoint_profile'], endpoint_profile_version=profile['version'],
                endpoint_policy_digest=profile.get('policy_digest', ''), auth_mode=values['auth_mode'],
                display_name=values['display_name'], request_id=values['request_id'], request_hash=digest)
            if row.auth_mode == 'api_key':
                row.credential_ciphertext, row.encryption_key_id = encrypt_credential(row, values['api_key'])
            row.save(force_insert=True)
        return Response(payload(row), status=201)


class UserAIConnectionDetailView(ConnectionView):
    def get(self, request, connection_id):
        row = UserAIConnection.objects.filter(pk=connection_id, user=request.user, is_deleted=False).first()
        return Response(payload(row)) if row else error('not_found', 404)

    def patch(self, request, connection_id):
        return self._mutate(request, connection_id, 'patch', PatchSerializer)

    def delete(self, request, connection_id):
        return self._mutate(request, connection_id, 'delete', DeleteSerializer)

    def _mutate(self, request, connection_id, action, serializer_class):
        with transaction.atomic():
            lock_owner(request.user.pk)
            row = UserAIConnection.objects.filter(pk=connection_id, user=request.user, is_deleted=False).first()
            if row is None:
                return error('not_found', 404)
            serializer = serializer_class(data=request.data)
            if not serializer.is_valid():
                return error('invalid_request')
            values = serializer.validated_data
            if row.revision != values['revision']:
                return error('connection_changed', 409)
            if action == 'delete':
                row.is_deleted, row.is_enabled = True, False
                row.deleted_at = timezone.now()
                row.credential_epoch += 1
                row.credential_ciphertext, row.encryption_key_id = '', ''
            elif action == 'key':
                if row.auth_mode != 'api_key':
                    return error('invalid_authentication')
                # Replacing a Key cannot silently bind it to a changed target.
                profile = get_profile(row.provider_id, row.endpoint_profile)
                if (profile is None or not profile_allows_user(profile, request.user.pk)
                        or row.endpoint_profile_version != profile['version']
                        or row.endpoint_policy_digest != profile.get('policy_digest', '')
                        or 'api_key' not in profile.get('auth_modes', ['api_key'])):
                    raise CredentialUnavailable('endpoint_changed')
                row.credential_epoch += 1
                row.credential_version += 1
                row.credential_ciphertext, row.encryption_key_id = encrypt_credential(row, values['api_key'])
            else:
                if 'display_name' in values:
                    row.display_name = values['display_name']
                if 'is_enabled' in values and values['is_enabled'] != row.is_enabled:
                    if values['is_enabled']:
                        profile = get_profile(row.provider_id, row.endpoint_profile)
                        if profile is None or profile['version'] != row.endpoint_profile_version:
                            raise CredentialUnavailable('endpoint_changed')
                        execution_credential(row)
                    row.is_enabled = values['is_enabled']
                    row.credential_epoch += 1
            row.revision += 1
            row.save()
        return Response({'deleted': True}) if action == 'delete' else Response(payload(row))


class UserAIConnectionKeyView(UserAIConnectionDetailView):
    http_method_names = ['put', 'options']

    def put(self, request, connection_id):
        return self._mutate(request, connection_id, 'key', ReplaceSerializer)
