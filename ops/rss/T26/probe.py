"""Synthetic-only staged ORM rehearsal; runs inside a full application image.

The runner creates the only writable mount. No stage reverses migrations or
restores a database. Legacy rows are seeded using historical 0051 ORM models.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

STATE = Path('/evidence')
DB = STATE / 'synthetic.sqlite3'
assert os.environ.get('DJANGO_DB_PATH') == str(DB), 'explicit synthetic target required'
assert (STATE / 'SYNTHETIC_ONLY').read_text().strip() == 'T26 synthetic, never production'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def save(name, data):
    (STATE / (name + '.json')).write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + '\n')
    print(json.dumps({'stage': name, 'status': 'PASS', 'digest': digest(data)}), flush=True)


def load(name):
    return json.loads((STATE / (name + '.json')).read_text())


def tables(spec=None):
    result = {}
    with connection.cursor() as cursor:
        for table in sorted(spec or connection.introspection.table_names()):
            if table == 'django_migrations':
                continue
            columns = spec[table]['columns'] if spec else [c.name for c in connection.introspection.get_table_description(cursor, table)]
            quote = connection.ops.quote_name
            cursor.execute('SELECT ' + ','.join(map(quote, columns)) + ' FROM ' + quote(table))
            rows = sorted(cursor.fetchall(), key=repr)
            result[table] = {'columns': columns, 'rows': len(rows), 'sha256': digest(rows)}
        cursor.execute('PRAGMA foreign_key_check')
        assert cursor.fetchall() == []
        cursor.execute('PRAGMA integrity_check')
        assert cursor.fetchall() == [('ok',)]
    return result


def seed():
    assert not DB.exists(), 'refuse to seed an existing database'
    target = [('api', '0051_seed_domestic_medical_sources')]
    executor = MigrationExecutor(connection)
    executor.migrate(target)
    apps = executor.loader.project_state(target).apps
    get = lambda name: apps.get_model('api', name)
    User = apps.get_model('auth', 'User')
    a = User.objects.create(username='synthetic-a', password='!disabled')
    User.objects.create(username='synthetic-b', password='!disabled')
    source, _ = get('Source').objects.get_or_create(name='Dev.to', defaults={'url': 'https://dev.to'})
    category = get('Category').objects.create(name='T26 synthetic', slug='t26-synthetic')
    body = '  # Exact legacy body\r\n\n```python\n  x = "中文"  \n```\n'
    news = get('News').objects.create(source=source, category=category, title='Old title', content='Old summary',
        title_zh='唯一旧标题', content_zh='唯一旧摘要', full_content=body, full_content_zh='唯一兼容全文译文',
        full_content_state='complete', full_content_revision=17, full_content_provenance={'provider':'historical'},
        url='https://dev.to/team/t26', publish_time=timezone.now(), title_hash=23456)
    for state in ('missing', 'legacy'):
        get('News').objects.create(source=source, category=category, title=state, content=state+' summary',
            full_content='' if state == 'missing' else 'legacy bytes\r\n', full_content_state=state,
            url='https://dev.to/team/t26-'+state, publish_time=timezone.now())
    get('NewsSourceItem').objects.create(news=news, source_key='devto', upstream_id='26', discovery_url=news.url)
    sub = get('ChannelSubscription').objects.create(user=a, source=source)
    group = get('ChannelGroup').objects.create(user=a, name='Synthetic group')
    get('ChannelGroupMember').objects.create(group=group, subscription=sub)
    get('NewsPreference').objects.create(user=a,scope='group',group=group)
    get('SourceTopicProfile').objects.create(source=source,about='synthetic retained profile',topics=['software'])
    get('ChannelGroupingConfig').objects.create(user=a,bindings={'software':group.pk})
    get('ChannelGroupingOverride').objects.create(user=a,source=source,group=group)
    get('ChannelGroupingProposal').objects.create(user=a,source_ids=[source.pk],input_snapshot='synthetic-hash',expires_at=timezone.now())
    get('SubscriptionGroupingState').objects.create(subscription=sub,status='ready')
    get('ChannelClassifierSettings').objects.create(owner=a,enabled=False)
    get('ChannelIntakeRequest').objects.create(user=a,url='https://intake.example/feed',status='approved',registered_source=source,reviewed_by=a)
    get('UserProviderCredential').objects.create(user=a,provider='openai',model_id='synthetic-never-called',encrypted_api_key='unused-synthetic-ciphertext')
    get('ChatGPTSubscriptionSelection').objects.create(user=a,generation=3)
    get('FeedState').objects.create(source_key='devto',feed_url='https://dev.to/feed',etag='synthetic-retained-etag',revision=8)

    get('Favorite').objects.create(user=a, news=news, type='bookmark')
    get('BlockedNews').objects.create(user=a, news=news)
    get('ReadingDay').objects.create(user=a, news=news, day=timezone.now().date())
    get('ChatSession').objects.create(user=a, news=news, messages=[{'role':'user','content':'retained history'}])
    research = get('ResearchSession').objects.create(user=a, title='retained research', messages=[{'content':'synthetic'}])
    get('ResearchSearchResult').objects.create(session=research, tool_name='search', result_type='news', url=news.url)
    conn = get('ChatGPTSubscriptionConnection').objects.create(user=a, subject_hash='synthetic-subject', issuer='synthetic',
        issued_client_id='synthetic', registration_key_hash='synthetic', encrypted_access_token='unused-synthetic-not-a-secret')
    get('ChatGPTArticleTranslation').objects.create(user=a, connection=conn, news=news, source_hash=hashlib.sha256(body.encode()).hexdigest(),
        model_slug='synthetic-provider-never-called', content='私人历史译文', completed_at=timezone.now())
    get('SharedArticleTranslation').objects.create(news=news, source_hash=hashlib.sha256(body.encode()).hexdigest(),
        translation_version='v1', content='共享历史译文', provider='synthetic-never-called', completed_at=timezone.now())
    get('ChatGPTTranslationTask').objects.create(user=a, connection=conn, news=news, source_hash='historical-task',
        model_slug='synthetic', connection_generation=3)
    get('SharedArticleTranslationTask').objects.create(news=news, source_hash='historical-task', translation_version='v1', initiated_by=a)
    save('seed', {'tables':tables(), 'news_id':news.pk, 'source_id':source.pk, 'user_id':a.pk,
        'body_sha256':hashlib.sha256(body.encode()).hexdigest(), 'schema':'0051', 'dataset':'synthetic'})


def upgrade():
    before = load('seed')
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    executor.migrate(leaves)
    after = tables(before['tables'])
    assert before['tables'] == after, 'old-column/PK/FK/text relationship fingerprint changed'
    from api.models import News, LegacyTranslationSnapshot, NewsReadState
    from api.services.stored_readers import legacy_translation
    news = News.objects.get(pk=before['news_id'])
    assert news.full_content_hash == before['body_sha256']
    assert news.body_owner_source_id == before['source_id'] and news.full_content_revision == 17
    assert not NewsReadState.objects.exists(), 'ReadingDay must not infer read state'
    for field in ('title','content','full_content'):
        assert legacy_translation(news.pk, field, getattr(news,field)).translated_text == getattr(news, field+'_zh')
    assert LegacyTranslationSnapshot.objects.filter(news=news).count() == 3
    save('upgrade', {'schema':leaves, 'old_tables':after, 'legacy_translation_count':3,
        'unchanged_old_columns':True, 'inferred_read_states':0})


def exercise():
    from django.contrib.auth.models import User
    from django.http import Http404
    from api.models import (News, Source, SourcePublication, FeedBinding, SourceFeedLink, EngineEntryMap,
        ChannelSubscription, NewsReadState, LegacyTranslationSnapshot)
    from api.rss.legacy_fencing import capture_source_token, legacy_translation_update
    from api.rss.source_migration import apply, MigrationBlocked
    from api.rss.content import convert_html
    from api.rss.content_store import capture_write_token, commit_body, fenced_article
    from api.rss.legacy_translation import archive_changed_translations
    from api.services.news_ingestion import ingest_item
    from api.services.full_content_status import enqueue_fetch, claim_fetch, mark_success
    from api.services.article_fetcher.types import FetchResult
    from api.rss.engine import FeedDTO, PolicyReceipt
    from types import SimpleNamespace
    seed = load('seed')
    news = News.objects.get(pk=seed['news_id'])
    source = news.source
    token = capture_source_token('devto')
    assert enqueue_fetch(news, force=True) == 'queued'
    assert claim_fetch(news)
    alias, _ = Source.objects.get_or_create(name='WebKit',defaults={'url':'https://webkit.org/'})
    SourcePublication.objects.update_or_create(source=alias, defaults={'owner':'legacy','publication':'public','reading_policy':'standard'})
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=2, engine_feed_id=26,
        canonical_feed_url='https://dev.to/feed', desired_mode='feed', desired_enabled=False, connection_state='paused')
    for src in (source,alias):
        SourceFeedLink.objects.create(source=src,binding=binding,enabled=True)
    engine_url = 'http://synthetic-miniflux.invalid'
    class SyntheticPolicyEngine:
        """Policy receipt fixture only; this stage explicitly makes no network call."""
        config = SimpleNamespace(engine_instance_uuid=str(binding.engine_instance_uuid), account_id=2, base_url=engine_url)
        def update_feed_policy(self, value, expected_policy_version):
            assert not connection.in_atomic_block
            return PolicyReceipt(FeedDTO(str(binding.engine_instance_uuid),2,26,binding.canonical_feed_url,
                'Synthetic receipt',value.desired_mode=='full_content',not value.desired_enabled),expected_policy_version)
    def manifest(target):
        news.refresh_from_db()
        rows=[]
        for src in (source,alias):
            pub=SourcePublication.objects.get(source=src)
            takeover=[] if src==alias else [{'news_id':news.pk,'expected_url':news.url,
                'expected_owner_source_id':news.body_owner_source_id,
                'expected_owner_binding_id':str(news.body_owner_binding_id) if news.body_owner_binding_id else None,
                'expected_body_owner_version':news.body_owner_version,'target_binding_id':str(binding.pk)}]
            rows.append({'source_id':src.pk,'expected_owner':pub.owner,'expected_epoch':pub.epoch,
                'expected_policy_version':pub.policy_version,'target_owner':target,'binding_id':str(binding.pk),
                'legacy_source_keys':['devto'] if src==source else ['webkit'],'body_takeover':takeover})
        sha=os.environ['REHEARSAL_APP_SHA']
        return {'schema_version':1,'kind':'rss_source_migration','id':str(uuid.uuid4()),'environment':'isolated',
            'app_sha':sha,'target':{'database':str(DB),'device':DB.stat().st_dev,'inode':DB.stat().st_ino,
                'engine_instance_uuid':str(binding.engine_instance_uuid),'account_id':2,'engine_base_url':engine_url},
            'allowlist':{'databases':[str(DB)],'engine_base_urls':[engine_url]},
            'drain':{'fenced_version':sha,'old_processes':[]},'sources':rows}
    data=manifest('miniflux')
    try:
        apply(data,source_ids=[source.pk],environment='isolated',adapter=SyntheticPolicyEngine(),execute=True)
        raise AssertionError('partial shared group accepted')
    except MigrationBlocked:
        pass
    assert apply(data,source_ids=[source.pk,alias.pk],environment='isolated',adapter=SyntheticPolicyEngine(),execute=True)['verified']
    save('switch_manifest',data)
    late=ingest_item(dict(source_key='devto',source_name='Dev.to',upstream_id='26',title='late old title',
        category_name='T26 synthetic',url=news.url,summary='late old summary',content_kind='article'),legacy_token=token)
    assert late.receipt_outcome=='deferred'
    assert not mark_success(news,FetchResult(ok=True,markdown='late old worker body',provider='synthetic'))
    entry=EngineEntryMap.objects.create(binding=binding,engine_entry_id=26,news=news,source_url=news.url,disposition='linked')
    current=capture_write_token(news_id=news.pk,source_id=source.pk,entry_id=entry.pk)
    old_title,old_content=news.title,news.content
    with fenced_article(current) as fresh:
        clear=archive_changed_translations(fresh, {'title':'Current engine title','content':'Current engine summary'})
        News.objects.filter(pk=news.pk).update(title='Current engine title',content='Current engine summary',**clear)
    assert commit_body(current,convert_html('<p>New short stored engine body.</p>',base_url=news.url)).status=='accepted'
    assert not legacy_translation_update(news,{'title_zh':'晚到旧标题'},title=old_title,content=old_content)
    assert LegacyTranslationSnapshot.objects.filter(news=news,translated_text='晚到旧标题',source_text=old_title).exists()
    news.refresh_from_db()
    assert news.title_zh=='' and news.full_content_state=='available' and news.full_content_revision==18
    # Create genuinely new post-upgrade data before application image rollback.
    personal=Source.objects.create(name='T26 personal paused',url='https://personal.example/')
    SourcePublication.objects.create(source=personal,publication='personal',owner='paused',reading_policy='standard')
    user=User.objects.get(pk=seed['user_id'])
    ChannelSubscription.objects.create(user=user,source=personal)
    private=News.objects.create(source=personal,category=news.category,title='private stored',content='private summary',
        url='https://personal.example/item',full_content='Private stored body',full_content_state='available',
        body_owner_source=personal,publish_time=timezone.now())
    NewsReadState.objects.create(user=user,news=news,is_read=True)
    # Ownership roundtrip keeps all new body bytes and history, increments fences.
    backward=manifest('legacy')
    assert apply(backward,source_ids=[source.pk,alias.pk],environment='isolated',adapter=SyntheticPolicyEngine(),execute=True)['verified']
    assert apply(manifest('miniflux'),source_ids=[source.pk,alias.pk],environment='isolated',adapter=SyntheticPolicyEngine(),execute=True)['verified']
    news.refresh_from_db()
    assert news.body_owner_version==4 and SourcePublication.objects.get(source=source).epoch==7
    # Control API compatibility uses fixed synthetic instance/account, no token.
    # It only enqueues durable intents; network is disabled by the container.
    from rest_framework.test import APIClient
    from django.core.files.uploadedfile import SimpleUploadedFile
    from api.rss.opml import process_imports
    os.environ['RSS_ENGINE_INSTANCE_UUID']=str(binding.engine_instance_uuid)
    os.environ['RSS_ENGINE_ACCOUNT_ID']=str(binding.account_id)
    client=APIClient(); client.force_authenticate(user)
    subscribed=client.post('/api/me/rss-subscriptions/',{'feed_url':binding.canonical_feed_url},
        format='json',HTTP_IDEMPOTENCY_KEY='t26-existing-subscription')
    assert subscribed.status_code in (200,201,202), subscribed.data
    xml=('<opml><body><outline type="rss" xmlUrl="'+binding.canonical_feed_url+'"/></body></opml>').encode()
    preview=client.post('/api/me/rss-imports/preview/',{'file':SimpleUploadedFile('synthetic.opml',xml)},format='multipart')
    assert preview.status_code==201, preview.data
    confirm=client.post('/api/me/rss-imports/confirm/',{'preview_token':preview.data['preview_token'],
        'selected_ids':[item['id'] for item in preview.data['items']],'group_map':{}},format='json')
    assert confirm.status_code==202, confirm.data
    process_imports()
    save('exercise',{'new_news_id':private.pk,'old_news_id':news.pk,'opml_batch_id':preview.data['id'],'body_revision':news.full_content_revision,
        'body_owner_version':news.body_owner_version,'source_epoch':7,'shared_group_size':2,
        'late_worker_rejected':True,'late_translation_archived_not_current':True,
        'policy_engine':'synthetic receipt, NOT real Miniflux','tables':tables()})


def verify():
    from django.contrib.auth.models import User, AnonymousUser
    from django.http import Http404
    from api.models import News, NewsReadState
    from api.rss.access import get_stored_article
    from api.services.stored_readers import legacy_translation
    expected=load('exercise')
    assert tables()==expected['tables'], 'application-only rollback changed stored data'
    a=User.objects.get(username='synthetic-a'); b=User.objects.get(username='synthetic-b')
    public=get_stored_article(AnonymousUser(),expected['old_news_id'])
    assert public.scope=='full' and public.markdown=='New short stored engine body.' and public.revision==18
    assert public.body_owner=='miniflux' and public.completeness=='unknown'
    assert get_stored_article(a,expected['new_news_id']).scope=='full'
    for actor in (b,AnonymousUser()):
        try:
            get_stored_article(actor,expected['new_news_id'])
            raise AssertionError('personal body leaked')
        except Http404:
            pass
    assert NewsReadState.objects.filter(user=a,news_id=expected['old_news_id'],is_read=True).exists()
    old=News.objects.get(pk=expected['old_news_id'])
    assert legacy_translation(old.pk,'title',old.title) is None
    assert legacy_translation(old.pk,'full_content',old.full_content) is None
    from rest_framework.test import APIClient
    client=APIClient(); client.force_authenticate(a)
    assert client.get('/api/me/rss-subscriptions/').status_code==200
    assert client.get('/api/me/rss-subscriptions/export/').status_code==200
    assert client.get('/api/me/rss-imports/'+expected['opml_batch_id']+'/').status_code==200
    state=client.get('/api/me/news/'+str(expected['old_news_id'])+'/read-state/')
    assert state.status_code==200 and state.data['is_read'] is True
    client.force_authenticate(b)
    assert client.get('/api/me/rss-imports/'+expected['opml_batch_id']+'/').status_code==404
    # Exercise the real WSGI URL/serializer path on container-local loopback.
    # No host port, session write or provider call is involved.
    from django.test import override_settings
    from django.core.wsgi import get_wsgi_application
    from wsgiref.simple_server import make_server
    from threading import Thread
    from urllib.request import build_opener, ProxyHandler
    from urllib.error import HTTPError
    import importlib.util
    assert all(importlib.util.find_spec(name) is not None for name in ('torch','scrapy','chromadb','waitress'))
    assert Path('/app/frontend/dist/index.html').is_file()
    with override_settings(ALLOWED_HOSTS=['127.0.0.1'], PUBLIC_SITE_MODE='full'):
        server=make_server('127.0.0.1',0,get_wsgi_application())
        thread=Thread(target=server.serve_forever,daemon=True); thread.start()
        opener=build_opener(ProxyHandler({}))
        try:
            base='http://127.0.0.1:'+str(server.server_port)+'/api/news/'
            with opener.open(base+str(expected['old_news_id'])+'/',timeout=20) as response:
                payload=json.load(response)
            assert payload['full_content']=='New short stored engine body.'
            assert payload['full_content_revision']==18 and payload['body_owner']=='miniflux'
            try:
                opener.open(base+str(expected['new_news_id'])+'/',timeout=20)
                raise AssertionError('anonymous HTTP personal article leaked')
            except HTTPError as error:
                assert error.code==404
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert tables()==expected['tables'], 'read verification mutated data'
    save(os.environ.get('REHEARSAL_STAGE','verify'), {'application_sha':os.environ['REHEARSAL_APP_SHA'],
        'all_table_fingerprint':digest(tables()),'schema':MigrationExecutor(connection).loader.graph.leaf_nodes(),
        'public_available_body':True,'actual_wsgi_http_available_and_acl':True,'subscription_opml_read_state_api_compatibility':True,'personal_paused_a_only':True,'read_state_preserved':True,
        'old_hash_translation_not_current':True,'no_database_restore_or_reverse_migration':True})


if __name__=='__main__':
    {'seed':seed,'upgrade':upgrade,'exercise':exercise,'verify':verify}[sys.argv[1]]()
