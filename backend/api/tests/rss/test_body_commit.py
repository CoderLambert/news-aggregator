"""Real SQLite transactions for body CAS, historical translations and quarantine."""
from dataclasses import replace
from io import StringIO
import sqlite3
import uuid
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import F
from django.test import override_settings
from django.utils import timezone

from api.models import (
    BodyCandidate, Category, EngineEntryMap, FeedBinding, FeedSyncState,
    LegacyTranslationSnapshot, News, Source, SourceFeedLink, SourcePublication,
)
from api.rss.content import ConvertedContent, convert_html
from api.rss.content_store import (
    StaleWrite, capture_write_token, commit_body, fenced_article, resolve_candidate,
)
from api.rss.legacy_translation import archive_changed_translations, exact_hash

pytestmark = pytest.mark.django_db


@pytest.fixture
def story():
    source = Source.objects.create(name='rss:test-binding', url='https://publisher.example/')
    category = Category.objects.create(name='Commit test', slug='commit-test')
    feed = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=7, engine_feed_id=11,
        canonical_feed_url='https://publisher.example/feed', desired_enabled=True, connection_state='ready',
        policy_version=3, applied_policy_version=3)
    publication = SourcePublication.objects.create(source=source, publication='personal', owner='miniflux',
        reading_policy='public_feed', epoch=4, policy_version=6)
    link = SourceFeedLink.objects.create(source=source, binding=feed, enabled=True)
    body = 'Old complete body\r\n  preserve spaces  \n'
    news = News.objects.create(source=source, category=category, title='Old title', content='Old summary',
        title_zh='旧标题', content_zh='旧摘要', full_content_zh='唯一旧全文译文', full_content=body,
        full_content_state='complete', full_content_hash=exact_hash(body), full_content_revision=8,
        full_content_provenance={'old': 'preserve-exactly'}, body_owner_binding=feed, body_owner_version=5,
        publish_time=timezone.now(), url='https://publisher.example/article')
    entry = EngineEntryMap.objects.create(binding=feed, engine_entry_id=42, news=news, source_url=news.url, disposition='linked')
    token = capture_write_token(news_id=news.pk, source_id=source.pk, entry_id=entry.pk)
    return news, source, feed, publication, link, entry, token


def converted(text='A safe readable new body with details.'):
    return ConvertedContent(text, exact_hash('raw:' + text), exact_hash(text), 'test-conversion-v1')


def test_accept_updates_revision_and_archives_only_changed_full_text(story):
    news, _, _, _, _, entry, token = story
    old = news.full_content
    result = commit_body(token, convert_html('<p>New readable unknown content.</p>', base_url=news.url))
    assert result.status == 'accepted' and result.revision == 9
    news.refresh_from_db()
    entry.refresh_from_db()
    assert news.full_content == 'New readable unknown content.'
    assert news.full_content_state == 'available' and news.full_content_completeness == 'unknown'
    assert news.full_content_revision == 9 and news.body_owner_version == 5
    assert news.full_content_hash == exact_hash(news.full_content)
    assert news.full_content_zh == '' and news.title_zh == '旧标题' and news.content_zh == '旧摘要'
    snapshot = LegacyTranslationSnapshot.objects.get(news=news)
    assert (snapshot.source_text, snapshot.translated_text, snapshot.origin) == (old, '唯一旧全文译文', 'legacy')
    assert snapshot.source_hash == exact_hash(old) and snapshot.translation_hash == exact_hash('唯一旧全文译文')
    assert news.full_content_provenance['engine_entry_id'] == 42
    assert entry.raw_hash == news.full_content_provenance['raw_hash']


def test_same_exact_bytes_preserve_revision_hash_provenance_and_translations(story):
    news, _, _, _, _, _, token = story
    # A historical hash may be uninitialized; unchanged content must not "repair" it.
    News.objects.filter(pk=news.pk).update(full_content_hash='historical-stored-hash')
    result = commit_body(token, converted(news.full_content))
    assert result.status == 'unchanged'
    news.refresh_from_db()
    assert news.full_content_revision == 8 and news.full_content_hash == 'historical-stored-hash'
    assert news.full_content_zh == '唯一旧全文译文' and news.full_content_state == 'complete'
    assert news.full_content_provenance == {'old': 'preserve-exactly'}
    assert not LegacyTranslationSnapshot.objects.exists()


@pytest.mark.parametrize('change', [
    'paused', 'source_epoch', 'source_policy', 'owner_binding', 'owner_version', 'revision', 'url',
    'binding_policy', 'unapplied', 'disabled', 'not_ready', 'entry_url', 'entry_news', 'entry_id',
    'engine_instance', 'engine_account', 'engine_feed', 'link_disabled', 'missing_publication', 'unclaimed',
])
def test_stale_tokens_cannot_write_archive_or_advance_cursor(story, change):
    news, source, feed, publication, link, entry, token = story
    sync = FeedSyncState.objects.create(engine_instance_uuid=feed.engine_instance_uuid, account_id=7, new_cursor=40, page_cursor=40)
    mutations = {
        'paused': lambda: SourcePublication.objects.filter(pk=source.pk).update(owner='paused'),
        'source_epoch': lambda: SourcePublication.objects.filter(pk=source.pk).update(epoch=5),
        'source_policy': lambda: SourcePublication.objects.filter(pk=source.pk).update(policy_version=7),
        'owner_binding': lambda: News.objects.filter(pk=news.pk).update(body_owner_binding=None, body_owner_source=source),
        'owner_version': lambda: News.objects.filter(pk=news.pk).update(body_owner_version=6),
        'revision': lambda: News.objects.filter(pk=news.pk).update(full_content_revision=9),
        'url': lambda: News.objects.filter(pk=news.pk).update(url='https://publisher.example/changed'),
        'binding_policy': lambda: FeedBinding.objects.filter(pk=feed.pk).update(policy_version=4),
        'unapplied': lambda: FeedBinding.objects.filter(pk=feed.pk).update(applied_policy_version=2),
        'disabled': lambda: FeedBinding.objects.filter(pk=feed.pk).update(desired_enabled=False),
        'not_ready': lambda: FeedBinding.objects.filter(pk=feed.pk).update(connection_state='paused'),
        'entry_url': lambda: EngineEntryMap.objects.filter(pk=entry.pk).update(source_url='https://other.example/wrong'),
        'entry_news': lambda: EngineEntryMap.objects.filter(pk=entry.pk).update(news=None),
        'entry_id': lambda: EngineEntryMap.objects.filter(pk=entry.pk).update(engine_entry_id=43),
        'engine_instance': lambda: FeedBinding.objects.filter(pk=feed.pk).update(engine_instance_uuid=uuid.uuid4()),
        'engine_account': lambda: FeedBinding.objects.filter(pk=feed.pk).update(account_id=8),
        'engine_feed': lambda: FeedBinding.objects.filter(pk=feed.pk).update(engine_feed_id=12),
        'link_disabled': lambda: SourceFeedLink.objects.filter(pk=link.pk).update(enabled=False),
        'missing_publication': lambda: SourcePublication.objects.filter(pk=source.pk).delete(),
        'unclaimed': lambda: News.objects.filter(pk=news.pk).update(body_owner_binding=None),
    }
    mutations[change]()
    result = commit_body(token, converted())
    assert result.status == 'stale'
    news.refresh_from_db()
    sync.refresh_from_db()
    assert news.full_content == 'Old complete body\r\n  preserve spaces  \n'
    assert news.full_content_zh == '唯一旧全文译文'
    assert not LegacyTranslationSnapshot.objects.exists() and not BodyCandidate.objects.exists()
    assert sync.new_cursor == sync.page_cursor == 40


def test_invalid_content_still_checks_current_entry_identity(story):
    _, _, _, _, _, entry, token = story
    EngineEntryMap.objects.filter(pk=entry.pk).update(engine_entry_id=43)
    assert commit_body(token, converted('')).status == 'stale'


@pytest.mark.parametrize('text,completeness,evidence,reason', [
    ('', 'unknown', {}, 'empty_content'),
    ('   ', 'unknown', {}, 'empty_content'),
    ('Access denied', 'unknown', {}, 'explicit_error_content'),
    ('Some error response', 'unknown', {'error_code': 'upstream_failed'}, 'explicit_error_content'),
    ('Short summary', 'summary', {}, 'summary_cannot_replace_complete'),
    ('Claims verified', 'verified', {}, 'verification_not_hash_bound'),
])
def test_rejected_content_preserves_old_complete(story, text, completeness, evidence, reason):
    news, *_, token = story
    result = commit_body(token, converted(text), completeness=completeness, evidence=evidence)
    assert (result.status, result.reason) == ('rejected', reason)
    news.refresh_from_db()
    assert news.full_content_revision == 8 and news.full_content_zh == '唯一旧全文译文'
    assert not LegacyTranslationSnapshot.objects.exists()


def test_canonical_hash_and_size_are_checked_without_truncation(story):
    news, *_, token = story
    assert commit_body(token, replace(converted(), canonical_hash='0' * 64)).reason == 'canonical_hash_mismatch'
    with override_settings(RSS_MAX_MARKDOWN_BYTES=3):
        assert commit_body(token, converted('中文')).reason == 'markdown_too_large'
    assert not BodyCandidate.objects.exists()
    news.refresh_from_db()
    assert news.full_content_revision == 8


def test_summary_policy_applies_even_to_same_body_and_new_unknown(story):
    news, source, _, _, _, _, token = story
    SourcePublication.objects.filter(pk=source.pk).update(reading_policy='summary_only', policy_version=7)
    assert commit_body(token, converted(news.full_content)).status == 'stale'
    token = capture_write_token(news_id=news.pk, source_id=source.pk, entry_id=token.entry_id)
    assert commit_body(token, converted(news.full_content)).reason == 'summary_only_policy'
    News.objects.filter(pk=news.pk).update(full_content='', full_content_state='missing', full_content_zh='')
    # A summary may become the stored readable content when there is no complete body.
    assert commit_body(token, converted('Readable summary'), completeness='summary').status == 'accepted'


def quarantine(story):
    news, *_, token = story
    News.objects.filter(pk=news.pk).update(full_content='a' * 1000, full_content_hash=exact_hash('a' * 1000))
    return commit_body(token, converted('b' * 499))


def test_shortening_dedupes_and_explicit_accept_rechecks_then_archives(story):
    news, *_, token = story
    first = quarantine(story)
    second = commit_body(token, converted('b' * 499))
    assert first.status == second.status == 'quarantined' and first.candidate_id == second.candidate_id
    assert BodyCandidate.objects.count() == 1 and not LegacyTranslationSnapshot.objects.exists()
    result = resolve_candidate(first.candidate_id, decision='accept')
    assert result.status == 'accepted'
    news.refresh_from_db()
    assert news.full_content == 'b' * 499 and news.full_content_revision == 9
    assert LegacyTranslationSnapshot.objects.get().source_text == 'a' * 1000
    assert resolve_candidate(first.candidate_id, decision='accept').status == 'stale'


def test_shrink_threshold_is_configurable_and_does_not_claim_verified(story):
    news, *_, token = story
    News.objects.filter(pk=news.pk).update(full_content='a' * 1500)
    with override_settings(RSS_BODY_SHRINK_MIN_CHARS=2000):
        assert commit_body(token, converted('short unknown content')).status == 'accepted'
    news.refresh_from_db()
    assert news.full_content_completeness == 'unknown'


@pytest.mark.parametrize('decision', ['accept', 'reject'])
def test_quarantine_resolution_does_not_bypass_policy_or_ownership(story, decision):
    news, source, *_, token = story
    pending = quarantine(story)
    SourcePublication.objects.filter(pk=source.pk).update(epoch=F('epoch') + 1)
    result = resolve_candidate(pending.candidate_id, decision=decision)
    assert result.status == 'stale'
    news.refresh_from_db()
    assert news.full_content_revision == 8 and news.full_content == 'a' * 1000
    assert BodyCandidate.objects.get().state == 'quarantined'
    assert not LegacyTranslationSnapshot.objects.exists()


def test_reject_and_command_dry_run_never_apply_candidate(story):
    news, *_, token = story
    pending = quarantine(story)
    stdout = StringIO()
    call_command('rss_body_candidate', str(pending.candidate_id), 'accept', stdout=stdout)
    assert 'dry-run' in stdout.getvalue() and BodyCandidate.objects.get().state == 'quarantined'
    call_command('rss_body_candidate', str(pending.candidate_id), 'reject', execute=True, stdout=StringIO())
    assert BodyCandidate.objects.get().state == 'rejected'
    news.refresh_from_db()
    assert news.full_content_revision == 8 and news.full_content == 'a' * 1000
    with pytest.raises(CommandError):
        call_command('rss_body_candidate', 'not-a-uuid', 'accept', execute=True)


@pytest.mark.parametrize('failure_point', ['after_archive', 'after_body_update'])
def test_failure_rolls_back_body_entry_snapshot_candidate_and_allows_replay(story, failure_point):
    news, *_, entry, token = story
    original_archive = archive_changed_translations

    def fail_after_archive(*args, **kwargs):
        original_archive(*args, **kwargs)
        assert LegacyTranslationSnapshot.objects.count() == 1
        raise RuntimeError('synthetic-interruption')

    target = 'archive_changed_translations' if failure_point == 'after_archive' else '_finish'
    effect = fail_after_archive if failure_point == 'after_archive' else RuntimeError('synthetic-interruption')
    with patch(f'api.rss.content_store.{target}', side_effect=effect), pytest.raises(RuntimeError):
        commit_body(token, converted())
    news.refresh_from_db()
    entry.refresh_from_db()
    assert news.full_content_revision == 8 and news.full_content_zh == '唯一旧全文译文'
    assert entry.raw_hash == '' and not LegacyTranslationSnapshot.objects.exists() and not BodyCandidate.objects.exists()
    assert commit_body(token, converted()).status == 'accepted'
    assert LegacyTranslationSnapshot.objects.count() == 1


def test_shared_metadata_helper_archives_all_changed_fields_atomically(story):
    news, *_, token = story
    replacements = {'title': 'New title', 'content': 'New summary'}
    with pytest.raises(RuntimeError):
        with fenced_article(token) as current:
            clearing = archive_changed_translations(current, replacements)
            assert LegacyTranslationSnapshot.objects.count() == 2
            News.objects.filter(pk=current.pk).update(**replacements, **clearing)
            raise RuntimeError('abort outer metadata transaction')
    assert LegacyTranslationSnapshot.objects.count() == 0
    news.refresh_from_db()
    assert news.title_zh == '旧标题' and news.content_zh == '旧摘要'
    with fenced_article(token) as current:
        clearing = archive_changed_translations(current, replacements)
        News.objects.filter(pk=current.pk).update(**replacements, **clearing)
    snapshots = {row.field: row for row in LegacyTranslationSnapshot.objects.all()}
    assert snapshots['title'].source_text == 'Old title' and snapshots['title'].translated_text == '旧标题'
    assert snapshots['content'].source_text == 'Old summary' and snapshots['content'].translated_text == '旧摘要'
    with fenced_article(token) as current:
        assert archive_changed_translations(current, replacements) == {}
    news.refresh_from_db()
    assert news.title_zh == news.content_zh == '' and news.full_content_zh == '唯一旧全文译文'
    assert news.full_content_revision == 8 and len(snapshots) == 2


def test_legacy_fence_cannot_cross_another_sources_body_owner(story):
    news, source, _, _, _, _, _ = story
    SourcePublication.objects.filter(pk=source.pk).update(owner='legacy')
    with pytest.raises(StaleWrite, match='legacy_not_body_owner'):
        capture_write_token(news_id=news.pk, source_id=source.pk)
    News.objects.filter(pk=news.pk).update(body_owner_binding=None, body_owner_source=source, body_owner_version=6)
    legacy = capture_write_token(news_id=news.pk, source_id=source.pk)
    with fenced_article(legacy) as current:
        assert current.pk == news.pk
    # ABA restore of the source owner still invalidates the captured source epoch.
    SourcePublication.objects.filter(pk=source.pk).update(epoch=6)
    with pytest.raises(StaleWrite):
        with fenced_article(legacy):
            pytest.fail('old legacy token must not enter update section')


@pytest.mark.django_db(transaction=True)
def test_sqlite_writer_reservation_prevents_policy_change_during_archive(story):
    news, source, *_, token = story
    original_archive = archive_changed_translations
    database = connection.settings_dict['NAME']
    competitor = sqlite3.connect(database, uri=True, timeout=0.02)
    blocked = []

    def archive_with_competing_policy_writer(*args, **kwargs):
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            competitor.execute('UPDATE api_sourcepublication SET policy_version=policy_version+1 WHERE source_id=?', [source.pk])
        competitor.rollback()
        blocked.append(True)
        return original_archive(*args, **kwargs)

    try:
        with patch('api.rss.content_store.archive_changed_translations', side_effect=archive_with_competing_policy_writer):
            assert commit_body(token, converted()).status == 'accepted'
        assert blocked == [True]
        competitor.execute('UPDATE api_sourcepublication SET policy_version=policy_version+1 WHERE source_id=?', [source.pk])
        competitor.commit()
        assert commit_body(token, converted('late result')).status == 'stale'
    finally:
        competitor.close()


def test_quarantine_captures_engine_identity_for_later_resolution(story):
    news, _, feed, _, _, _, _ = story
    pending = quarantine(story)
    FeedBinding.objects.filter(pk=feed.pk).update(engine_instance_uuid=uuid.uuid4())
    result = resolve_candidate(pending.candidate_id, decision='accept')
    assert result.status == 'stale' and result.reason == 'engine_identity_changed'
    news.refresh_from_db()
    assert news.full_content == 'a' * 1000 and news.full_content_zh == '唯一旧全文译文'


def test_explicit_rejection_remains_rejected_on_identical_replay(story):
    news, *_, token = story
    pending = quarantine(story)
    assert resolve_candidate(pending.candidate_id, decision='reject').reason == 'operator_rejected'
    replay = commit_body(token, converted('b' * 499))
    assert replay.status == 'rejected' and replay.reason == 'operator_rejected'
    assert replay.candidate_id == pending.candidate_id and BodyCandidate.objects.count() == 1
    news.refresh_from_db()
    assert news.full_content_revision == 8


def test_verified_evidence_is_bound_to_current_hash_and_not_inherited(story):
    news, source, _, _, _, entry, token = story
    first = converted('Verified body with retained evidence.')
    assert commit_body(token, first, completeness='verified', evidence={'verified_canonical_hash': first.canonical_hash}).status == 'accepted'
    news.refresh_from_db()
    assert news.full_content_completeness == 'verified'
    current = capture_write_token(news_id=news.pk, source_id=source.pk, entry_id=entry.pk)
    assert commit_body(current, converted('Next changed unknown readable body.')).status == 'accepted'
    news.refresh_from_db()
    assert news.full_content_completeness == 'unknown' and news.full_content_revision == 10


def test_summary_never_replaces_verified_available_body(story):
    news, *_, token = story
    News.objects.filter(pk=news.pk).update(full_content_state='available', full_content_completeness='verified')
    result = commit_body(token, converted('Summary must not overwrite verified body'), completeness='summary')
    assert result.reason == 'summary_cannot_replace_complete'
    news.refresh_from_db()
    assert news.full_content_revision == 8 and news.full_content_completeness == 'verified'


def test_outer_transaction_can_roll_back_accepted_body_with_caller_cursor(story):
    from django.db import transaction
    news, _, feed, _, _, _, token = story
    state = FeedSyncState.objects.create(engine_instance_uuid=feed.engine_instance_uuid, account_id=7, new_cursor=41)
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            assert commit_body(token, converted()).status == 'accepted'
            FeedSyncState.objects.filter(pk=state.pk).update(new_cursor=42)
            raise RuntimeError('caller page failed')
    news.refresh_from_db()
    state.refresh_from_db()
    assert state.new_cursor == 41 and news.full_content_revision == 8
    assert news.full_content_zh == '唯一旧全文译文'
    assert not BodyCandidate.objects.exists() and not LegacyTranslationSnapshot.objects.exists()
