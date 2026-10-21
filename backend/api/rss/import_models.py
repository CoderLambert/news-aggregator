"""OPML previews and outcomes; ChannelSubscription remains the relationship truth."""
import uuid

from django.conf import settings
from django.db import models


class RssImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='rss_imports')
    filename = models.CharField(max_length=255, blank=True, default='')
    # Private bounded upload; never served through a public media directory.
    file_content = models.BinaryField(null=True, editable=False)
    file_size = models.PositiveIntegerField(default=0)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_count = models.PositiveIntegerField(default=0)
    paused = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    file_hash = models.CharField(max_length=64)
    preview_token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    confirmed_request_hash = models.CharField(max_length=64, blank=True, default='')
    options = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default='preview', choices=[(v, v) for v in ('preview', 'confirmed', 'complete', 'removed')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class RssImportItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(RssImportBatch, on_delete=models.CASCADE, related_name='items')
    feed_url = models.CharField(max_length=1024, blank=True, default='')
    title = models.CharField(max_length=255, blank=True, default='')
    groups = models.JSONField(default=list)
    selected_group_ids = models.JSONField(default=list)
    status = models.CharField(max_length=16, default='preview', choices=[(v, v) for v in ('preview', 'invalid', 'pending', 'queued', 'failed', 'succeeded', 'removed')])
    error_code = models.CharField(max_length=64, blank=True, default='')
    outcome = models.CharField(max_length=32, blank=True, default='')
    duplicate_count = models.PositiveIntegerField(default=0)
    next_attempt = models.DateTimeField(null=True, blank=True)
    operation = models.ForeignKey('api.FeedOperation', null=True, blank=True, on_delete=models.PROTECT)
    created_subscription = models.BooleanField(default=False)
    subscription = models.ForeignKey('api.ChannelSubscription', null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'next_attempt'], name='rss_import_due_idx')]
