"""RSSHub aliases are server-owned Feed selections, never directory keywords."""
import pytest
from api.rss.models import FeedBinding
from api.rss.operations import OperationError, canonicalize_feed_url
from api.tests.rss.test_subscriptions import people,subscribe,client

pytestmark=pytest.mark.django_db(transaction=True)

@pytest.fixture
def gateway(settings):
    settings.RSSHUB_GATEWAY={'enabled':True,'verified':True,'origin':'https://feeds.example.com','version':1,
        'routes':['twitter.user','github.trending'],'capabilities':['twitter.public_only','config:TWITTER_AUTH_TOKEN','config:GITHUB_ACCESS_TOKEN'],
        'auth_required':False}
    return settings.RSSHUB_GATEWAY

def test_alias_and_https_converge_and_preserve_alias(people,gateway):
    a,b=people
    first=subscribe(a,feed_url='rsshub://twitter/user/elonmusk')
    other=subscribe(b,feed_url='https://feeds.example.com/twitter/user/elonmusk')
    assert first.status_code==other.status_code==202
    binding=FeedBinding.objects.get()
    assert binding.canonical_feed_url=='https://feeds.example.com/twitter/user/elonmusk'
    assert binding.rsshub_alias=='rsshub://twitter/user/elonmusk'
    assert len(binding.rsshub_gateway_version)==64 and binding.desired_mode=='feed'

def test_unconfigured_alias_has_actionable_error_and_creates_nothing(people,settings):
    settings.RSSHUB_GATEWAY={}
    response=subscribe(people[0],feed_url='rsshub://twitter/user/elonmusk')
    assert response.status_code==400
    assert 'RSSHub' in str(response.data) and '配置' in str(response.data)
    assert not FeedBinding.objects.exists()

@pytest.mark.parametrize('value',['rsshub://twitter/user/elonmusk?url=http://127.0.0.1',
    'rsshub://twitter/user/../admin','rsshub://twitter/user/elonmusk%2Fadmin',
    'https://feeds.example.com/anything','rsshub://evil/user/a','rsshub://user:pass@twitter/user/a'])
def test_bad_or_unapproved_routes_fail_closed(people,gateway,value):
    assert subscribe(people[0],feed_url=value).status_code==400
    assert not FeedBinding.objects.exists()

def test_config_change_blocks_old_binding_without_rebinding(people,gateway,settings):
    from api.rss.feed_policy import assert_binding_policy
    assert subscribe(people[0],feed_url='rsshub://twitter/user/elonmusk').status_code==202
    binding=FeedBinding.objects.get()
    settings.RSSHUB_GATEWAY={**gateway,'version':2}
    with pytest.raises(OperationError,match='rsshub_configuration_changed'): assert_binding_policy(binding)
    assert FeedBinding.objects.get().canonical_feed_url=='https://feeds.example.com/twitter/user/elonmusk'

def test_missing_twitter_capability_is_not_a_fake_connection(people,gateway,settings):
    settings.RSSHUB_GATEWAY={**gateway,'capabilities':[]}
    response=subscribe(people[0],feed_url='rsshub://twitter/user/elonmusk')
    assert response.status_code==400 and not FeedBinding.objects.exists()

def test_opml_uses_the_same_alias_resolution(gateway):
    from api.rss.opml import parse_opml
    rows=parse_opml(b'<opml version="2.0"><body><outline text="x" xmlUrl="rsshub://twitter/user/elonmusk"/></body></opml>')
    assert rows[0]['feed_url']=='https://feeds.example.com/twitter/user/elonmusk'
    assert rows[0]['status']=='preview'

def test_late_gateway_response_cannot_commit_after_configuration_change(people,gateway,settings):
    from api.rss.control_worker import ControlWorker,Outcome
    from api.rss.engine import EngineConfig,FeedDTO
    from api.rss.models import FeedOperation
    from api.models import ChannelSubscription
    from api.rss.subscriptions import engine_identity
    a,_=people;response=subscribe(a,feed_url='rsshub://twitter/user/elonmusk')
    instance,account=engine_identity()
    worker=ControlWorker(EngineConfig(str(instance),account,'http://127.0.0.1:1','synthetic'))
    try:
        request=worker.prepare(worker.claim_next())
        settings.RSSHUB_GATEWAY={**gateway,'version':2}
        outcome=Outcome(feed=FeedDTO(str(instance),account,111,request.url,'Gateway',False,False))
        worker.complete(request,outcome)
        assert not ChannelSubscription.objects.filter(user=a).exists()
        op=FeedOperation.objects.get(pk=response.data['operation_id'])
        assert op.state in {'unknown','manual_blocked'}
    finally:worker.close()

def test_gateway_auth_is_worker_only_and_dto_opml_keep_alias(people,gateway,settings,tmp_path):
    import json
    from types import SimpleNamespace
    from api.rss.engine import EngineAdapter,EngineConfig
    from api.rss.opml import export_opml
    from api.tests.rss.registration_fixtures import connect_pending
    from api.rss.subscriptions import engine_identity
    auth=tmp_path/'auth.json';auth.write_text(json.dumps({'username':'synthetic-gateway','password':'synthetic-private-password'}))
    settings.RSSHUB_GATEWAY={**gateway,'auth_file':str(auth),'auth_required':True}
    result=subscribe(people[0],feed_url='rsshub://twitter/user/elonmusk');assert result.status_code==202
    connect_pending()
    instance,account=engine_identity();row={}
    def create(url,**fields):
        row.update(id=123,user_id=account,feed_url=url,title='Gateway',**fields)
        return 123
    adapter=object.__new__(EngineAdapter)
    adapter.config=EngineConfig(str(instance),account,'http://engine:8080','synthetic-api')
    adapter._identity_checked=False
    adapter._client=SimpleNamespace(me=lambda:{'id':account,'is_admin':False},get_feeds=lambda:[],create_feed=create,get_feed=lambda _:row)
    adapter._call=lambda fn,**kw:fn()
    dto=adapter.create_feed('https://feeds.example.com/twitter/user/elonmusk')
    assert row['username']=='synthetic-gateway' and row['password']=='synthetic-private-password'
    assert 'synthetic-private-password' not in repr(dto) and 'password' not in result.data
    exported=export_opml(people[0])
    assert b'rsshub://twitter/user/elonmusk' in exported and b'synthetic-private-password' not in exported

def test_category_change_rejects_stale_writes(people):
    from api.models import Category
    from api.tests.rss.registration_fixtures import connect_pending
    a,_=people;response=subscribe(a);connect_pending()
    category=Category.objects.create(name='CAS',slug='cas')
    data={'action':'set_category','source_ids':[response.data['source_id']],'category_id':category.pk,'expected_version':0}
    assert client(a).post('/api/me/channel-subscriptions/',data,format='json').status_code==200
    assert client(a).post('/api/me/channel-subscriptions/',{**data,'category_id':None},format='json').status_code==409

def test_gateway_https_is_resolved_locally_without_unauthenticated_discovery(people,gateway):
    from api.rss.models import FeedOperation
    response=client(people[0]).post('/api/rss/discovery/resolve/',{'input':'https://feeds.example.com/twitter/user/elonmusk'},format='json')
    assert response.status_code==200
    assert response.data['kind']=='feed' and response.data['feed_url']=='rsshub://twitter/user/elonmusk'
    assert not FeedOperation.objects.exists()

def test_configuration_revocation_does_not_block_confirmed_feed_disable(people,gateway,settings):
    from api.rss.control_worker import ControlWorker,Outcome
    from api.rss.engine import EngineConfig,FeedDTO
    from api.rss.models import FeedOperation
    from api.rss.subscriptions import engine_identity,unsubscribe
    from api.tests.rss.registration_fixtures import connect_pending
    from api.models import ChannelSubscription
    a,_=people;subscribe(a,feed_url='rsshub://twitter/user/elonmusk');connect_pending()
    binding=FeedBinding.objects.get();instance,account=engine_identity()
    settings.RSSHUB_GATEWAY={**gateway,'enabled':False}
    unsubscribe(a,ChannelSubscription.objects.get(user=a).pk)
    worker=ControlWorker(EngineConfig(str(instance),account,'http://127.0.0.1:1','synthetic'))
    try:
        request=worker.prepare(worker.claim_next());assert request.policy.desired_enabled is False
        worker.complete(request,Outcome(feed=FeedDTO(str(instance),account,binding.engine_feed_id,request.url,'Gateway',False,True)))
        binding.refresh_from_db()
        assert binding.connection_state=='paused' and binding.applied_policy_version==binding.policy_version
        assert not FeedOperation.objects.filter(binding=binding,state__in=['unknown','manual_blocked']).exists()
    finally:worker.close()

def test_non_article_rsshub_template_retains_feed_policy_restrictions(gateway,settings):
    from api.rss.feed_policy import approved_feed_policy
    settings.RSSHUB_GATEWAY={**gateway,'routes':['github.issue'],'repositories':[['DIYgod','RSSHub']]}
    admission=approved_feed_policy('rsshub://github/issue/DIYgod/RSSHub/open')
    assert admission.desired_mode=='feed' and admission.content_kind=='issue'
    assert admission.reading_policy=='rss_summary_only' and not admission.full_content_allowed

def test_new_rsshub_connection_pins_initial_seven_day_range_without_resetting_existing(people,gateway):
    from datetime import timedelta
    from django.utils import timezone
    first=subscribe(people[0],feed_url='rsshub://twitter/user/elonmusk')
    assert first.status_code==202
    binding=FeedBinding.objects.get()
    assert binding.published_since==timezone.now().date()-timedelta(days=7)
    original=binding.published_since-timedelta(days=1)
    FeedBinding.objects.filter(pk=binding.pk).update(published_since=original)
    subscribe(people[1],feed_url='https://feeds.example.com/twitter/user/elonmusk')
    binding.refresh_from_db();assert binding.published_since==original


def test_operator_proxy_applies_only_to_gateway_and_fences_changes(gateway,settings):
    from api.rss.rsshub import credentials,selection
    gateway['proxy_url']='http://rsshub-proxy:3128'
    before=selection('rsshub://twitter/user/elonmusk')
    assert credentials(before.url)=={'proxy_url':'http://rsshub-proxy:3128'}
    assert credentials('https://example.org/feed')=={}
    settings.RSSHUB_GATEWAY={**gateway,'proxy_url':'http://rsshub-proxy:3129'}
    assert selection('rsshub://twitter/user/elonmusk').version!=before.version

@pytest.mark.parametrize('proxy',['http://user:secret@proxy:3128','file:///etc/passwd','http://proxy:3128/path','http://proxy:3128?token=x','http://proxy:3128#fragment'])
def test_malformed_operator_proxy_is_not_dispatched(gateway,proxy):
    from api.rss.rsshub import credentials
    gateway['proxy_url']=proxy
    with pytest.raises(OperationError,match='rsshub_unverified'):
        credentials('rsshub://twitter/user/elonmusk')
