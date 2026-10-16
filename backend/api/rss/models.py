"""C02 persistence only; network, ACL, CAS and operation execution live in services.

Engine identity is (engine_instance_uuid, account_id, feed_id, entry_id).
Bindings are durable identity anchors: never reassign one to a rebuilt instance.
SQLite unique/check constraints arbitrate competing writers; no row-lock contract.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def choices(*values):
    return [(value, value) for value in values]


def all_entries_policy():
    return {'version': 1, 'mode': 'all'}


class FeedBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engine_instance_uuid = models.UUIDField()
    account_id = models.PositiveBigIntegerField()
    engine_feed_id = models.PositiveBigIntegerField(null=True, blank=True)
    canonical_feed_url = models.URLField(max_length=1024)
    desired_mode = models.CharField(max_length=24, choices=choices('feed', 'full_content'), default='feed')
    desired_enabled = models.BooleanField(default=False)
    connection_state = models.CharField(max_length=24, default='pending', choices=choices(
        'pending', 'connecting', 'ready', 'paused', 'error', 'unknown'))
    policy_version = models.PositiveBigIntegerField(default=1)
    applied_policy_version = models.PositiveBigIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['engine_instance_uuid', 'account_id', 'canonical_feed_url'], name='rss_binding_url_identity'),
            models.UniqueConstraint(fields=['engine_instance_uuid', 'account_id', 'engine_feed_id'], condition=models.Q(engine_feed_id__isnull=False), name='rss_binding_feed_identity'),
            models.CheckConstraint(condition=models.Q(account_id__gt=0), name='rss_binding_account_positive'),
            models.CheckConstraint(condition=models.Q(engine_feed_id__isnull=True) | models.Q(engine_feed_id__gt=0), name='rss_binding_feed_positive'),
            models.CheckConstraint(condition=models.Q(policy_version__gte=1, applied_policy_version__lte=models.F('policy_version')), name='rss_binding_policy_order'),
        ]


class SourcePublication(models.Model):
    source = models.OneToOneField('api.Source', primary_key=True, on_delete=models.PROTECT, related_name='publication')
    publication = models.CharField(max_length=16, choices=choices('public', 'personal'), default='personal')
    display_name = models.CharField(max_length=255, blank=True, default='')
    # Existing static/dynamic policy vocabulary is retained; policy resolution is T11.
    reading_policy = models.CharField(max_length=32, default='summary_only')
    policy_version = models.PositiveBigIntegerField(default=1)
    owner = models.CharField(max_length=16, choices=choices('legacy', 'miniflux', 'paused'), default='paused')
    epoch = models.PositiveBigIntegerField(default=1)
    pause_reason = models.CharField(max_length=128, blank=True, default='')

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(publication__in=['public', 'personal']), name='rss_publication_scope_valid'),
            models.CheckConstraint(condition=models.Q(owner__in=['legacy', 'miniflux', 'paused']), name='rss_publication_owner_valid'),
            models.CheckConstraint(condition=models.Q(epoch__gte=1, policy_version__gte=1), name='rss_publication_versions_positive'),
        ]


class SourceFeedLink(models.Model):
    source = models.ForeignKey('api.Source', on_delete=models.PROTECT, related_name='feed_links')
    binding = models.ForeignKey(FeedBinding, on_delete=models.PROTECT, related_name='source_links')
    editorial_pin = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    # Data-only manifest filter. Services must validate the V1 whitelist before use.
    association_policy = models.JSONField(default=all_entries_policy)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'binding'], name='rss_source_binding_unique')]


class EngineEntryMap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey(FeedBinding, on_delete=models.PROTECT, related_name='entry_maps')
    engine_entry_id = models.PositiveBigIntegerField()
    news = models.ForeignKey('api.News', null=True, blank=True, on_delete=models.PROTECT, related_name='engine_entries')
    source_url = models.URLField(max_length=500)
    comments_url = models.URLField(max_length=1024, blank=True, default='')
    raw_hash = models.CharField(max_length=64, blank=True, default='')
    conversion_version = models.CharField(max_length=128, blank=True, default='')
    last_seen = models.DateTimeField(default=timezone.now)
    disposition = models.CharField(max_length=24, default='pending', choices=choices('pending', 'linked', 'rejected', 'conflict'))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['binding', 'engine_entry_id'], name='rss_entry_identity'),
            models.CheckConstraint(condition=models.Q(engine_entry_id__gt=0), name='rss_entry_id_positive'),
        ]


class BodyCandidate(models.Model):
    """Retained converted candidate and captured CAS tokens, never publisher HTML."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(EngineEntryMap, on_delete=models.PROTECT, related_name='body_candidates')
    news = models.ForeignKey('api.News', on_delete=models.PROTECT, related_name='body_candidates')
    source = models.ForeignKey('api.Source', on_delete=models.PROTECT, related_name='body_candidates')
    source_epoch = models.PositiveBigIntegerField()
    body_owner_version = models.PositiveBigIntegerField()
    source_policy_version = models.PositiveBigIntegerField()
    binding_policy_version = models.PositiveBigIntegerField()
    news_url = models.URLField(max_length=500)
    expected_revision = models.PositiveBigIntegerField()
    markdown = models.TextField()
    raw_hash = models.CharField(max_length=64)
    canonical_hash = models.CharField(max_length=64)
    conversion_version = models.CharField(max_length=128)
    content_kind = models.CharField(max_length=32, default='unknown')
    completeness = models.CharField(max_length=16, default='unknown', choices=choices('unknown', 'summary', 'verified'))
    evidence = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=16, default='pending', choices=choices('pending', 'unchanged', 'accepted', 'rejected', 'quarantined', 'conflict', 'stale'))
    reason = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['entry', 'source', 'canonical_hash', 'conversion_version', 'source_epoch',
                    'body_owner_version', 'source_policy_version', 'binding_policy_version', 'expected_revision'],
            name='rss_candidate_replay_unique',
        )]
        indexes = [models.Index(fields=['state', 'created_at'], name='rss_candidate_state_idx')]


class FeedSyncState(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engine_instance_uuid = models.UUIDField()
    account_id = models.PositiveBigIntegerField()
    new_cursor = models.PositiveBigIntegerField(default=0)
    run_id = models.UUIDField(null=True, blank=True)
    upper_id = models.PositiveBigIntegerField(null=True, blank=True)
    page_cursor = models.PositiveBigIntegerField(default=0)
    # Full retained-entry reconciliation has independent persisted progress.
    reconciliation_run_id = models.UUIDField(null=True, blank=True)
    reconciliation_upper_id = models.PositiveBigIntegerField(null=True, blank=True)
    reconciliation_page_cursor = models.PositiveBigIntegerField(default=0)
    reconciliation_last_complete_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_epoch = models.PositiveBigIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_complete_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['engine_instance_uuid', 'account_id'], name='rss_sync_account_unique'),
            models.CheckConstraint(condition=models.Q(account_id__gt=0), name='rss_sync_account_positive'),
        ]


class FeedOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=24, choices=choices('register', 'set_enabled', 'update_feed_policy', 'discover', 'refresh_feed', 'refetch_entry'))
    # Null is an internal system intent, never a public API actor or service user.
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='feed_operations')
    binding = models.ForeignKey(FeedBinding, null=True, blank=True, on_delete=models.PROTECT, related_name='operations')
    entry = models.ForeignKey(EngineEntryMap, null=True, blank=True, on_delete=models.PROTECT, related_name='operations')
    # Only fixed action parameters; validation/redaction belongs to the service.
    safe_input = models.JSONField(default=dict, blank=True)
    intent_version = models.PositiveBigIntegerField(default=1)
    dedupe_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=24, default='pending', choices=choices('pending', 'running', 'retry_wait', 'unknown', 'manual_blocked', 'succeeded', 'failed', 'cancelled'))
    attempts = models.PositiveIntegerField(default=0)
    next_attempt = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_epoch = models.PositiveBigIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    safe_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['actor', 'dedupe_key'], name='rss_operation_actor_dedupe'),
            models.UniqueConstraint(fields=['dedupe_key'], condition=models.Q(actor__isnull=True), name='rss_operation_system_dedupe'),
            models.CheckConstraint(condition=models.Q(kind__in=['register', 'set_enabled', 'update_feed_policy', 'discover', 'refresh_feed', 'refetch_entry']), name='rss_operation_kind_valid'),
            models.CheckConstraint(condition=models.Q(state__in=['pending', 'running', 'retry_wait', 'unknown', 'manual_blocked', 'succeeded', 'failed', 'cancelled']), name='rss_operation_state_valid'),
        ]
        indexes = [models.Index(fields=['state', 'next_attempt'], name='rss_operation_due_idx')]


class EntryIssue(models.Model):
    """Complete observed identity even if no registered binding can be trusted."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engine_instance_uuid = models.UUIDField()
    account_id = models.PositiveBigIntegerField()
    engine_feed_id = models.PositiveBigIntegerField()
    engine_entry_id = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=128)
    safe_metadata = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default='')
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(default=timezone.now)
    retryable = models.BooleanField(default=False)
    resolution = models.CharField(max_length=128, blank=True, default='')

    class Meta:
        abstract = True
        constraints = [models.UniqueConstraint(
            fields=['engine_instance_uuid', 'account_id', 'engine_feed_id', 'engine_entry_id', 'reason', 'content_hash'],
            name='%(class)s_identity_reason_hash',
        ), models.CheckConstraint(
            condition=models.Q(account_id__gt=0, engine_feed_id__gt=0, engine_entry_id__gt=0),
            name='%(class)s_positive_identity',
        )]


class FeedRejection(EntryIssue):
    pass


class IdentityConflict(EntryIssue):
    existing_news = models.ForeignKey('api.News', null=True, blank=True, on_delete=models.PROTECT, related_name='identity_conflicts')


class LegacyTranslationSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    news = models.ForeignKey('api.News', on_delete=models.PROTECT, related_name='legacy_translation_snapshots')
    field = models.CharField(max_length=16, choices=choices('title', 'content', 'full_content'))
    source_hash = models.CharField(max_length=64)
    translation_hash = models.CharField(max_length=64)
    source_text = models.TextField()
    translated_text = models.TextField()
    origin = models.CharField(max_length=128, default='legacy')
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['news', 'field', 'source_hash', 'translation_hash'], name='rss_legacy_translation_unique'),
            models.CheckConstraint(condition=models.Q(field__in=['title', 'content', 'full_content']), name='rss_legacy_translation_field'),
        ]
