"""Versioned business authority and explicit public-feed publication grants."""
import uuid
from django.conf import settings
from django.db import models


class RssReviewerGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    engine_instance_uuid = models.UUIDField()
    active = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [('review_public_rss', 'Review public RSS channels')]
        constraints = [models.UniqueConstraint(fields=['user', 'engine_instance_uuid'], name='rss_reviewer_instance_unique')]


class RssReviewerEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    grant = models.ForeignKey(RssReviewerGrant, on_delete=models.PROTECT)
    version = models.PositiveBigIntegerField()
    active = models.BooleanField()
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor', 'key'], name='rss_reviewer_event_key_unique')]


class PublicFeedCandidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.OneToOneField('api.FeedBinding', on_delete=models.PROTECT, related_name='public_candidate')
    name = models.CharField(max_length=255)
    category = models.ForeignKey('api.Category', on_delete=models.PROTECT)
    language = models.CharField(max_length=16, default='zh')
    version = models.PositiveBigIntegerField(default=1)
    state = models.CharField(max_length=16, default='pending', choices=[(s,s) for s in ['pending','approved','rejected','withdrawn','published']])
    creation_mode = models.CharField(max_length=16, default='recommendation')
    decision = models.ForeignKey('api.PublicFeedReviewEvent', null=True, on_delete=models.PROTECT, related_name='+')
    public_source = models.OneToOneField('api.Source', null=True, on_delete=models.PROTECT, related_name='public_candidate')
    scope_since = models.DateTimeField(null=True)
    member_cursor = models.PositiveBigIntegerField(default=0)
    member_sync_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PublicFeedSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(PublicFeedCandidate, on_delete=models.PROTECT, related_name='submissions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.CharField(max_length=1000, blank=True)
    withdrawn_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['candidate','user'], name='rss_submission_user_unique')]


class PublicFeedReviewEvent(models.Model):
    candidate = models.ForeignKey(PublicFeedCandidate, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    candidate_version = models.PositiveBigIntegerField()
    authority = models.JSONField(default=dict)
    action = models.CharField(max_length=24)
    reason = models.CharField(max_length=1000, blank=True)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor','key'], name='rss_review_event_key_unique')]


class PublicFeedEntry(models.Model):
    source = models.ForeignKey('api.Source', on_delete=models.PROTECT, related_name='public_entries')
    entry = models.ForeignKey('api.EngineEntryMap', on_delete=models.PROTECT, related_name='public_memberships')
    approval_version = models.PositiveBigIntegerField()
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source','entry'], name='rss_public_entry_unique')]
