"""Local initialization/reset semantics on disposable data, never a site database."""
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from api.ai_connection_models import UserAIConnection
from api.models import (
    AuthSecurityLock, Category, ChannelGroup, ChannelGroupRoot, ChannelSubscription,
    ChatSession, Favorite, News, Source,
)
from api.rss.initialize import cutoff_date, initialize
from api.rss.models import FeedBinding, FeedOperation, RSSInitialization, SourceFeedLink, EngineEntryMap
from api.rss.import_models import RssImportBatch, RssImportItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def local(monkeypatch, settings):
    settings.RSS_FULL_CONTENT_ENABLED = True
    instance = uuid.uuid4()
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(instance))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '3')
    monkeypatch.setenv('RSS_ENGINE_BASE_URL', 'http://miniflux:8080')
    monkeypatch.setenv('NEWSHUB_LOCAL_INSTANCE', str(instance))
    return instance


def paired_backup(path, instance):
    path.mkdir(mode=0o700)
    hashes = {}
    for name in ('application.sqlite3', 'miniflux.dump', 'configuration.tar'):
        # Unit boundary only; real archive restoration is a separate runtime check.
        raw = ('synthetic paired artifact ' + name).encode()
        (path / name).write_bytes(raw)
        hashes[name] = sha256(raw).hexdigest()
    (path / 'backup.json').write_text(json.dumps({'instance_uuid': str(instance), 'account_id': 3, 'sha256': hashes}))
    return path


def test_preview_is_read_only_and_apply_requires_the_explicit_local_identity(local, monkeypatch):
    before = (Source.objects.count(), FeedBinding.objects.count())
    out = StringIO()
    call_command('rss_initialize', local_instance=str(local), stdout=out)
    assert json.loads(out.getvalue())['preview']
    assert (Source.objects.count(), FeedBinding.objects.count()) == before
    monkeypatch.delenv('NEWSHUB_LOCAL_INSTANCE')
    with pytest.raises(CommandError, match='explicitly marked local'):
        call_command('rss_initialize', local_instance=str(local), apply=True)
    assert not RSSInitialization.objects.exists()


def test_reset_preserves_accounts_configuration_audits_and_replay_preserves_new_content(local, tmp_path):
    user = get_user_model().objects.create_user('keep-account', password='synthetic-only')
    connection = UserAIConnection.objects.create(user=user, provider_id='openai', endpoint_profile='openai',
        display_name='Keep model connection', request_hash='a' * 64, credential_ciphertext='synthetic-encrypted')
    audit = AuthSecurityLock.objects.create(id=91, revision=42)
    source = Source.objects.create(name='Old channel', url='https://old.example/')
    category = Category.objects.create(name='Old taxonomy', slug='old-taxonomy')
    news = News.objects.create(title='Old', url='https://old.example/story', source=source, category=category,
        content='old content', publish_time=datetime.now(timezone.utc))
    Favorite.objects.create(user=user, news=news)
    ChatSession.objects.create(user=user, news=news, messages=[{'role': 'assistant', 'content': 'private'}])
    subscription = ChannelSubscription.objects.create(user=user, source=source)
    group_root = ChannelGroupRoot.objects.create(user=user, name='Old root')
    ChannelGroup.objects.create(user=user, root=group_root, name='Old child').subscriptions.add(subscription)
    operation = FeedOperation.objects.create(kind='discover', actor=user, dedupe_key='audit-operation', request_hash='b' * 64)
    old_binding = FeedBinding.objects.create(engine_instance_uuid=local, account_id=3,
        engine_feed_id=7, canonical_feed_url='https://old.example/feed')
    old_entry = EngineEntryMap.objects.create(binding=old_binding, engine_entry_id=1,
        news=news, source_url=news.url, disposition='linked')
    handoff = FeedOperation.objects.create(kind='refetch_entry', actor=user, binding=old_binding,
        entry=old_entry, dedupe_key='old-handoff', request_hash='c' * 64, state='succeeded',
        safe_result={'pending_sync': True, 'connected': True})
    batch = RssImportBatch.objects.create(user=user, file_hash='d' * 64, preview_token_hash='e' * 64,
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc), status='confirmed')
    RssImportItem.objects.create(batch=batch, feed_url='https://old.example/resurrect', status='pending')
    backup = paired_backup(tmp_path / 'paired', local)
    call_command('rss_initialize', local_instance=str(local), apply=True, reset_content=True,
        backup_dir=str(backup), stdout=StringIO())
    assert not News.objects.exists() and not Favorite.objects.exists() and not ChatSession.objects.exists()
    assert not ChannelSubscription.objects.exists()
    assert not ChannelGroup.objects.exists() and not ChannelGroupRoot.objects.exists()
    assert not RssImportBatch.objects.exists() and not RssImportItem.objects.exists()
    handoff.refresh_from_db()
    assert handoff.state == 'succeeded' and handoff.safe_result['pending_sync'] is False
    assert handoff.binding_id is None and handoff.entry_id is None
    assert get_user_model().objects.get(pk=user.pk).check_password('synthetic-only')
    assert UserAIConnection.objects.get(pk=connection.pk).credential_ciphertext == 'synthetic-encrypted'
    assert AuthSecurityLock.objects.get(pk=audit.pk).revision == 42
    assert FeedOperation.objects.filter(pk=operation.pk, state='cancelled').exists()
    assert Source.objects.count() == FeedBinding.objects.count() == 10
    assert SourceFeedLink.objects.filter(editorial_pin=True, enabled=True).count() == 10
    assert not FeedBinding.objects.filter(published_since__isnull=True).exists()
    fresh = News.objects.create(title='New', url='https://new.example/story', source=Source.objects.first(),
        category=category, content='new content', publish_time=datetime.now(timezone.utc))
    call_command('rss_initialize', local_instance=str(local), apply=True, reset_content=True, stdout=StringIO())
    assert News.objects.get(pk=fresh.pk).content == 'new content'
    assert RSSInitialization.objects.count() == 1
    assert FeedBinding.objects.count() == 10


def test_reset_refuses_missing_tampered_or_wrong_instance_backup(local, tmp_path):
    with pytest.raises(CommandError, match='backup'):
        call_command('rss_initialize', local_instance=str(local), apply=True, reset_content=True,
            backup_dir=str(tmp_path / 'missing'), stdout=StringIO())
    backup = paired_backup(tmp_path / 'wrong', uuid.uuid4())
    with pytest.raises(CommandError, match='another engine'):
        call_command('rss_initialize', local_instance=str(local), apply=True, reset_content=True,
            backup_dir=str(backup), stdout=StringIO())
    assert not RSSInitialization.objects.exists()


def test_additive_initialization_respects_opt_out_and_cannot_later_reset_same_version(local, settings):
    settings.RSS_FULL_CONTENT_ENABLED = False
    record, changed = initialize(local, 3)
    assert changed and not FeedBinding.objects.exclude(desired_mode='feed').exists()
    with pytest.raises(CommandError, match='another content reset'):
        initialize(local, 3, reset=True)
    assert RSSInitialization.objects.get(pk=record.pk).reset_content is False


def test_date_rounding_never_includes_articles_older_than_seven_days():
    assert str(cutoff_date(datetime(2026, 10, 20, 0, tzinfo=timezone.utc))) == '2026-10-13'
    assert str(cutoff_date(datetime(2026, 10, 20, 12, tzinfo=timezone.utc))) == '2026-10-14'
    assert str(cutoff_date(datetime(2026, 1, 2, 12, tzinfo=timezone.utc))) == '2025-12-27'


def test_remote_local_marker_cannot_reset_even_with_backup(local, tmp_path, monkeypatch):
    backup = paired_backup(tmp_path / 'remote', local)
    monkeypatch.setenv('RSS_ENGINE_BASE_URL', 'https://production.example')
    with pytest.raises(CommandError, match='explicitly marked local'):
        call_command('rss_initialize', local_instance=str(local), apply=True, reset_content=True,
            backup_dir=str(backup), stdout=StringIO())
    assert not RSSInitialization.objects.exists()
