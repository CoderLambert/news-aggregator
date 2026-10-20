"""Explicit local initialization. No network calls and no startup registration."""
from datetime import timedelta, timezone as utc
from hashlib import sha256
import json
from pathlib import Path

from django.apps import apps
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from api.models import Source
from api.rss.feed_policy import approved_feed_policy
from api.rss.models import FeedBinding, RSSInitialization, SourceFeedLink, SourcePublication
from api.rss.operations import canonicalize_feed_url, get_or_create_binding, reconcile_binding

MANIFEST = Path(__file__).with_name('directory_data') / 'defaults-v1.json'


def defaults():
    raw = MANIFEST.read_bytes()
    manifest = json.loads(raw)
    if manifest['version'] != 'curated-tech-ai-dev-v1' or len(manifest['feeds']) != 10:
        raise CommandError('Invalid pinned default source manifest.')
    urls = [canonicalize_feed_url(row['feed_url']) for row in manifest['feeds']]
    if len(urls) != len(set(urls)):
        raise CommandError('Duplicate default feeds.')
    return manifest, sha256(raw).hexdigest()


def cutoff_date(now=None):
    # Miniflux 2.3.3 accepts YYYY-MM-DD, not timestamps. Round the seven-day
    # lower bound UP to UTC midnight so no entry older than seven days is fetched.
    lower = (now or timezone.now()).astimezone(utc.utc) - timedelta(days=7)
    return lower.date() + (timedelta(days=1) if lower.time().isoformat() != '00:00:00' else timedelta())


def counts():
    return {name: apps.get_model('api', name).objects.count() for name in (
        'News', 'Source', 'ChannelSubscription', 'ChannelGroup', 'Favorite', 'NewsReadState',
        'ArticleChatTurn', 'ChatSession', 'ResearchSession', 'FeedBinding')}


def initialization_status(instance, account):
    from django.db.models import Max
    from api.rss.models import FeedOperation, FeedSyncState
    bindings = FeedBinding.objects.filter(engine_instance_uuid=instance, account_id=account,
        source_links__editorial_pin=True).distinct()
    operations = FeedOperation.objects.filter(binding__in=bindings)
    sync = FeedSyncState.objects.filter(engine_instance_uuid=instance, account_id=account).first()
    return {
        'pending_operations': operations.filter(state__in=['pending', 'running', 'retry_wait', 'unknown']).count(),
        'last_operation_at': operations.aggregate(last=Max('updated_at'))['last'],
        'last_sync_at': sync.last_complete_at if sync else None,
        'sources': list(bindings.order_by('canonical_feed_url').values('canonical_feed_url',
            'engine_feed_id', 'connection_state', 'desired_mode', 'published_since', 'last_error')),
    }


def reset_content():
    """Called inside the same transaction as the retained initialization audit.

    User/AI configuration and security/call/collection audits are untouched.
    SourceConfig restrictions survive with their retired Source reference detached.
    """
    def model(name):
        return apps.get_model('api', name)
    model('FeedOperation').objects.update(binding=None, entry=None, lease_token=None,
        lease_until=None, lease_epoch=F('lease_epoch') + 1)
    model('FeedOperation').objects.exclude(state__in=['succeeded', 'failed', 'cancelled']).update(
        state='cancelled', safe_result={'code': 'local_content_reset'})
    for name in ('BodyCandidate', 'IdentityConflict', 'LegacyTranslationSnapshot', 'EngineEntryMap',
                 'News', 'LegacyChatArchive', 'ProviderComparison', 'ResearchSession',
                 'ChannelSubscription', 'ChannelGroup', 'SourceFeedLink', 'SourcePublication'):
        model(name).objects.all().delete()
    model('NewsPreference').objects.update(scope='all', group=None)
    model('SourceConfig').objects.update(source=None)
    Source.objects.all().delete()
    FeedBinding.objects.all().delete()
    model('FeedSyncState').objects.all().delete()
    model('CrawlerTarget').objects.update(enabled=False)
    for name in ('CrawlRun', 'CrawlBatch', 'SearchIndexRun'):
        model(name).objects.filter(status__in=['queued', 'running', 'cancel_requested']).update(status='cancelled')
    model('SearchIndexSettings').objects.update(active_collection='news_embeddings', last_success_at=None,
        worker_heartbeat_at=None, worker_instance_id='', next_run_at=timezone.now())
    # Versioned group proposals contain old source IDs and must not be replayed.
    model('ChannelGroupingProposal').objects.all().delete()
    model('ChannelGroupingConfig').objects.update(bindings={}, revision=F('revision') + 1)


@transaction.atomic
def initialize(instance, account, *, reset=False, backup_path=''):
    manifest, checksum = defaults()
    # Serialize before any read that could decide to clear content.
    RSSInitialization.objects.filter(engine_instance_uuid=instance, account_id=account).update(
        backup_path=F('backup_path'))
    existing = RSSInitialization.objects.filter(engine_instance_uuid=instance, account_id=account,
        manifest_version=manifest['version']).first()
    if existing:
        if existing.manifest_sha256 != checksum or (reset and not existing.reset_content):
            raise CommandError('Initialization identity changed; refusing another content reset.')
        return existing, False
    if reset:
        if FeedBinding.objects.exclude(engine_instance_uuid=instance, account_id=account).exists():
            raise CommandError('Other engine bindings exist; refusing cross-instance reset.')
        reset_content()
    record = RSSInitialization.objects.create(engine_instance_uuid=instance, account_id=account,
        manifest_version=manifest['version'], manifest_sha256=checksum, cutoff_date=cutoff_date(),
        reset_content=reset, backup_path=backup_path)
    from api.models import Category
    Category.objects.get_or_create(name='科技', defaults={'slug': 'technology'})
    for row in manifest['feeds']:
        admission = approved_feed_policy(row['feed_url'])
        binding = get_or_create_binding(instance, account, row['feed_url'], admission.desired_mode)
        if binding.engine_feed_id is not None and binding.published_since != record.cutoff_date:
            raise CommandError('Existing feed has another history bound; explicit reset required.')
        FeedBinding.objects.filter(pk=binding.pk).update(published_since=record.cutoff_date)
        # Only the reviewed default manifest may publish a new source globally.
        source, created = Source.objects.get_or_create(name=row['name'], defaults={
            'url': row['website'], 'language': row['language'], 'region': row['region'], 'country': ''})
        publication = getattr(source, 'publication', None)
        if not created and publication and publication.publication != 'public':
            raise CommandError('Personal source name collision; refusing public promotion.')
        if publication and publication.owner != 'miniflux':
            from api.models import News, ChannelSubscription
            if (News.objects.filter(source=source).exists() or source.feed_links.exists()
                    or ChannelSubscription.objects.filter(source=source).exists()):
                raise CommandError('Existing legacy content requires the explicit local reset or migration workflow.')
            SourcePublication.objects.filter(source=source).update(owner='miniflux',
                epoch=F('epoch') + 1, policy_version=F('policy_version') + 1,
                reading_policy=admission.reading_policy, display_name=row['name'])
        elif publication is None:
            SourcePublication.objects.create(source=source, publication='public', owner='miniflux',
                display_name=row['name'], reading_policy=admission.reading_policy)
        SourceFeedLink.objects.update_or_create(source=source, binding=binding,
            defaults={'editorial_pin': True, 'enabled': True})
        reconcile_binding(binding.pk)
    return record, True
