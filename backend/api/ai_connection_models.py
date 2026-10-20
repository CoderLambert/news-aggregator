"""Sole BYOK T01 connection identity; historical Keys migrate once in 0061."""
import uuid
from django.db import models


class UserAIConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='ai_connections')
    provider_id = models.CharField(max_length=32)
    endpoint_profile = models.CharField(max_length=48)
    endpoint_profile_version = models.PositiveSmallIntegerField(default=1)
    endpoint_policy_digest = models.CharField(max_length=40, blank=True, default='')
    auth_mode = models.CharField(max_length=8, choices=(('api_key', 'API Key'), ('none', 'No Key')),
                                 default='api_key')
    display_name = models.CharField(max_length=64)
    # One-time preserved model selection; T02 converts it into UserAIModelConfig.
    # Never consulted by inference in the T01 transition.
    imported_model_id = models.CharField(max_length=128, blank=True, default='')
    credential_ciphertext = models.TextField(blank=True, default='')
    encryption_key_id = models.CharField(max_length=64, blank=True, default='')
    credential_epoch = models.PositiveBigIntegerField(default=1)
    credential_version = models.PositiveBigIntegerField(default=1)
    revision = models.PositiveBigIntegerField(default=1)
    request_id = models.UUIDField(default=uuid.uuid4, editable=False)
    request_hash = models.CharField(max_length=64, editable=False)
    is_enabled = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at', 'id']
        indexes = [models.Index(fields=['user', 'is_deleted'], name='user_ai_conn_owner_deleted')]
        constraints = [models.UniqueConstraint(fields=['user', 'request_id'], name='user_ai_conn_request_unique')]

    def __str__(self):
        return f'AI connection {self.provider_id}:{self.pk}'
