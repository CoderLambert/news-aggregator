"""Persistence for channel organization; never a second subscription truth source."""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class SourceTopicProfile(models.Model):
    source = models.OneToOneField('api.Source', on_delete=models.CASCADE, related_name='topic_profile')
    about = models.TextField(default='', blank=True)
    topics = models.JSONField(default=list)
    origin = models.CharField(max_length=16, default='rules')
    evidence_hash = models.CharField(max_length=64, default='')
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class ChannelGroupingConfig(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='channel_grouping_config')
    mode = models.CharField(max_length=16, default='suggest')
    bindings = models.JSONField(default=dict)
    revision = models.PositiveBigIntegerField(default=1)
    active_since = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class ChannelGroupingOverride(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source = models.ForeignKey('api.Source', on_delete=models.CASCADE)
    group = models.ForeignKey('api.ChannelGroup', on_delete=models.CASCADE)
    suppressed = models.BooleanField(default=False)
    touched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'source', 'group'], name='unique_grouping_override')]


class ChannelGroupingProposal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    request_id = models.UUIDField(default=uuid.uuid4)
    engine = models.CharField(max_length=16, default='rules')
    status = models.CharField(max_length=16, default='ready', db_index=True)
    source_ids = models.JSONField(default=list)
    topic_keys = models.JSONField(default=list)
    input_snapshot = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64, default='')
    evidence = models.JSONField(default=list)
    result = models.JSONField(default=list)
    applied_changes = models.JSONField(default=list)
    applied_at = models.DateTimeField(null=True, blank=True)
    public_source = models.ForeignKey('api.Source', null=True, blank=True, on_delete=models.CASCADE)
    credential_fingerprint = models.CharField(max_length=64, default='', blank=True)
    model_id = models.CharField(max_length=160, default='', blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.CharField(max_length=64, default='', blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    error_code = models.CharField(max_length=64, default='', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['user', 'request_id'], name='unique_grouping_request')]


class SubscriptionGroupingState(models.Model):
    subscription = models.OneToOneField('api.ChannelSubscription', on_delete=models.CASCADE)
    status = models.CharField(max_length=16, default='pending')
    profile_hash = models.CharField(max_length=64, default='')
    updated_at = models.DateTimeField(auto_now=True)


class ChannelClassifierSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    enabled = models.BooleanField(default=False)
    daily_limit = models.PositiveSmallIntegerField(default=10)
    updated_at = models.DateTimeField(auto_now=True)


class ReadingDay(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    news = models.ForeignKey('api.News', on_delete=models.CASCADE)
    day = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'news', 'day'], name='unique_reader_news_day')]
        indexes = [models.Index(fields=['user', 'day'], name='reader_day_lookup')]


class ChannelIntakeRequest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    url = models.URLField(max_length=1024)
    status = models.CharField(max_length=16, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_channel_intakes')
    registered_source = models.ForeignKey('api.Source', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='intake_requests')
    review_revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'url'], name='unique_channel_intake')]
