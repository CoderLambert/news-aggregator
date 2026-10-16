"""C02 schema evidence on synthetic SQLite databases, never a user database."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from importlib import import_module
import sqlite3
from threading import Barrier
import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from api.models import (
    BodyCandidate, Category, EngineEntryMap, FeedBinding, FeedOperation,
    FeedRejection, FeedSyncState, IdentityConflict, LegacyTranslationSnapshot,
    News, Source, SourceFeedLink, SourcePublication,
)


pytestmark = pytest.mark.django_db


def binding(**overrides):
    values = dict(engine_instance_uuid=uuid.uuid4(), account_id=1,
                  canonical_feed_url='https://example.test/Feed?q=one', engine_feed_id=11)
    return FeedBinding.objects.create(**(values | overrides))


def article(**overrides):
    source = Source.objects.create(name=f'old-source-{uuid.uuid4()}', url='https://example.test/')
    category, _ = Category.objects.get_or_create(name='Test', defaults={'slug': 'test'})
    return News.objects.create(**(dict(title='Old title', content='Old summary',
        source=source, category=category, url=f'https://example.test/{uuid.uuid4()}',
        publish_time=timezone.now(), full_content='old body\r\n  code  \n') | overrides))


def assert_duplicate(factory):
    with pytest.raises(IntegrityError), transaction.atomic():
        factory()


def test_composite_identity_scopes_feed_and_entry_and_nullable_registration():
    first = binding()
    identity = dict(engine_instance_uuid=first.engine_instance_uuid, account_id=first.account_id)
    assert_duplicate(lambda: binding(**identity, engine_feed_id=12))
    assert_duplicate(lambda: binding(**identity, canonical_feed_url='https://example.test/other'))
    # Numeric IDs deliberately collide across rebuilt instances and accounts.
    second = binding()
    third = binding(**(identity | {'account_id': 2}))
    fourth = binding(**identity, engine_feed_id=12, canonical_feed_url='https://example.test/other')
    for current in [first, second, third, fourth]:
        EngineEntryMap.objects.create(binding=current, engine_entry_id=91, source_url='https://example.test/article')
    assert_duplicate(lambda: EngineEntryMap.objects.create(binding=first, engine_entry_id=91, source_url='https://example.test/article'))
    assert EngineEntryMap.objects.count() == 4
    binding(**identity, engine_feed_id=None, canonical_feed_url='https://example.test/new1')
    binding(**identity, engine_feed_id=None, canonical_feed_url='https://example.test/new2')
    assert_duplicate(lambda: binding(**identity, engine_feed_id=None, canonical_feed_url='https://example.test/new1'))


def test_source_publication_pause_and_policy_are_independent():
    news = article()
    publication = SourcePublication.objects.create(source=news.source)
    assert (publication.publication, publication.owner, publication.reading_policy) == ('personal', 'paused', 'summary_only')
    publication.publication = 'public'
    publication.owner = 'legacy'
    publication.save()
    SourcePublication.objects.filter(pk=news.source_id).update(owner='paused', pause_reason='unsupported')
    publication.refresh_from_db()
    assert publication.publication == 'public'
    assert publication.epoch == publication.policy_version == 1
    SourcePublication.objects.filter(pk=news.source_id).update(publication='personal')
    publication.refresh_from_db()
    assert publication.owner == 'paused' and publication.publication == 'personal'
    assert_duplicate(lambda: SourcePublication.objects.filter(pk=publication.pk).update(publication='history_only'))
    link = SourceFeedLink.objects.create(source=news.source, binding=binding())
    assert link.association_policy == {'version': 1, 'mode': 'all'}
    assert_duplicate(lambda: SourceFeedLink.objects.create(source=news.source, binding=link.binding))
    assert_duplicate(lambda: Source.objects.create(name=news.source.name, url='https://different.test/'))
    assert_duplicate(lambda: article(url=news.url))


def test_body_has_one_writer_and_independent_versions_and_exact_snapshot_identity():
    news = article()
    feed = binding()
    News.objects.filter(pk=news.pk).update(body_owner_source=news.source, body_owner_version=4)
    assert_duplicate(lambda: News.objects.filter(pk=news.pk).update(body_owner_binding=feed))
    News.objects.filter(pk=news.pk).update(body_owner_source=None, body_owner_binding=feed, body_owner_version=5)
    news.refresh_from_db()
    assert news.full_content_revision == 0 and news.body_owner_version == 5
    assert_duplicate(lambda: News.objects.filter(pk=news.pk).update(body_owner_version=0))
    entry = EngineEntryMap.objects.create(binding=feed, engine_entry_id=1, source_url=news.url, news=news)
    candidate_values = dict(entry=entry, news=news, source=news.source, source_epoch=2,
        body_owner_version=5, source_policy_version=3, binding_policy_version=1,
        news_url=news.url, expected_revision=0, markdown='candidate', raw_hash='a' * 64,
        canonical_hash='b' * 64, conversion_version='test-v1')
    BodyCandidate.objects.create(**candidate_values)
    assert_duplicate(lambda: BodyCandidate.objects.create(**candidate_values))
    BodyCandidate.objects.create(**(candidate_values | {'binding_policy_version': 2}))
    source_hash = sha256(news.full_content.encode()).hexdigest()
    values = dict(news=news, field='full_content', source_hash=source_hash,
        translation_hash=sha256('唯一旧译文'.encode()).hexdigest(),
        source_text=news.full_content, translated_text='唯一旧译文')
    saved = LegacyTranslationSnapshot.objects.create(**values)
    assert saved.origin == 'legacy'
    assert saved.source_text == 'old body\r\n  code  \n'
    assert_duplicate(lambda: LegacyTranslationSnapshot.objects.create(**values))
    LegacyTranslationSnapshot.objects.create(**(values | {'field': 'content'}))
    LegacyTranslationSnapshot.objects.create(**(values | {'translation_hash': 'c' * 64, 'translated_text': '其他版本'}))


def test_operation_dedupe_is_actor_scoped_and_sync_cursors_are_independent(django_user_model):
    first = django_user_model.objects.create_user(username='first')
    second = django_user_model.objects.create_user(username='second')
    feed = binding()
    values = dict(kind='refresh_feed', binding=feed, dedupe_key='same-client-key', request_hash='a' * 64)
    operation = FeedOperation.objects.create(actor=first, **values)
    assert_duplicate(lambda: FeedOperation.objects.create(actor=first, **values))
    FeedOperation.objects.create(actor=second, **values)
    FeedOperation.objects.create(actor=None, **values)
    assert_duplicate(lambda: FeedOperation.objects.create(actor=None, **values))
    assert FeedOperation.objects.filter(actor=first).count() == 1
    assert_duplicate(lambda: FeedOperation.objects.filter(pk=operation.pk).update(kind='arbitrary_http'))
    state = FeedSyncState.objects.create(engine_instance_uuid=feed.engine_instance_uuid, account_id=1,
        new_cursor=10, upper_id=15, page_cursor=12, reconciliation_upper_id=9,
        reconciliation_page_cursor=3, lease_epoch=7)
    assert_duplicate(lambda: FeedSyncState.objects.create(engine_instance_uuid=feed.engine_instance_uuid, account_id=1))
    FeedSyncState.objects.filter(pk=state.pk).update(reconciliation_page_cursor=8)
    state.refresh_from_db()
    assert (state.new_cursor, state.page_cursor, state.upper_id, state.lease_epoch) == (10, 12, 15, 7)
    assert feed.policy_version == 1 and feed.applied_policy_version == 0
    assert_duplicate(lambda: FeedBinding.objects.filter(pk=feed.pk).update(applied_policy_version=2))


@pytest.mark.parametrize('model', [FeedRejection, IdentityConflict])
def test_issues_keep_full_identity_and_dedupe_replay(model):
    identity = dict(engine_instance_uuid=uuid.uuid4(), account_id=1, engine_feed_id=2,
                    engine_entry_id=3, reason='identity_changed', content_hash='a' * 64)
    model.objects.create(**identity)
    assert_duplicate(lambda: model.objects.create(**identity))
    model.objects.create(**(identity | {'engine_instance_uuid': uuid.uuid4()}))
    model.objects.create(**(identity | {'account_id': 2}))
    model.objects.create(**(identity | {'content_hash': 'b' * 64}))
    assert model.objects.count() == 4


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('kind', ['binding', 'entry', 'snapshot'])
def test_two_sqlite_connections_converge_on_one_identity(tmp_path, kind):
    """Real competing connections and DB constraints, no select_for_update mocks."""
    news = article()
    feed = binding()
    if kind == 'binding':
        row = feed
    elif kind == 'entry':
        row = EngineEntryMap.objects.create(binding=feed, engine_entry_id=9, source_url=news.url)
    else:
        row = LegacyTranslationSnapshot.objects.create(news=news, field='full_content',
            source_hash='a' * 64, translation_hash='b' * 64, source_text='old', translated_text='旧')
    table = row._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM "{table}" WHERE id = %s', [row.pk.hex])
        values = list(cursor.fetchone())
        columns = [column[0] for column in cursor.description]
        cursor.execute(f'DELETE FROM "{table}" WHERE id = %s', [row.pk.hex])
    database = tmp_path / 'competing-writers.sqlite3'
    with sqlite3.connect(database) as target:
        connection.connection.backup(target)
    barrier = Barrier(2)

    def insert():
        candidate = list(values)
        candidate[columns.index('id')] = uuid.uuid4().hex
        with sqlite3.connect(database, timeout=5) as db:
            db.execute('PRAGMA foreign_keys=ON')
            barrier.wait(timeout=5)
            try:
                db.execute(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in candidate)})', candidate)
                db.commit()
                return 'created'
            except sqlite3.IntegrityError:
                return 'duplicate'

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(insert) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == ['created', 'duplicate']
    with sqlite3.connect(database) as db:
        assert db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 1
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def snapshot_old_columns():
    result = {}
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names():
            if table == 'django_migrations':
                continue
            columns = [column.name for column in connection.introspection.get_table_description(cursor, table)]
            quoted = ','.join(connection.ops.quote_name(column) for column in columns)
            cursor.execute(f'SELECT {quoted} FROM {connection.ops.quote_name(table)}')
            result[table] = (columns, sorted(cursor.fetchall(), key=repr))
    return result


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('baseline', ['0051_seed_domestic_medical_sources', '0052_feed_directory'])
def test_upgrade_preserves_all_old_columns_relationships_and_text(baseline):
    old_target = [('api', baseline)]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    executor.migrate(old_target)
    try:
        apps = executor.loader.project_state(old_target).apps
        get = lambda name: apps.get_model('api', name)
        if baseline == '0052_feed_directory':
            directory = get('FeedDirectorySnapshot').objects.create(checksum='d' * 64,
                commit='frozen-commit', license='MIT', schema_version=1, active=True)
            get('FeedDirectoryEntry').objects.create(snapshot=directory, entry_id=uuid.uuid4(),
                name='Existing directory', kind='feed', public_url='https://directory.test/feed')
        user = apps.get_model('auth', 'User').objects.create(username='historical-user', password='hashed-existing')
        source = get('Source').objects.create(name='Historical Unicode 来源', url='https://history.test/')
        restricted = get('Source').objects.create(name='STAT News', url='https://stat.test/')
        category = get('Category').objects.create(name='Historic category', slug='historic-category')
        get('SourceConfig').objects.create(source_key='old_summary', source=source, category=category,
            publisher_name='Historical', channel_name=source.name, reading_policy='summary_only')
        dynamic_source = get('Source').objects.create(name='Dynamic full feed', url='https://dynamic.test/')
        get('SourceConfig').objects.create(source_key='old_public', source=dynamic_source, category=category,
            publisher_name='Dynamic', channel_name=dynamic_source.name, reading_policy='public_feed')
        body = '  # Old\r\n\r\n```python\n  x = "中文"  \n```\n\n'
        news = get('News').objects.create(source=source, category=category, title='Old title', content='Old summary',
            url='https://history.test/item', publish_time=timezone.now(), title_zh='旧标题', content_zh='旧摘要',
            full_content=body, full_content_zh='唯一兼容全文译文', full_content_state='complete',
            full_content_revision=17, full_content_provenance={'canonical_hash': 'historical-hash', 'provider': 'old'},
            title_hash=123456)
        get('News').objects.create(source=source, category=category, title='Only compatible translation', content='',
            url='https://history.test/only-compat', publish_time=timezone.now(),
            full_content='Only original\r\n', full_content_zh='只有兼容字段译文', full_content_state='legacy')
        get('News').objects.create(source=source, category=category, title='Missing body', content='summary',
            url='https://history.test/missing', publish_time=timezone.now(), full_content_state='missing')
        get('NewsSourceItem').objects.create(news=news, source_key='original-publisher', upstream_id='original-77', discovery_url=news.url)
        subscription = get('ChannelSubscription').objects.create(user=user, source=source)
        group = get('ChannelGroup').objects.create(user=user, name='Historical group')
        get('ChannelGroupMember').objects.create(group=group, subscription=subscription)
        get('Favorite').objects.create(user=user, news=news, type='bookmark')
        get('BlockedNews').objects.create(user=user, news=news)
        get('ChatSession').objects.create(user=user, news=news, messages=[{'role': 'user', 'content': 'history'}])
        get('ReadingDay').objects.create(user=user, news=news, day=timezone.now().date())
        research = get('ResearchSession').objects.create(user=user, title='old research', messages=[{'content': 'saved'}])
        get('ResearchSearchResult').objects.create(session=research, tool_name='search', result_type='news', url=news.url)
        conn = get('ChatGPTSubscriptionConnection').objects.create(user=user, subject_hash='subject', issuer='issuer',
            issued_client_id='client', registration_key_hash='registration', encrypted_access_token='synthetic-ciphertext')
        other = get('News').objects.create(source=source, category=category, title='Translated article', content='summary',
            url='https://history.test/translated', publish_time=timezone.now(), full_content='Private/shared source')
        get('ChatGPTArticleTranslation').objects.create(user=user, connection=conn, news=other,
            source_hash='old-private-hash', model_slug='old-model', content='私人译文', completed_at=timezone.now())
        get('SharedArticleTranslation').objects.create(news=other, source_hash='old-shared-hash', translation_version='v1',
            content='共享译文', provider='known-provider', completed_at=timezone.now())
        get('ChatGPTTranslationTask').objects.create(user=user, connection=conn, news=news,
            source_hash='old-task-hash', model_slug='old-model', connection_generation=3)
        get('SharedArticleTranslationTask').objects.create(news=news, source_hash='old-shared-task-hash',
            translation_version='v1', initiated_by=user)
        before = snapshot_old_columns()
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        with connection.cursor() as cursor:
            for table, (columns, rows) in before.items():
                quoted = ','.join(connection.ops.quote_name(column) for column in columns)
                cursor.execute(f'SELECT {quoted} FROM {connection.ops.quote_name(table)}')
                assert sorted(cursor.fetchall(), key=repr) == rows, table
            cursor.execute('PRAGMA foreign_key_check')
            assert cursor.fetchall() == []
        migrated = News.objects.get(pk=news.pk)
        assert migrated.full_content == body
        assert migrated.full_content_hash == sha256(body.encode('utf-8')).hexdigest()
        assert migrated.body_owner_source_id == source.pk and migrated.body_owner_binding_id is None
        assert migrated.body_owner_version == 1 and migrated.full_content_revision == 17
        assert migrated.full_content_completeness == 'unknown'
        assert not LegacyTranslationSnapshot.objects.exists()  # T07 archives before replacement.
        publication = SourcePublication.objects.get(source_id=source.pk)
        assert (publication.publication, publication.owner, publication.display_name) == ('public', 'legacy', source.name)
        assert SourcePublication.objects.get(source_id=restricted.pk).reading_policy == 'rss_summary_only'
        dynamic = get('SourceConfig').objects.filter(source_id__isnull=False).first()
        assert SourcePublication.objects.get(source_id=dynamic.source_id).reading_policy == dynamic.reading_policy
        assert SourcePublication.objects.get(source_id=dynamic_source.pk).reading_policy == 'public_feed'
        # Interrupted backfill can replay without resetting a later explicit owner/policy.
        feed = binding()
        News.objects.filter(pk=news.pk).update(body_owner_source=None, body_owner_binding=feed, body_owner_version=2)
        SourcePublication.objects.filter(pk=source.pk).update(owner='paused', epoch=2, publication='personal')
        migration = import_module('api.migrations.0054_rss_legacy_compatibility')
        with connection.schema_editor() as editor:
            migration.initialize_legacy(executor.loader.project_state(latest).apps, editor)
        migrated.refresh_from_db()
        publication.refresh_from_db()
        assert migrated.body_owner_binding_id == feed.pk and migrated.body_owner_version == 2
        assert publication.owner == 'paused' and publication.epoch == 2 and publication.publication == 'personal'
    finally:
        MigrationExecutor(connection).migrate(latest)
