"""T02 model configuration and secret-free probe attempt receipts.

The parent UserAIConnection remains the sole credential identity.
No business inference is enabled until T03 task preferences are explicitly bound.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class UserAIModelConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey('api.UserAIConnection', on_delete=models.CASCADE, related_name='model_configs')
    model_id = models.CharField(max_length=160)
    display_name = models.CharField(max_length=64)
    catalog_model_id = models.CharField(max_length=80, blank=True, default='')
    config_revision = models.PositiveBigIntegerField(default=1)
    # Each independent capability receipt captures its authorizing attempt
    # and versioned connection/model identity, never provider response contents.
    capability_results = models.JSONField(default=dict)
    last_text_attempt = models.UUIDField(null=True, blank=True)
    last_tools_attempt = models.UUIDField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['connection', 'model_id'], condition=Q(is_deleted=False),
                                    name='user_ai_model_unique_active'),
        ]


class AIModelProbeAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    connection = models.ForeignKey('api.UserAIConnection', on_delete=models.CASCADE)
    model_config = models.ForeignKey(UserAIModelConfig, on_delete=models.CASCADE, related_name='probe_attempts')
    model_id = models.CharField(max_length=160)
    model_revision = models.PositiveBigIntegerField()
    probe_kind = models.CharField(max_length=8)
    status = models.CharField(max_length=16, default='started')
    safe_error_code = models.CharField(max_length=48, blank=True, default='')
    credential_epoch = models.PositiveBigIntegerField()
    credential_version = models.PositiveBigIntegerField()
    endpoint_profile = models.CharField(max_length=48)
    endpoint_profile_version = models.PositiveSmallIntegerField()
    proxy_alias = models.CharField(max_length=80)
    provider_request_id = models.CharField(max_length=128, blank=True, default='')
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', 'id']
        indexes = [models.Index(fields=['user', 'created_at'], name='ai_probe_owner_created')]
