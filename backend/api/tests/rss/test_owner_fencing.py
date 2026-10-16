"""T25 synthetic source switches and actual legacy entry-point writes."""
from dataclasses import replace
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from api.models import Category, FeedBinding, FeedOperation, LegacyTranslationSnapshot, News, NewsSourceItem, Source, SourceFeedLink, SourcePublication
from api.rss.content_store import StaleWrite
from api.rss.engine import EngineError, FeedDTO, PolicyReceipt
from api.rss.legacy_fencing import capture_source_token, capture_legacy_article, legacy_admin_guard, legacy_translation_update
from api.rss.source_migration import MigrationBlocked, apply, plan, verify
from api.services.article_fetcher.types import FullContentCandidate, FetchResult
from api.services.full_content_status import claim_fetch, commit_candidate, enqueue_fetch, mark_success, owns_fetch
from api.services.news_ingestion import ingest_item

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def old():
    source, _ = Source.objects.get_or_create(name='Dev.to', defaults={'url': 'https://dev.to'})
    publication, _ = SourcePublication.objects.update_or_create(source=source, defaults={
        'publication': 'public', 'owner': 'legacy', 'epoch': 1, 'policy_version': 1, 'reading_policy': 'standard'})
    category = Category.objects.create(name='Fencing', slug='fencing')
    news = News.objects.create(source=source, category=category, title='A real short publisher article', content='old summary',
        title_zh='旧标题唯一副本', content_zh='旧摘要唯一副本', full_content='Original body\r\n  exact  \n',
        full_content_zh='旧全文唯一副本', full_content_state='legacy', full_content_hash='untouched-historical-hash',
        full_content_provenance={'old': 'provenance'}, full_content_revision=2,
        body_owner_source=source, publish_time=timezone.now(), url='https://dev.to/team/fencing')
    NewsSourceItem.objects.create(news=news, source_key='devto', upstream_id='17', discovery_url=news.url)
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=1, engine_feed_id=9,
        canonical_feed_url='https://dev.to/feed', desired_mode='feed', desired_enabled=False, connection_state='paused')
    SourceFeedLink.objects.create(source=source, binding=binding)
    return source, news, binding


def item(news, **updates):
    return dict(source_key='devto', source_name='Dev.to', upstream_id='17', title='Changed title',
        category_name='Fencing', url=news.url, summary='changed summary', content_kind='article', **updates)


def candidate(news):
    return FullContentCandidate(source_key='devto', source_item_id='17', target_url=news.url,
        retrieved_from_url='https://dev.to/api/articles/17', declared_canonical_url=None,
        title=news.title, content_kind='article', body_field='body_markdown', content_format='markdown',
        declared_completeness='full', raw_content='A complete short article with an update.',
        source_modified_at=None, source_version=None, request_started_at=timezone.now())


def manifest(old, *, target='miniflux'):
    source, news, binding = old
    publication = SourcePublication.objects.get(source=source)
    configured = str(connection.settings_dict['NAME'])
    path = configured if configured.startswith('file:memorydb_') else str(Path(configured).resolve())
    target_db = {'database': path, 'engine_instance_uuid': str(binding.engine_instance_uuid), 'account_id': binding.account_id, 'engine_base_url': 'http://synthetic-miniflux.test'}
    if not configured.startswith('file:memorydb_'):
        target_db.update(device=Path(path).stat().st_dev, inode=Path(path).stat().st_ino)
    return {'schema_version': 1, 'kind': 'rss_source_migration', 'id': str(uuid.uuid4()), 'environment': 'isolated',
        'app_sha': 'synthetic-fenced-version', 'target': target_db, 'allowlist': {'databases': [path], 'engine_base_urls': ['http://synthetic-miniflux.test']},
        'drain': {'fenced_version': 'synthetic-fenced-version', 'old_processes': []},
        'sources': [{'source_id': source.pk, 'expected_owner': publication.owner, 'expected_epoch': publication.epoch,
            'expected_policy_version': publication.policy_version, 'target_owner': target, 'binding_id': str(binding.pk),
            'legacy_source_keys': ['devto'], 'body_takeover': [{'news_id': news.pk, 'expected_url': news.url,
                'expected_owner_source_id': news.body_owner_source_id,
                'expected_owner_binding_id': str(news.body_owner_binding_id) if news.body_owner_binding_id else None,
                'expected_body_owner_version': news.body_owner_version, 'target_binding_id': str(binding.pk)}]}]}


class FakeEngine:
    def __init__(self, binding, *, fail=False, hook=None):
        self.config = SimpleNamespace(engine_instance_uuid=str(binding.engine_instance_uuid), account_id=binding.account_id, base_url='http://synthetic-miniflux.test')
        self.url = binding.canonical_feed_url
        self.fail = fail
        self.hook = hook
        self.calls = 0

    def update_feed_policy(self, binding, expected_policy_version):
        assert not connection.in_atomic_block, 'engine network must be outside write transaction'
        self.calls += 1
        if self.hook:
            self.hook()
        if self.fail:
            raise EngineError('synthetic_engine_failure')
        return PolicyReceipt(FeedDTO(str(binding.engine_instance_uuid), binding.account_id, binding.engine_feed_id,
            self.url, 'Synthetic feed', binding.desired_mode == 'full_content', not binding.desired_enabled), expected_policy_version)


def execute(old, data=None, engine=None):
    source, _, binding = old
    return apply(data or manifest(old), source_ids=[source.pk], environment='isolated',
                 adapter=engine or FakeEngine(binding), execute=True)


def test_legacy_ingest_requires_pre_network_source_token(old):
    source, news, _ = old
    assert ingest_item(item(news)).reason == 'legacy_token_missing'
    token = capture_source_token('devto')
    result = ingest_item(item(news), legacy_token=token)
    assert result.receipt_outcome == 'committed'
    news.refresh_from_db()
    assert news.title == 'Changed title' and news.content == 'changed summary'
    assert news.title_zh == news.content_zh == '' and news.full_content_zh == '旧全文唯一副本'
    assert set(LegacyTranslationSnapshot.objects.values_list('field', flat=True)) == {'title', 'content'}


def test_new_legacy_article_is_claimed_without_retroactive_existing_article_token(old):
    source, news, _ = old
    token = capture_source_token('devto')
    values = item(news)
    values.update(url='https://dev.to/team/new', upstream_id='18')
    first = ingest_item(values, legacy_token=token)
    created = News.objects.get(pk=first.news_id)
    assert created.body_owner_source_id == source.pk and created.body_owner_binding_id is None
    values['title'] = 'Later page title must not overwrite without original snapshot'
    assert ingest_item(values, legacy_token=token).receipt_outcome == 'committed'
    created.refresh_from_db()
    assert created.title == 'Changed title'


def test_source_switch_rejects_late_feed_metadata_and_body(old):
    source, news, _ = old
    source_token = capture_source_token('devto')
    article_token = source_token.article(news.pk)
    original = News.objects.values().get(pk=news.pk)
    assert execute(old)['verified']
    assert ingest_item(item(news), legacy_token=source_token).receipt_outcome == 'deferred'
    assert commit_candidate(news, candidate(news), legacy_token=article_token).outcome == 'conflict'
    after = News.objects.values().get(pk=news.pk)
    for field in original.keys() - {'body_owner_source_id', 'body_owner_binding_id', 'body_owner_version'}:
        assert after[field] == original[field], field
    assert not LegacyTranslationSnapshot.objects.exists()


def test_full_content_lease_fences_actual_old_worker_result(old):
    source, news, _ = old
    assert enqueue_fetch(news, force=True) == 'queued'
    lease = claim_fetch(news)
    assert lease and lease.legacy_token and owns_fetch(news)
    body = candidate(news)
    assert execute(old)['verified']
    assert not owns_fetch(news)
    result = FetchResult(ok=True, markdown=body.raw_content, provider='devto', candidate=body)
    assert not mark_success(news, result)
    news.refresh_from_db()
    assert news.full_content_zh == '旧全文唯一副本' and news.full_content_revision == 2
    assert claim_fetch(news) is None and enqueue_fetch(news, force=True) == 'rejected'


def test_source_stays_legacy_but_another_binding_body_owner_blocks_old_result(old):
    source, news, binding = old
    token = capture_source_token('devto')
    News.objects.filter(pk=news.pk).update(body_owner_source=None, body_owner_binding=binding, body_owner_version=2)
    assert ingest_item(item(news), legacy_token=token).receipt_outcome == 'deferred'
    assert commit_candidate(news, candidate(news), legacy_token=token.article(news.pk)).outcome == 'conflict'
    news.refresh_from_db()
    assert news.title != 'Changed title'


def test_dry_run_and_plan_are_zero_write_and_no_engine_calls(old, tmp_path):
    source, _, binding = old
    data = manifest(old)
    engine = FakeEngine(binding)
    before = connection.connection.total_changes
    assert plan(data, source_ids=[source.pk], environment='isolated')['phase'] == 'initial'
    result = apply(data, source_ids=[source.pk], environment='isolated', adapter=engine)
    assert result['dry_run'] and engine.calls == 0
    assert connection.connection.total_changes == before
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(data))
    output = StringIO()
    call_command('rss_migration', 'apply', manifest=str(path), source_ids=str(source.pk), environment='isolated', stdout=output)
    assert json.loads(output.getvalue())['dry_run'] and connection.connection.total_changes == before


def test_shared_feed_minimal_group_required_and_switches_together(old):
    source, news, binding = old
    second = Source.objects.create(name='Legacy alias', url='https://alias.example/')
    SourcePublication.objects.create(source=second, owner='legacy', publication='public', reading_policy='standard')
    SourceFeedLink.objects.create(source=second, binding=binding, enabled=True)
    data = manifest(old)
    with pytest.raises(MigrationBlocked, match='shared_feed_group_incomplete'):
        execute(old, data)
    data['sources'].append({'source_id': second.pk, 'expected_owner': 'legacy', 'expected_epoch': 1,
        'expected_policy_version': 1, 'target_owner': 'miniflux', 'binding_id': str(binding.pk), 'body_takeover': []})
    result = apply(data, source_ids=[source.pk, second.pk], environment='isolated', adapter=FakeEngine(binding), execute=True)
    assert result['verified'] and SourcePublication.objects.filter(source_id__in=[source.pk, second.pk], owner='miniflux', epoch=3).count() == 2


def test_engine_failure_leaves_paused_then_same_manifest_resumes_once(old):
    source, news, binding = old
    data = manifest(old)
    engine = FakeEngine(binding, fail=True)
    result = execute(old, data, engine)
    assert result['phase'] == 'paused' and not result['verified']
    assert SourcePublication.objects.get(source=source).epoch == 2
    news.refresh_from_db()
    assert news.body_owner_version == 2
    engine.fail = False
    assert execute(old, data, engine)['verified']
    news.refresh_from_db()
    assert news.body_owner_version == 2 and SourcePublication.objects.get(source=source).epoch == 3
    assert execute(old, data, engine)['verified'] and engine.calls == 2


def test_round_trip_increments_epochs_and_body_versions_without_aba(old):
    source, news, binding = old
    token = capture_source_token('devto')
    assert execute(old)['verified']
    news.refresh_from_db()
    returning = manifest(old, target='legacy')
    assert execute(old, returning)['verified']
    news.refresh_from_db()
    binding.refresh_from_db()
    assert SourcePublication.objects.get(source=source).epoch == 5
    assert news.body_owner_source_id == source.pk and news.body_owner_version == 3
    assert not binding.desired_enabled
    assert ingest_item(item(news), legacy_token=token).receipt_outcome == 'deferred'


@pytest.mark.parametrize('subscribed,pinned,enabled', [(True, False, True), (False, False, False), (False, True, True)])
def test_shared_active_reference_preserves_physical_feed_when_returning_legacy(old, subscribed, pinned, enabled):
    source, news, binding = old
    assert execute(old)['verified']
    other = Source.objects.create(name='rss:other', url='https://other.example/')
    SourcePublication.objects.create(source=other, owner='miniflux')
    SourceFeedLink.objects.create(source=other, binding=binding, enabled=True, editorial_pin=pinned)
    if subscribed:
        from django.contrib.auth import get_user_model
        from api.models import ChannelSubscription
        user = get_user_model().objects.create_user(username='shared-feed-subscriber')
        ChannelSubscription.objects.create(user=user, source=other)
    news.refresh_from_db()
    assert execute(old, manifest(old, target='legacy'))['verified']
    binding.refresh_from_db()
    assert binding.desired_enabled == enabled
    assert binding.connection_state == ('ready' if enabled else 'paused')


def test_live_old_process_blocks_after_pause_without_body_takeover(old):
    source, news, _ = old
    data = manifest(old)
    ticks = Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')', 1)[1].split()[19]
    data['drain']['old_processes'] = [{'pid': os.getpid(), 'start_ticks': ticks, 'role': 'legacy'}]
    result = execute(old, data)
    assert result['reason'] == 'old_unfenced_process_still_running'
    assert SourcePublication.objects.get(source=source).owner == 'paused'
    news.refresh_from_db()
    assert news.body_owner_source_id == source.pk and news.body_owner_version == 1


def test_policy_change_during_engine_io_cannot_activate(old):
    source, _, binding = old
    engine = FakeEngine(binding, hook=lambda: SourcePublication.objects.filter(source=source).update(policy_version=2))
    result = execute(old, engine=engine)
    assert result['phase'] == 'paused' and result['reason'] == 'source_policy_changed'
    assert SourcePublication.objects.get(source=source).owner == 'paused'


def test_target_allowlist_and_production_gate_precede_writes(old):
    source, _, binding = old
    data = manifest(old)
    data['allowlist']['databases'] = []
    before = connection.connection.total_changes
    with pytest.raises(MigrationBlocked, match='database_not_allowlisted'):
        execute(old, data)
    data = manifest(old)
    data['environment'] = 'production'
    with pytest.raises(MigrationBlocked, match='approved_window_missing'):
        apply(data, source_ids=[source.pk], environment='production', adapter=FakeEngine(binding), execute=True)
    assert connection.connection.total_changes == before


def test_unrecognized_filter_never_becomes_all_entries(old):
    data = manifest(old)
    data['sources'][0]['association_policy'] = {'version': 1, 'mode': 'custom'}
    with pytest.raises(MigrationBlocked, match='association_filter_requires_supported_validator'):
        execute(old, data)


def test_feed_checkpoint_and_old_translation_cannot_publish_late(old):
    from api.services.feed_state import prepare_feed_request, commit_feed_checkpoint
    source, news, _ = old
    context = prepare_feed_request('webkit', 'https://webkit.org/feed/')
    SourcePublication.objects.filter(source_id=context.legacy_token.source_id).update(owner='paused', epoch=2)
    assert not commit_feed_checkpoint(context, etag='must-not-commit')
    News.objects.filter(pk=news.pk).update(title='New version of title', content='New version of summary')
    assert not legacy_translation_update(news, {'title_zh': 'Late translated old title', 'content_zh': 'Late old summary'},
                                         title=news.title, content=news.content)
    news.refresh_from_db()
    assert news.title_zh == '旧标题唯一副本'
    assert set(LegacyTranslationSnapshot.objects.values_list('translated_text', flat=True)) == {'Late translated old title', 'Late old summary'}


def test_plan_rejects_wrong_body_owner_before_any_pause(old):
    data = manifest(old)
    data['sources'][0]['body_takeover'][0]['expected_body_owner_version'] += 9
    before = connection.connection.total_changes
    with pytest.raises(MigrationBlocked, match='body_owner_version_changed'):
        plan(data, source_ids=[old[0].pk], environment='isolated')
    assert connection.connection.total_changes == before
    assert SourcePublication.objects.get(source=old[0]).owner == 'legacy'


def test_summary_policy_cannot_enable_html_crawler(old):
    SourcePublication.objects.filter(source=old[0]).update(reading_policy='public_feed')
    FeedBinding.objects.filter(pk=old[2].pk).update(desired_mode='full_content')
    with pytest.raises(MigrationBlocked, match='full_content_policy_not_permitted'):
        plan(manifest(old), source_ids=[old[0].pk], environment='isolated')


def test_unknown_static_filter_is_not_silently_removed(old, monkeypatch):
    from api.services.source_policy import POLICIES
    monkeypatch.setitem(POLICIES, 'devto', replace(POLICIES['devto'], keyword_filter='AI'))
    with pytest.raises(MigrationBlocked, match='association_filter_requires_supported_validator'):
        plan(manifest(old), source_ids=[old[0].pk], environment='isolated')


def test_legacy_source_policy_changed_after_fetch_blocks_body_lease(old, monkeypatch):
    from api.services.source_policy import POLICIES
    _, news, _ = old
    assert enqueue_fetch(news, force=True) == 'queued'
    lease = claim_fetch(news)
    assert lease
    monkeypatch.setitem(POLICIES, 'devto', replace(POLICIES['devto'], contract_version='later'))
    assert not owns_fetch(news)
    assert commit_candidate(news, candidate(news), lease=lease).reason == 'legacy_policy_changed'
    news.refresh_from_db()
    assert news.full_content_hash == 'untouched-historical-hash'


def test_repair_plan_cannot_write_after_body_handover(old):
    from api.rss.legacy_fencing import assert_legacy_admin_guard
    source, news, _ = old
    guard = legacy_admin_guard(source.pk, [news.pk])
    assert execute(old)['verified']
    with pytest.raises(StaleWrite):
        assert_legacy_admin_guard(guard)


def test_metadata_archive_failure_rolls_back_every_write(old, monkeypatch):
    import api.services.news_ingestion as ingestion
    _, news, _ = old
    token = capture_source_token('devto')
    before = News.objects.values().get(pk=news.pk)
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic_archive_failure')
    monkeypatch.setattr(ingestion, 'archive_changed_translations', fail)
    with pytest.raises(RuntimeError, match='synthetic_archive_failure'):
        ingest_item(item(news), legacy_token=token)
    assert News.objects.values().get(pk=news.pk) == before
    assert not LegacyTranslationSnapshot.objects.exists()


def test_downloader_captures_before_http_and_rechecks_each_request(old, monkeypatch):
    import asyncio
    from scrapy.http import Request, Response
    from news_crawler import download_handlers as handler
    from api.services.article_fetcher import safe_http
    from api.rss.legacy_fencing import LegacySourceToken
    source, news, _ = old
    calls = []
    class Stats:
        def inc_value(self, *args): pass
        def set_value(self, *args): pass
    spider = SimpleNamespace(name='devto')
    class Inner:
        async def download_request(self, request):
            assert isinstance(spider._legacy_source_token, LegacySourceToken)
            assert spider._legacy_source_token.article(news.pk).news_url == news.url
            calls.append(request.url)
            return Response(request.url, status=200)
    monkeypatch.setattr(safe_http, 'validate_public_url', lambda *args: None)
    monkeypatch.setattr(handler, 'claim_budget', lambda *args: object())
    monkeypatch.setattr(handler, 'confirm_permit', lambda *args: None)
    monkeypatch.setattr(handler, 'release_budget', lambda *args: None)
    monkeypatch.setattr(handler, 'record_response', lambda *args, **kwargs: None)
    value = handler.BudgetedHTTPDownloadHandler.__new__(handler.BudgetedHTTPDownloadHandler)
    value.crawler = SimpleNamespace(spider=spider, stats=Stats())
    value.inner = Inner()
    async def scenario():
        await value.download_request(Request('https://dev.to/api/articles'))
        await handler._db(lambda: SourcePublication.objects.filter(source=source).update(owner='paused', epoch=2))
        with pytest.raises(StaleWrite):
            await value.download_request(Request('https://dev.to/api/articles?page=2'))
    asyncio.run(scenario())
    assert len(calls) == 1
    assert ingest_item(item(news), legacy_token=spider._legacy_source_token).receipt_outcome == 'deferred'


def test_file_sqlite_migration_dry_run_apply_resume_and_roundtrip(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[4]
    code = r'''
import django, json, socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('synthetic migration cannot use network'))
django.setup()
from django.core.management import call_command
from django.db import connection
from api.tests.rss.test_owner_fencing import old, manifest, FakeEngine
from api.rss.source_migration import apply, verify
from api.models import SourcePublication
call_command('migrate', verbosity=0)
rows = old.__wrapped__()
source, news, binding = rows
before = news.__class__.objects.values().get(pk=news.pk)
data = manifest(rows)
engine = FakeEngine(binding)
changes = connection.connection.total_changes
assert apply(data, source_ids=[source.pk], environment='isolated', adapter=engine)['dry_run']
assert connection.connection.total_changes == changes and engine.calls == 0
assert apply(data, source_ids=[source.pk], environment='isolated', adapter=engine, execute=True)['verified']
assert apply(data, source_ids=[source.pk], environment='isolated', adapter=engine, execute=True)['verified']
assert engine.calls == 1
news.refresh_from_db()
back = manifest(rows, target='legacy')
assert apply(back, source_ids=[source.pk], environment='isolated', adapter=engine, execute=True)['verified']
assert SourcePublication.objects.get(source=source).epoch == 5
news.refresh_from_db()
after = news.__class__.objects.values().get(pk=news.pk)
assert all(after[k] == v for k, v in before.items() if not k.startswith('body_owner_'))
assert news.body_owner_version == 3
print(json.dumps({'file_sqlite':True, 'zero_write_plan':True, 'roundtrip':True, 'retained_text':True}))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root, env={**os.environ,
        'RUN_MAIN': 'true', 'DJANGO_ENV': 'development', 'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_DB_PATH': str(tmp_path / 'switch.sqlite3'), 'PYTHONPATH': str(root / 'backend')},
        capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"roundtrip": true' in result.stdout


def test_config_version_change_fences_full_content_and_source_result(old):
    from api.models import SourceConfig
    source, news, _ = old
    config = SourceConfig.objects.create(source_key='devto', source=source, category=news.category,
        publisher_name='Dev.to', channel_name='Dev.to', reading_policy='official_html', status='enabled',
        approved_config_version=1, approved_at=timezone.now())
    source_token = capture_source_token('devto')
    assert enqueue_fetch(news, force=True) == 'queued'
    lease = claim_fetch(news)
    assert lease and owns_fetch(news)
    SourceConfig.objects.filter(pk=config.pk).update(config_version=2, status='blocked')
    assert not owns_fetch(news)
    assert ingest_item(item(news), legacy_token=source_token).reason == 'legacy_policy_changed'
    assert commit_candidate(news, candidate(news), lease=lease).reason == 'legacy_policy_changed'


def test_cutover_and_return_preserve_user_relations(old):
    from django.contrib.auth import get_user_model
    from api.models import Favorite, ChatSession
    _, news, _ = old
    user = get_user_model().objects.create_user(username='migration-reader')
    favorite = Favorite.objects.create(user=user, news=news, type='bookmark')
    chat = ChatSession.objects.create(user=user, news=news, messages=[{'role': 'user', 'content': 'retained conversation'}])
    before = News.objects.values().get(pk=news.pk)
    assert execute(old)['verified']
    news.refresh_from_db()
    assert execute(old, manifest(old, target='legacy'))['verified']
    favorite.refresh_from_db()
    chat.refresh_from_db()
    assert favorite.news_id == chat.news_id == news.pk
    assert chat.messages == [{'role': 'user', 'content': 'retained conversation'}]
    after = News.objects.values().get(pk=news.pk)
    assert all(after[key] == value for key, value in before.items() if not key.startswith('body_owner_'))


def test_unclaimed_migrated_legacy_news_can_enqueue_but_cannot_write_without_token(old):
    from api.services.full_content_status import fetch_eligibility
    source, news, _ = old
    News.objects.filter(pk=news.pk).update(body_owner_source=None)
    news.refresh_from_db()
    assert fetch_eligibility(news) == ''
    assert commit_candidate(news, candidate(news)).reason == 'legacy_token_missing'
    assert enqueue_fetch(news, force=True) == 'queued'
    news.refresh_from_db()
    assert news.body_owner_source_id == source.pk


@pytest.mark.parametrize('reading_policy', ['summary_only', 'rss_summary_only'])
def test_legacy_body_commit_preserves_restrictive_publication_policy(old, reading_policy):
    source, news, _ = old
    SourcePublication.objects.filter(source=source).update(reading_policy=reading_policy)
    token = capture_legacy_article(news)
    assert commit_candidate(news, candidate(news), legacy_token=token).reason == 'unsupported'
    assert enqueue_fetch(news, force=True) == 'rejected'
    news.refresh_from_db()
    assert news.full_content_hash == 'untouched-historical-hash'


def test_cutover_reconciles_removed_binding_without_stopping_other_references(old):
    source, news, binding = old
    orphan = FeedBinding.objects.create(engine_instance_uuid=binding.engine_instance_uuid, account_id=1,
        engine_feed_id=10, canonical_feed_url='https://dev.to/old-feed', desired_enabled=True,
        connection_state='ready', policy_version=1, applied_policy_version=1)
    SourceFeedLink.objects.create(source=source, binding=orphan, enabled=True)
    class MultiEngine(FakeEngine):
        def update_feed_policy(self, policy, expected_policy_version):
            self.url = FeedBinding.objects.get(engine_feed_id=policy.engine_feed_id).canonical_feed_url
            return super().update_feed_policy(policy, expected_policy_version)
    engine = MultiEngine(binding)
    assert execute(old, engine=engine)['verified']
    orphan.refresh_from_db()
    assert not orphan.desired_enabled and orphan.connection_state == 'paused'
    assert engine.calls == 2


@pytest.mark.parametrize('owner', ['legacy', 'paused'])
def test_non_miniflux_editorial_pin_does_not_keep_feed_active_on_return(old, owner):
    assert execute(old)['verified']
    source, news, binding = old
    news.refresh_from_db()
    other = Source.objects.create(name='Inactive editor pin ' + owner)
    SourcePublication.objects.create(source=other, owner=owner)
    SourceFeedLink.objects.create(source=other, binding=binding, editorial_pin=True)
    data = manifest(old, target='legacy')
    data['sources'].append({'source_id': other.pk, 'expected_owner': owner, 'expected_epoch': 1,
        'expected_policy_version': 1, 'target_owner': 'paused', 'binding_ids': [], 'body_takeover': []})
    assert apply(data, source_ids=[source.pk, other.pk], environment='isolated',
        adapter=FakeEngine(binding), execute=True)['verified']
    binding.refresh_from_db()
    assert not binding.desired_enabled


def test_completed_translation_records_exact_bound_hash_and_retains_previous_copy(old):
    from api.rss.legacy_translation import exact_hash
    _, news, _ = old
    assert legacy_translation_update(news, {'title_zh': 'New translation'}, title=news.title, content=news.content)
    row = LegacyTranslationSnapshot.objects.get(news=news, field='title', origin='legacy-bound')
    assert row.source_hash == exact_hash(news.title) and row.source_text == news.title
    assert row.translated_text == 'New translation'
    assert LegacyTranslationSnapshot.objects.filter(news=news, field='title', origin='legacy', translated_text='旧标题唯一副本').exists()
    news.refresh_from_db()
    assert news.title_zh == 'New translation'


def test_approved_official_html_policy_can_keep_html_mode(old):
    SourcePublication.objects.filter(source=old[0]).update(reading_policy='official_html')
    FeedBinding.objects.filter(pk=old[2].pk).update(desired_mode='full_content')
    assert execute(old)['verified']
