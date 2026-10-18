"""Owner-scoped T02 model CRUD and *explicit* bounded capacity probes.

All request and commit decisions recheck the existing T01 connection authority.
T03 business routing remains deliberately fail-closed in ai_execution.py.
"""
from dataclasses import asdict
import time
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response

from api.ai_connection_models import UserAIConnection
from api.ai_model_models import UserAIModelConfig, AIModelProbeAttempt
from api.ai_connection_views import ConnectionView, StrictSerializer, validate_name, error
from api.services.ai_credentials import (
    CredentialUnavailable, lock_owner, require_active_snapshot, snapshot_connection,
)
from api.services.ai_worker_fencing import dispatch_once, SNAPSHOT_SCHEMA_VERSION
from api.services.ai_model_registry import (
    CATALOG_VERSION, catalog_for, get_trusted_preset, normalize_model_id,
)
from api.services.ai_model_probe import ProbeOutcome, send_model_probe
from api.services.ai_model_capabilities import current_capabilities as _effective_capabilities


MODEL_LIMIT = 30
_KINDS = ('text', 'tools')


class ModelCreateSerializer(StrictSerializer):
    model_id = serializers.CharField(min_length=1, max_length=160, trim_whitespace=False)
    display_name = serializers.CharField(min_length=1, max_length=64, required=False)

    def validate_display_name(self, value):
        return validate_name(value)


class ModelPatchSerializer(StrictSerializer):
    revision = serializers.IntegerField(min_value=1)
    model_id = serializers.CharField(min_length=1, max_length=160, trim_whitespace=False, required=False)
    display_name = serializers.CharField(min_length=1, max_length=64, required=False)

    def validate_display_name(self, value):
        return validate_name(value)

    def validate(self, values):
        if set(values) == {'revision'}:
            raise serializers.ValidationError('empty_change')
        return values


class ModelDeleteSerializer(StrictSerializer):
    revision = serializers.IntegerField(min_value=1)


class ModelProbeSerializer(StrictSerializer):
    revision = serializers.IntegerField(min_value=1)
    request_id = serializers.UUIDField()
    probe_kind = serializers.ChoiceField(choices=_KINDS)


def _connection(user, connection_id):
    return UserAIConnection.objects.filter(
        pk=connection_id, user=user, is_deleted=False,
    ).first()


def _model(user, connection_id, model_id):
    return UserAIModelConfig.objects.select_related('connection').filter(
        pk=model_id, connection_id=connection_id,
        connection__user=user, connection__is_deleted=False, is_deleted=False,
    ).first()


def model_payload(model):
    capabilities = _effective_capabilities(model)
    return {
        'id': str(model.pk), 'connection_id': str(model.connection_id),
        'model_id': model.model_id, 'display_name': model.display_name,
        'catalog_model_id': model.catalog_model_id,
        'config_revision': model.config_revision, 'capabilities': capabilities,
        'has_trusted_route': get_trusted_preset(model.connection, model.model_id) is not None,
        'context_window_tokens': None,  # unknown until separately evidenced
        'updated_at': model.updated_at.isoformat(),
    }


def attempt_payload(row):
    return {
        'attempt_id': str(row.pk), 'request_id': str(row.request_id),
        'model_id': row.model_id, 'probe_kind': row.probe_kind,
        'status': row.status, 'safe_error_code': row.safe_error_code,
        'provider_request_id': row.provider_request_id,
        'input_tokens': row.input_tokens, 'output_tokens': row.output_tokens,
        'latency_ms': row.latency_ms,
        'created_at': row.created_at.isoformat(),
        'completed_at': row.completed_at.isoformat() if row.completed_at else None,
        'billing_notice': 'provider_may_bill',
    }


class AIModelCatalogView(ConnectionView):
    def get(self, request, connection_id):
        connection = _connection(request.user, connection_id)
        if not connection:
            return error('not_found', 404)
        return Response({'catalog_version': CATALOG_VERSION, 'models': catalog_for(connection)})


class AIModelListCreateView(ConnectionView):
    def get(self, request, connection_id):
        connection = _connection(request.user, connection_id)
        if connection is None:
            return error('not_found', 404)
        rows = UserAIModelConfig.objects.filter(connection=connection, is_deleted=False)
        return Response({'models': [model_payload(row) for row in rows]})

    def post(self, request, connection_id):
        serializer = ModelCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error('invalid_request')
        with transaction.atomic():
            lock_owner(request.user.pk)
            connection = _connection(request.user, connection_id)
            if connection is None:
                return error('not_found', 404)
            values = serializer.validated_data
            model_id = normalize_model_id(connection.provider_id, values['model_id'])
            if not model_id:
                return error('invalid_model_id')
            if UserAIModelConfig.objects.filter(connection=connection, is_deleted=False).count() >= MODEL_LIMIT:
                return error('model_limit', 429)
            if UserAIModelConfig.objects.filter(connection=connection, model_id=model_id, is_deleted=False).exists():
                return error('model_exists', 409)
            display_name = values.get('display_name') or model_id[:64]
            if len(display_name) > 64:
                return error('invalid_request')
            preset = get_trusted_preset(connection, model_id)
            row = UserAIModelConfig.objects.create(
                connection=connection, model_id=model_id, display_name=display_name,
                catalog_model_id=model_id if preset else '')
        return Response(model_payload(row), status=201)


class AIModelDetailView(ConnectionView):
    def get(self, request, connection_id, model_id):
        row = _model(request.user, connection_id, model_id)
        return Response(model_payload(row)) if row else error('not_found', 404)

    def patch(self, request, connection_id, model_id):
        serializer = ModelPatchSerializer(data=request.data)
        if not serializer.is_valid():
            return error('invalid_request')
        with transaction.atomic():
            lock_owner(request.user.pk)
            row = _model(request.user, connection_id, model_id)
            if row is None:
                return error('not_found', 404)
            values = serializer.validated_data
            if row.config_revision != values['revision']:
                return error('model_changed', 409)
            if 'model_id' in values:
                normalized = normalize_model_id(row.connection.provider_id, values['model_id'])
                if not normalized:
                    return error('invalid_model_id')
                if UserAIModelConfig.objects.filter(connection=row.connection, model_id=normalized,
                                                    is_deleted=False).exclude(pk=row.pk).exists():
                    return error('model_exists', 409)
                row.model_id = normalized
                row.catalog_model_id = normalized if get_trusted_preset(row.connection, normalized) else ''
            if 'display_name' in values:
                row.display_name = values['display_name']
            row.config_revision += 1
            row.capability_results = {}
            row.last_text_attempt = None
            row.last_tools_attempt = None
            row.save()
        return Response(model_payload(row))

    def delete(self, request, connection_id, model_id):
        serializer = ModelDeleteSerializer(data=request.data)
        if not serializer.is_valid():
            return error('invalid_request')
        with transaction.atomic():
            lock_owner(request.user.pk)
            row = _model(request.user, connection_id, model_id)
            if row is None:
                return error('not_found', 404)
            if row.config_revision != serializer.validated_data['revision']:
                return error('model_changed', 409)
            row.is_deleted = True
            row.config_revision += 1
            row.capability_results = {}
            row.last_text_attempt = None
            row.last_tools_attempt = None
            row.save()
        return Response({'deleted': True})


class AIModelAttemptListView(ConnectionView):
    def get(self, request, connection_id, model_id):
        if _model(request.user, connection_id, model_id) is None:
            return error('not_found', 404)
        attempts = AIModelProbeAttempt.objects.filter(
            user=request.user, connection_id=connection_id, model_config_id=model_id,
        )[:20]
        return Response({'attempts': [attempt_payload(row) for row in attempts]})


class AIModelProbeView(ConnectionView):
    http_method_names = ['post', 'options']

    def post(self, request, connection_id, model_id):
        serializer = ModelProbeSerializer(data=request.data)
        if not serializer.is_valid():
            return error('invalid_request')
        values = serializer.validated_data
        kind = values['probe_kind']
        request_id = values['request_id']
        with transaction.atomic():
            lock_owner(request.user.pk)
            # A previously accepted request MUST NOT be resent even if its
            # first response was lost or the connection has since been revoked.
            existing = AIModelProbeAttempt.objects.filter(user=request.user, request_id=request_id).first()
            if existing:
                if (existing.connection_id != connection_id or existing.model_config_id != model_id or
                        existing.probe_kind != kind or existing.model_revision != values['revision']):
                    return error('probe_request_conflict', 409)
                return Response(attempt_payload(existing))

            model = _model(request.user, connection_id, model_id)
            if model is None:
                return error('not_found', 404)
            if model.config_revision != values['revision']:
                return error('model_changed', 409)
            preset = get_trusted_preset(model.connection, model.model_id)
            if preset is None:
                return error('model_not_approved', 409)
            snapshot = snapshot_connection(model.connection)
            try:
                require_active_snapshot(snapshot)
            except CredentialUnavailable:
                return error('connection_inactive', 409)
            attempt = AIModelProbeAttempt.objects.create(
                user=request.user, request_id=request_id,
                connection=model.connection, model_config=model,
                model_id=model.model_id, model_revision=model.config_revision,
                probe_kind=kind, credential_epoch=snapshot.credential_epoch,
                credential_version=snapshot.credential_version,
                endpoint_profile=snapshot.endpoint_profile,
                endpoint_profile_version=snapshot.endpoint_profile_version,
                proxy_alias=preset['proxy_alias'],
            )
            setattr(model, f'last_{kind}_attempt', attempt.pk)
            receipts = dict(model.capability_results)
            receipts.pop(kind, None)
            model.capability_results = receipts
            model.save(update_fields=[f'last_{kind}_attempt', 'capability_results', 'updated_at'])

        started = time.monotonic()
        try:
            outcome = dispatch_once(
                {'schema_version': SNAPSHOT_SCHEMA_VERSION, **asdict(snapshot)},
                task_owner_id=request.user.pk,
                send=lambda key: send_model_probe(
                    provider_key=key, model_alias=preset['proxy_alias'], probe_kind=kind),
            )
        except CredentialUnavailable:
            outcome = ProbeOutcome('not_sent', 'authorization_changed')
        except Exception:
            # Do not reflect provider exceptions or assume lost responses were
            # never billed. No implicit retry on any unknown result.
            outcome = ProbeOutcome('unknown', 'result_unknown')
        latency = min(int((time.monotonic() - started) * 1000), 2_147_483_647)

        with transaction.atomic():
            lock_owner(request.user.pk)
            audit = AIModelProbeAttempt.objects.get(pk=attempt.pk, user=request.user)
            current = _model(request.user, connection_id, model_id)
            # Compare every input identity and same-kind latest attempt, plus
            # the *current* revocation/decryption fence, before any capability write.
            stale = current is None or (
                current.config_revision != attempt.model_revision or
                current.model_id != attempt.model_id or
                getattr(current, f'last_{kind}_attempt') != attempt.pk or
                current.connection.credential_epoch != snapshot.credential_epoch or
                current.connection.credential_version != snapshot.credential_version or
                current.connection.endpoint_profile != snapshot.endpoint_profile or
                current.connection.endpoint_profile_version != snapshot.endpoint_profile_version or
                not current.connection.is_enabled or
                get_trusted_preset(current.connection, current.model_id) is None
            )
            if not stale:
                try:
                    require_active_snapshot(snapshot)
                except CredentialUnavailable:
                    stale = True
            audit.status = 'stale' if stale else outcome.status
            audit.safe_error_code = outcome.safe_error_code
            audit.provider_request_id = outcome.provider_request_id
            audit.input_tokens = outcome.input_tokens
            audit.output_tokens = outcome.output_tokens
            audit.latency_ms = latency
            audit.completed_at = timezone.now()
            audit.save(update_fields=['status', 'safe_error_code', 'provider_request_id',
                'input_tokens', 'output_tokens', 'latency_ms', 'completed_at'])
            if not stale:
                capability = ('supported' if outcome.status == 'succeeded' else
                              'unsupported' if outcome.status == 'unsupported' else 'unknown')
                receipts = dict(current.capability_results)
                receipts[kind] = {
                    'attempt_id': str(attempt.pk), 'status': capability,
                    'config_revision': attempt.model_revision,
                    'credential_epoch': snapshot.credential_epoch,
                    'credential_version': snapshot.credential_version,
                    'endpoint_profile': snapshot.endpoint_profile,
                    'endpoint_profile_version': snapshot.endpoint_profile_version,
                }
                current.capability_results = receipts
                current.save(update_fields=['capability_results', 'updated_at'])
        return Response({**attempt_payload(audit), 'stale': stale,
                         'capability': 'unknown' if stale else _effective_capabilities(current)[kind]})
