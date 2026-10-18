"""Real SQLite coverage for T09 cursors, two-read fencing and body handoff."""
from concurrent.futures import Future
from dataclasses import replace
from datetime import timedelta
import uuid
from unittest.mock import patch

import pytest
from django.db import OperationalError, transaction
from django.utils import timezone

from api.models import (Category, EngineEntryMap, FeedBinding, FeedOperation, FeedRejection,
    FeedSyncState, IdentityConflict, LegacyTranslationSnapshot, News, Source, SourceFeedLink, SourcePublication)
from api.rss.engine import EngineConfig, EngineError, EntryDTO
from api.rss.reconciliation import (SyncWorker, acquire_lease, begin_run, finish_page,
    health_snapshot, release_lease, reserve_lease)
from api.rss.sync import commit_entry, commit_refetch, prepare_page, prepare_refetch, sync_metadata
from api.rss.content_store import StaleWrite

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(settings):
    settings.RSS_FULL_CONTENT_ENABLED = True
    source = Source.objects.create(name='sync-source', url='https://publisher.example/')
    Category.objects.create(name='科技', slug='technology')
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=2, engine_feed_id=5,
        canonical_feed_url='https://publisher.example/rss', desired_enabled=True,
        desired_mode='full_content', connection_state='ready', applied_policy_version=1)
    SourcePublication.objects.create(source=source, owner='miniflux', publication='public', reading_policy='public_feed')
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
    lease = acquire_lease(binding.engine_instance_uuid, 2)
    config = EngineConfig(str(binding.engine_instance_uuid), 2, 'http://engine:8080', 'synthetic',
                          full_content_enabled=True)
    dto = EntryDTO(str(binding.engine_instance_uuid), 2, 5, 10, 'First title',
        'https://publisher.example/story', 'https://publisher.example/discussion', 'Author',
        '<p>A readable article.</p>', '2020-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
    return source, binding, lease, config, dto


def capture(setup, dto=None):
    _, _, _, config, initial = setup
    dto = dto or initial
    return prepare_page([dto], instance_uuid=config.engine_instance_uuid, account_id=2)[dto.id]


def commit(setup, dto=None, fence=None):
    dto = dto or setup[-1]
    return commit_entry(dto, fence or capture(setup, dto), reserve=lambda: reserve_lease(setup[2]))


def test_new_article_and_exact_replay_preserve_identity_and_translation(setup):
    assert commit(setup).status == 'accepted'
    news = News.objects.get()
    assert news.source_id == setup[0].pk and news.body_owner_binding_id == setup[1].pk
    assert news.publish_time.year == 2020 and news.full_content_revision == 1
    assert sync_metadata(news) == {'publish_time_inferred': False, 'summary_version': 'rss-summary-v1:500'}
    News.objects.filter(pk=news.pk).update(full_content_zh='唯一译文')
    assert commit(setup).status == 'unchanged'
    news.refresh_from_db()
    assert news.full_content_zh == '唯一译文' and news.full_content_revision == 1
    assert EngineEntryMap.objects.count() == News.objects.count() == 1


def test_same_html_updates_metadata_and_archives_title_and_summary(setup):
    commit(setup)
    news = News.objects.get()
    News.objects.filter(pk=news.pk).update(title_zh='旧标题', content='Legacy summary', content_zh='旧摘要')
    assert commit(setup, replace(setup[-1], title='Revised title')).status == 'unchanged'
    news.refresh_from_db()
    assert news.title == 'Revised title' and news.title_hash is not None
    assert news.full_content_revision == 1 and news.title_zh == news.content_zh == ''
    assert set(LegacyTranslationSnapshot.objects.values_list('field', flat=True)) == {'title', 'content'}


@pytest.mark.parametrize('mutation', ['source_epoch', 'policy', 'owner', 'source_name', 'source_url', 'source_region', 'news_source', 'news_category', 'body_owner', 'revision', 'unapplied', 'link', 'map', 'instance', 'account', 'feed'])
def test_second_get_cannot_refresh_authorization(setup, mutation):
    commit(setup)
    fence = capture(setup)
    source, binding, _, _, dto = setup
    if mutation == 'source_epoch':
        SourcePublication.objects.filter(source=source).update(epoch=2)
    elif mutation == 'policy':
        SourcePublication.objects.filter(source=source).update(policy_version=2)
    elif mutation == 'owner':
        SourcePublication.objects.filter(source=source).update(owner='legacy')
    elif mutation == 'source_name':
        Source.objects.filter(pk=source.pk).update(name='Renamed source after discovery')
    elif mutation == 'source_url':
        Source.objects.filter(pk=source.pk).update(url='https://changed.example/')
    elif mutation == 'source_region':
        Source.objects.filter(pk=source.pk).update(region='domestic')
    elif mutation == 'news_source':
        unrelated = Source.objects.create(name='Unrelated source after discovery', url='https://other.example/')
        News.objects.update(source=unrelated)
    elif mutation == 'news_category':
        category = Category.objects.create(name='Reclassified after discovery', slug='reclassified-after-discovery')
        News.objects.update(category=category)
    elif mutation == 'body_owner':
        News.objects.update(body_owner_binding=None, body_owner_source=source, body_owner_version=2)
    elif mutation == 'revision':
        News.objects.update(full_content_revision=2)
    elif mutation == 'unapplied':
        FeedBinding.objects.filter(pk=binding.pk).update(policy_version=2)
    elif mutation == 'instance':
        FeedBinding.objects.filter(pk=binding.pk).update(engine_instance_uuid=uuid.uuid4())
    elif mutation == 'account':
        FeedBinding.objects.filter(pk=binding.pk).update(account_id=3)
    elif mutation == 'feed':
        FeedBinding.objects.filter(pk=binding.pk).update(engine_feed_id=9)
    elif mutation == 'link':
        SourceFeedLink.objects.filter(binding=binding).update(enabled=False)
    else:
        EngineEntryMap.objects.update(source_url='https://publisher.example/other')
    with pytest.raises(StaleWrite):
        commit(setup, replace(dto, title='Late title'), fence)
    assert News.objects.get().title == dto.title


def test_second_get_new_url_and_concurrent_creation_are_stale(setup):
    fence = capture(setup)
    with pytest.raises(StaleWrite):
        commit(setup, replace(setup[-1], url='https://publisher.example/other'), fence)
    commit(setup)
    with pytest.raises(StaleWrite):
        commit(setup, fence=fence)
    assert News.objects.count() == 1


def test_summary_empty_and_shortening_do_not_destroy_complete(setup):
    commit(setup)
    news = News.objects.get()
    News.objects.filter(pk=news.pk).update(full_content='x' * 1500, full_content_state='complete', full_content_zh='旧译文')
    assert commit(setup).status == 'quarantined'
    assert commit(setup, replace(setup[-1], content='')).status == 'rejected'
    SourcePublication.objects.update(reading_policy='summary_only', policy_version=2)
    assert commit(setup).status == 'rejected'
    news.refresh_from_db()
    assert news.full_content == 'x' * 1500 and news.full_content_zh == '旧译文'


def test_non_owner_binding_can_only_associate(setup):
    commit(setup)
    original = News.objects.get()
    second = FeedBinding.objects.create(engine_instance_uuid=setup[1].engine_instance_uuid, account_id=2,
        engine_feed_id=6, canonical_feed_url='https://publisher.example/second', desired_enabled=True,
        connection_state='ready', applied_policy_version=1)
    SourceFeedLink.objects.create(source=setup[0], binding=second, enabled=True)
    dto = replace(setup[-1], feed_id=6, id=11, title='Other feed title', content='<p>Different.</p>')
    result = commit(setup, dto)
    assert result.status == 'unchanged' and result.reason == 'association_only'
    original.refresh_from_db()
    assert original.title == 'First title' and original.full_content == 'A readable article.'
    assert EngineEntryMap.objects.count() == 2


def test_inferred_date_never_replaces_trusted_or_unknown_legacy_date(setup):
    commit(setup)
    dto = replace(setup[-1], published_at=None, created_at='2026-06-01T00:00:00Z')
    commit(setup, dto)
    news = News.objects.get()
    assert news.publish_time.year == 2020
    News.objects.update(full_content_provenance={})
    commit(setup, dto)
    assert News.objects.get().publish_time.year == 2020


def test_new_inferred_date_is_upgraded_and_metadata_survives_body_commit(setup):
    commit(setup, replace(setup[-1], published_at=None))
    assert sync_metadata(News.objects.get())['publish_time_inferred']
    commit(setup, replace(setup[-1], content='<p>New body.</p>'))
    news = News.objects.get()
    assert news.publish_time.year == 2020 and not sync_metadata(news)['publish_time_inferred']
    assert news.full_content_provenance['engine_entry_id'] == 10


@pytest.mark.parametrize('change,reason', [({'title': ''}, 'invalid_title'),
    ({'author': 'x' * 101}, 'author_too_long'), ({'url': 'file:///etc/passwd'}, 'invalid_article_url')])
def test_deterministic_rejection_is_persisted(setup, change, reason):
    assert commit(setup, replace(setup[-1], **change)).reason == reason
    assert FeedRejection.objects.get().reason == reason and not News.objects.exists()


def test_unknown_filter_fails_closed(setup):
    SourceFeedLink.objects.update(association_policy={'version': 1, 'mode': 'unreviewed'})
    assert commit(setup).reason == 'unsupported_association_policy'
    assert not News.objects.exists()


def test_body_failure_rolls_back_metadata_membership_and_snapshot(setup):
    commit(setup)
    News.objects.update(title_zh='旧标题')
    with patch('api.rss.sync.commit_body', side_effect=OperationalError('locked')):
        with pytest.raises(OperationalError):
            commit(setup, replace(setup[-1], title='Lost title'))
    assert News.objects.get().title == 'First title'
    assert not LegacyTranslationSnapshot.objects.exists()


def test_cursor_advance_completion_and_lease_epoch(setup):
    lease = setup[2]
    state = begin_run(lease, 20, lookback=0)
    assert health_snapshot(setup[1].engine_instance_uuid, 2)['last_successful_incremental'] is None
    commit(setup)
    assert not finish_page(lease, run_id=state.run_id, upper=20, lower=0, ids=[10])
    state.refresh_from_db()
    assert state.new_cursor == 0 and state.page_cursor == 10 and state.upper_id == 20
    assert finish_page(lease, run_id=state.run_id, upper=20, lower=10, ids=[])
    state.refresh_from_db()
    assert state.new_cursor == 20 and state.last_complete_at
    old = lease
    release_lease(lease)
    newer = acquire_lease(setup[1].engine_instance_uuid, 2)
    assert newer.epoch > old.epoch
    with pytest.raises(StaleWrite):
        reserve_lease(old)


class Engine:
    def __init__(self, entries):
        self.entries = entries
        self.reads = []
        self.fail = False
    def read_upper_bound(self):
        return max((e.id for e in self.entries), default=0)
    def list_entries(self, *, lower, upper, limit):
        self.reads.append((lower, upper, limit))
        if self.fail:
            raise EngineError('timeout', retryable=True)
        return sorted([e for e in self.entries if lower < e.id <= upper], key=lambda e: e.id)[:limit]
    def get_entry(self, entry_id):
        return next(e for e in self.entries if e.id == entry_id)


class Reads:
    def __init__(self, engine):
        self.engine = engine
    def submit_short_read(self, callback):
        future = Future()
        try:
            future.set_result(callback(self.engine))
        except Exception as error:
            future.set_exception(error)
        return future


def worker(setup, entries, **kwargs):
    release_lease(setup[2])
    engine = Engine(entries)
    result = SyncWorker(Reads(engine), setup[3], page_size=1, **kwargs)
    return result, engine


def tick_until(worker, predicate, limit=100):
    for _ in range(limit):
        worker.retry_at = 0
        worker.tick()
        if predicate():
            return
    pytest.fail('worker did not converge: ' + repr(worker.status()))


def test_fixed_upper_old_date_high_id_low_id_late_and_retained_update(setup):
    dto = setup[-1]
    task, engine = worker(setup, [dto], incremental_seconds=0, reconcile_seconds=0)
    tick_until(task, lambda: FeedSyncState.objects.get().upper_id == 10)
    engine.entries.append(replace(dto, id=30, url='https://publisher.example/old', published_at='1990-01-01T00:00:00Z'))
    tick_until(task, lambda: FeedSyncState.objects.get().new_cursor == 10)
    assert not News.objects.filter(url='https://publisher.example/old').exists()
    tick_until(task, lambda: FeedSyncState.objects.get().new_cursor == 30)
    engine.entries.append(replace(dto, id=2, url='https://publisher.example/late'))
    engine.entries[0] = replace(dto, content='<p>Updated retained body.</p>')
    tick_until(task, lambda: News.objects.filter(url='https://publisher.example/late').exists()
        and News.objects.get(url=dto.url).full_content == 'Updated retained body.')
    assert News.objects.get(url='https://publisher.example/old').publish_time.year == 1990
    engine.entries.clear()
    tick_until(task, lambda: FeedSyncState.objects.get().reconciliation_last_complete_at is not None)
    assert News.objects.count() == 3
    task.close()


def test_transient_failure_does_not_advance_and_restarts_resume(setup):
    task, engine = worker(setup, [setup[-1]])
    task.tick()
    task.tick()
    engine.fail = True
    task.tick()
    task.tick()
    state = FeedSyncState.objects.get()
    assert state.new_cursor == 0 and state.last_complete_at is None
    task.close()
    engine.fail = False
    resumed = SyncWorker(Reads(engine), setup[3])
    tick_until(resumed, lambda: FeedSyncState.objects.get().last_complete_at is not None)
    assert News.objects.count() == 1
    resumed.close()


def test_refetch_original_revision_and_atomic_ack(setup):
    from api.rss.operations import refetch_fence
    commit(setup)
    entry = EngineEntryMap.objects.get()
    binding = setup[1]
    op = FeedOperation.objects.create(kind='refetch_entry', binding=binding, entry=entry,
        state='succeeded', request_hash='a' * 64, dedupe_key='synthetic',
        safe_result={'pending_sync': True}, safe_input={'fence': refetch_fence(entry, setup[0].pk, None)})
    token, fence = prepare_refetch(op)
    News.objects.update(full_content_revision=2)
    result = commit_refetch(replace(setup[-1], content='<p>Late body.</p>'), token, fence,
        reserve=lambda: reserve_lease(setup[2]))
    assert result.status == 'stale'
    op.refresh_from_db()
    assert not op.safe_result['pending_sync'] and op.safe_result['sync_status'] == 'stale'
    assert News.objects.get().full_content == 'A readable article.'


@pytest.mark.parametrize('change', ['new_id', 'owner', 'new_url'])
def test_second_page_changes_do_not_advance_cursor(setup, change):
    task, engine = worker(setup, [setup[-1]])
    original = engine.list_entries
    calls = 0
    def changed(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if change == 'owner':
                SourcePublication.objects.update(owner='paused', epoch=2)
            elif change == 'new_id':
                engine.entries = [replace(setup[-1], id=2)]
            else:
                engine.entries = [replace(setup[-1], url='https://publisher.example/new-url')]
        return original(**kwargs)
    engine.list_entries = changed
    tick_until(task, lambda: task.error_class is not None)
    assert not News.objects.exists()
    assert FeedSyncState.objects.get().page_cursor == FeedSyncState.objects.get().new_cursor == 0
    task.close()


def test_duplicate_urls_in_one_page_do_not_loop_forever(setup):
    task, engine = worker(setup, [setup[-1], replace(setup[-1], id=11, title='Same URL duplicate')])
    task.page_size = 100
    tick_until(task, lambda: FeedSyncState.objects.get().new_cursor == 11)
    assert News.objects.count() == 1
    assert FeedRejection.objects.filter(reason='duplicate_url_in_page').exists()
    task.close()


def test_completed_article_before_cursor_loss_is_replayed_once(setup):
    task, engine = worker(setup, [setup[-1]])
    with patch('api.rss.reconciliation.finish_page', side_effect=OperationalError('busy')):
        tick_until(task, lambda: News.objects.exists())
    state = FeedSyncState.objects.get()
    assert state.new_cursor == 0 and state.last_complete_at is None
    tick_until(task, lambda: FeedSyncState.objects.get().last_complete_at is not None)
    assert News.objects.get().full_content_revision == 1
    task.close()


def test_compound_identity_rejects_other_instance_same_integer_ids(setup):
    other = replace(setup[-1], engine_instance_uuid=str(uuid.uuid4()))
    with pytest.raises(StaleWrite):
        capture(setup, other)


def test_healthy_dto_distinguishes_started_and_complete(setup):
    state = begin_run(setup[2], 40)
    result = health_snapshot(setup[1].engine_instance_uuid, 2, {'engine_ready': True})
    assert result['initial_sync'] and result['lag'] == 40
    assert result['new_cursor'] == '0' and result['observed_upper_id'] == '40'
    assert result['incremental_running'] and result['last_successful_incremental'] is None
    assert result['last_successful_full_reconcile'] is None
    assert health_snapshot(setup[1].engine_instance_uuid, 2)['engine_ready'] is False


@pytest.mark.parametrize('state', ['accepted', 'unchanged', 'quarantined', 'rejected'])
def test_refetch_result_acknowledged_with_body_transaction(setup, state):
    from api.rss.operations import refetch_fence
    commit(setup)
    if state == 'quarantined':
        News.objects.update(full_content='x' * 2000)
    entry = EngineEntryMap.objects.get()
    op = FeedOperation.objects.create(kind='refetch_entry', binding=setup[1], entry=entry,
        state='succeeded', request_hash='b' * 64, dedupe_key='refetch-' + state,
        safe_result={'pending_sync': True}, safe_input={'fence': refetch_fence(entry, setup[0].pk, None)})
    token, fence = prepare_refetch(op)
    dto = setup[-1]
    if state == 'accepted':
        dto = replace(dto, content='<p>Changed body.</p>')
    elif state == 'rejected':
        dto = replace(dto, content='')
    result = commit_refetch(dto, token, fence, reserve=lambda: reserve_lease(setup[2]))
    assert result.status == state
    op.refresh_from_db()
    assert op.safe_result['sync_status'] == state and op.safe_result['pending_sync'] is False


def test_refetch_missing_entry_terminal_but_operation_generation_guarded(setup):
    from api.rss.operations import refetch_fence
    from api.rss.sync import reject_missing_refetch
    commit(setup)
    entry = EngineEntryMap.objects.get()
    op = FeedOperation.objects.create(kind='refetch_entry', binding=setup[1], entry=entry,
        state='succeeded', request_hash='c' * 64, dedupe_key='missing-refetch',
        safe_result={'pending_sync': True}, safe_input={'fence': refetch_fence(entry, setup[0].pk, None)})
    token, _ = prepare_refetch(op)
    assert reject_missing_refetch(token, reserve=lambda: reserve_lease(setup[2]))
    op.refresh_from_db()
    assert op.safe_result['code'] == 'engine_entry_missing'


def test_dynamic_channel_region_and_category_membership_preserve_primary(setup):
    from api.models import SourceConfig
    from api.services.channel_articles import category_filter, region_filter
    commit(setup)
    news = News.objects.get()
    extra = Source.objects.create(name='Second channel', url='https://publisher.example/second', region='domestic')
    category = Category.objects.create(name='另一分类', slug='another')
    SourceConfig.objects.create(source_key='second_channel', source=extra, category=category,
        publisher_name='Synthetic', channel_name='Another', status='approved', approved_config_version=1)
    SourcePublication.objects.create(source=extra, owner='miniflux', publication='public', reading_policy='public_feed')
    SourceFeedLink.objects.create(source=extra, binding=setup[1], enabled=True)
    assert category_filter(News.objects.all(), [category.pk]).get().pk == news.pk
    assert region_filter(News.objects.all(), 'domestic').get().pk == news.pk
    news.refresh_from_db()
    assert news.category_id != category.pk and news.source_id == setup[0].pk


def test_static_source_content_kind_is_not_labeled_article(setup):
    Source.objects.filter(name='Hacker News').update(name='Parked seed HN')
    Source.objects.filter(pk=setup[0].pk).update(name='Hacker News')
    commit(setup)
    assert News.objects.get().content_kind == 'discussion'


def test_expired_lease_cannot_authorize_old_response_after_reacquisition(setup):
    task = SyncWorker(Reads(Engine([setup[-1]])), setup[3])
    task.lease = setup[2]
    state = begin_run(task.lease, 10)
    task.run_id, task.upper, task.lower = state.run_id, 10, 0
    task.full = False
    task.fences, task.discovery_ids = {10: capture(setup)}, [10]
    pending = Future()
    task.future, task.phase = pending, 'candidate'
    FeedSyncState.objects.update(lease_until=timezone.now() - timedelta(seconds=1))
    task.tick()
    assert task.lease is None and task.discard_read
    pending.set_result([setup[-1]])
    task.tick()
    assert task.lease.epoch > setup[2].epoch
    assert not News.objects.exists() and FeedSyncState.objects.get().page_cursor == 0
    task.close()


def test_category_and_region_membership_do_not_reveal_other_users_private_source(setup):
    from types import SimpleNamespace
    from django.contrib.auth.models import AnonymousUser, User
    from api.models import ChannelSubscription, SourceConfig
    from api.rss.access import authorized_news
    from api.services.channel_articles import category_filter, region_filter
    from api.views import NewsFilter
    commit(setup)
    news = News.objects.get()
    owner = User.objects.create_user('private-category-owner')
    other = User.objects.create_user('private-category-other')
    category = Category.objects.create(name='Private classification', slug='private-classification')
    source = Source.objects.create(name='Private classification source', url='https://publisher.example/private', region='domestic')
    SourcePublication.objects.create(source=source, publication='personal', owner='miniflux', reading_policy='public_feed')
    SourceConfig.objects.create(source_key='private_classification', source=source, category=category,
        publisher_name='Synthetic', channel_name='Private', status='approved', approved_config_version=1)
    ChannelSubscription.objects.create(user=owner, source=source)
    SourceFeedLink.objects.create(source=source, binding=setup[1], enabled=True)
    # The binding also has the original PUBLIC source. Authorization and category
    # must constrain the SAME joined SourceFeedLink, not two different links.
    for actor, permitted in [(owner, True), (other, False), (AnonymousUser(), False), (None, False)]:
        queryset = authorized_news(actor)
        assert queryset.filter(pk=news.pk).exists()
        assert category_filter(queryset, [category.pk], actor=actor).exists() is permitted
        assert region_filter(queryset, 'domestic', actor=actor).exists() is permitted
        assert category_filter(queryset, [news.category_id], actor=actor).exists()
        if actor is not None:
            filters = NewsFilter({'category': str(category.pk)}, queryset=queryset,
                                 request=SimpleNamespace(user=actor))
            assert filters.is_valid(), filters.errors
            assert filters.qs.exists() is permitted
    ChannelSubscription.objects.filter(user=owner, source=source).delete()
    assert not category_filter(authorized_news(owner), [category.pk], actor=owner).exists()


def test_legacy_category_membership_requires_authorized_source(setup):
    from django.contrib.auth.models import User
    from api.models import ChannelSubscription, NewsSourceItem
    from api.services.channel_articles import category_filter
    from api.services.source_policy import POLICIES
    commit(setup)
    news = News.objects.get()
    policy = next(p for p in POLICIES.values() if p.default_category and p.default_category != news.category.name)
    category, _ = Category.objects.get_or_create(name=policy.default_category, defaults={'slug': 'legacy-extra-category'})
    source, _ = Source.objects.get_or_create(name=policy.name, defaults={'url': 'https://publisher.example/legacy'})
    SourcePublication.objects.update_or_create(source=source, defaults={'publication': 'personal', 'owner': 'legacy'})
    owner = User.objects.create_user('legacy-category-owner')
    other = User.objects.create_user('legacy-category-other')
    ChannelSubscription.objects.create(user=owner, source=source)
    NewsSourceItem.objects.create(source_key=policy.key, upstream_id='private-classification',
        news=news, discovery_url=news.url)
    assert category_filter(News.objects.all(), [category.pk], actor=owner).exists()
    assert not category_filter(News.objects.all(), [category.pk], actor=other).exists()
    assert not category_filter(News.objects.all(), [category.pk]).exists()
