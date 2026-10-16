"""Versioned local catalog, separate from sources and user subscriptions."""

import uuid

from django.db import models


class FeedDirectorySnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checksum = models.CharField(max_length=64, unique=True)
    commit = models.CharField(max_length=64)
    license = models.CharField(max_length=128)
    schema_version = models.PositiveIntegerField()
    provenance = models.JSONField(default=dict)
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['active'], condition=models.Q(active=True),
            name='one_active_feed_directory',
        )]


class FeedDirectoryEntry(models.Model):
    snapshot = models.ForeignKey(FeedDirectorySnapshot, on_delete=models.CASCADE, related_name='entries')
    entry_id = models.UUIDField(editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    language = models.CharField(max_length=32, blank=True, default='')
    region = models.CharField(max_length=32, blank=True, default='')
    tags = models.JSONField(default=list)
    origin = models.JSONField(default=dict)
    kind = models.CharField(max_length=16, choices=[('feed', 'feed'), ('route_template', 'route_template')])
    public_url = models.CharField(max_length=1024)
    required_parameters = models.JSONField(default=list)
    capability_requirements = models.JSONField(default=list)
    verified_at = models.DateTimeField(null=True, blank=True)
    visibility = models.CharField(max_length=16, default='public', choices=[('public', 'public'), ('hidden', 'hidden')])

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['snapshot', 'entry_id'], name='unique_directory_snapshot_entry',
        )]
        indexes = [models.Index(fields=['snapshot', 'visibility'], name='directory_snapshot_visible')]
