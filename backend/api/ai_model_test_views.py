"""Owner-authorized, one-shot capability checks for approved model aliases."""

from __future__ import annotations

import hashlib
import json
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.ai_model_views import NoStoreAPIView, UNKNOWN_CAPABILITIES, _require_feature
from api.authentication import AnonymousCsrfSessionAuthentication
from api.models import AICallAttempt, UserAIConnection, UserAIModelConfig
from api.services.ai_credentials import (
    CredentialEncryptionUnavailable,
    CredentialUnavailable,
    decrypt_credential,
    require_active_connection,
)
from api.services.ai_model_registry import get_model_preset
from api.services.ai_model_test import gateway_is_configured, send_model_probe
from api.services.ai_registry import get_profile


class ModelTestSerializer(serializers.Serializer):
    probe_kind = serializers.ChoiceField(choices=('text', 'tools'))

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({'request': '请求字段无效'})
        return super().to_internal_value(data)


def _snapshot_digest(*, model: UserAIModelConfig, connection: UserAIConnection, probe_kind: str, alias: str) -> str:
    snapshot = {
        'model_id': model.model_id,
        'catalog_model_id': model.catalog_model_id,
        'catalog_version': model.catalog_version,
        'proxy_alias': alias,
        'probe_kind': probe_kind,
        'provider_id': connection.provider_id,
        'endpoint_profile': connection.endpoint_profile,
        'credential_epoch': connection.credential_epoch,
        'config_revision': model.config_revision,
        'endpoint_profile_version': connection.endpoint_profile_version,
    }
    encoded = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def _current_snapshot(model_id, connection_id, *, user_id, credential_epoch, config_revision, endpoint_profile_version):
    model = UserAIModelConfig.objects.select_for_update().filter(
        pk=model_id, connection__user_id=user_id,
    ).first()
    connection = UserAIConnection.objects.select_for_update().filter(
        pk=connection_id, user_id=user_id,
    ).first()
    if model is None or connection is None:
        return None
    if (
        model.connection_id != connection.pk
        or model.config_revision != config_revision
        or connection.credential_epoch != credential_epoch
        or connection.endpoint_profile_version != endpoint_profile_version
    ):
        return None
    return model


class AIModelTestView(NoStoreAPIView):
    authentication_classes = [AnonymousCsrfSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, model_id):
        denied = _require_feature()
        if denied:
            return denied
        serializer = ModelTestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        probe_kind = serializer.validated_data['probe_kind']

        with transaction.atomic():
            model = UserAIModelConfig.objects.select_for_update().filter(
                pk=model_id,
                connection__user=request.user,
                connection__is_deleted=False,
            ).first()
            if model is None:
                return Response({'error_code': 'not_found'}, status=status.HTTP_404_NOT_FOUND)
            connection = UserAIConnection.objects.select_for_update().filter(
                pk=model.connection_id,
                user=request.user,
                is_deleted=False,
            ).first()
            if connection is None:
                return Response({'error_code': 'connection_unavailable'}, status=status.HTTP_409_CONFLICT)

            preset = get_model_preset(model.catalog_model_id, connection.provider_id)
            if (
                preset is None
                or model.catalog_version != preset['catalog_version']
                or model.model_id != preset['model_id']
                or model.proxy_model_alias != preset['proxy_model_alias']
            ):
                return Response({'error_code': 'model_test_route_unavailable'}, status=status.HTTP_409_CONFLICT)
            profile = get_profile(connection.provider_id, connection.endpoint_profile)
            if profile is None or profile['version'] != connection.endpoint_profile_version:
                return Response({'error_code': 'endpoint_profile_unavailable'}, status=status.HTTP_409_CONFLICT)
            if not gateway_is_configured(settings.AI_BYOK_GATEWAY_URL, settings.AI_BYOK_GATEWAY_PROJECT_KEY):
                return Response({'error_code': 'model_test_gateway_unavailable'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            try:
                active_connection = require_active_connection(
                    user_id=request.user.pk,
                    connection_id=connection.pk,
                    expected_epoch=connection.credential_epoch,
                )
                provider_key = decrypt_credential(active_connection)
            except (CredentialEncryptionUnavailable, CredentialUnavailable):
                return Response({'error_code': 'connection_unavailable'}, status=status.HTTP_409_CONFLICT)

            snapshot = {
                'model_id': model.pk,
                'connection_id': connection.pk,
                'credential_epoch': connection.credential_epoch,
                'config_revision': model.config_revision,
                'endpoint_profile_version': connection.endpoint_profile_version,
            }
            snapshot_hash = _snapshot_digest(
                model=model,
                connection=connection,
                probe_kind=probe_kind,
                alias=preset['proxy_model_alias'],
            )
            attempt = AICallAttempt.objects.create(
                user=request.user,
                model_config=model,
                purpose='model_test',
                probe_kind=probe_kind,
                status='started',
                snapshot_digest=snapshot_hash,
                credential_epoch=connection.credential_epoch,
                config_revision=model.config_revision,
                endpoint_profile_version=connection.endpoint_profile_version,
            )

        started = time.monotonic()
        outcome = send_model_probe(
            gateway_url=settings.AI_BYOK_GATEWAY_URL,
            project_key=settings.AI_BYOK_GATEWAY_PROJECT_KEY,
            provider_key=provider_key,
            model_alias=preset['proxy_model_alias'],
            probe_kind=probe_kind,
        )
        latency_ms = min(max(int((time.monotonic() - started) * 1000), 0), 2_147_483_647)

        with transaction.atomic():
            saved_attempt = AICallAttempt.objects.select_for_update().get(pk=attempt.pk)
            saved_attempt.status = outcome.status
            saved_attempt.provider_request_id = outcome.provider_request_id
            saved_attempt.input_tokens = outcome.input_tokens
            saved_attempt.output_tokens = outcome.output_tokens
            saved_attempt.latency_ms = latency_ms
            saved_attempt.safe_error_code = outcome.safe_error_code
            saved_attempt.finished_at = timezone.now()
            saved_attempt.save(update_fields=[
                'status', 'provider_request_id', 'input_tokens', 'output_tokens',
                'latency_ms', 'safe_error_code', 'finished_at',
            ])

            current_model = _current_snapshot(
                snapshot['model_id'],
                snapshot['connection_id'],
                user_id=request.user.pk,
                credential_epoch=snapshot['credential_epoch'],
                config_revision=snapshot['config_revision'],
                endpoint_profile_version=snapshot['endpoint_profile_version'],
            )
            stale = current_model is None
            if not stale:
                capabilities = {**UNKNOWN_CAPABILITIES, **current_model.capability_snapshot}
                if outcome.status == 'succeeded':
                    capabilities[probe_kind] = 'supported'
                current_model.capability_snapshot = capabilities
                current_model.verification_status = 'verified' if outcome.status == 'succeeded' else 'failed'
                current_model.verified_credential_epoch = snapshot['credential_epoch']
                current_model.verified_config_revision = snapshot['config_revision']
                current_model.verified_endpoint_profile_version = snapshot['endpoint_profile_version']
                current_model.last_tested_at = timezone.now()
                current_model.last_safe_error_code = outcome.safe_error_code
                current_model.save(update_fields=[
                    'capability_snapshot', 'verification_status', 'verified_credential_epoch',
                    'verified_config_revision', 'verified_endpoint_profile_version',
                    'last_tested_at', 'last_safe_error_code', 'updated_at',
                ])
                capability = current_model.capability_snapshot.get(probe_kind, 'unknown')
                verification_status = current_model.verification_status
            else:
                capability = 'unknown'
                verification_status = 'stale'

        return Response({
            'attempt_id': str(attempt.attempt_id),
            'probe_kind': probe_kind,
            'status': 'stale' if stale else outcome.status,
            'verification_status': verification_status,
            'capability': capability,
            'stale': stale,
            'safe_error_code': outcome.safe_error_code,
            'latency_ms': latency_ms,
            'input_tokens': outcome.input_tokens,
            'output_tokens': outcome.output_tokens,
            'billing_notice': 'provider_may_bill',
        })
