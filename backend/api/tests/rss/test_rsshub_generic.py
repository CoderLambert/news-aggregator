"""Generic RSSHub syntax is independent of a per-template approval list."""
import pytest
from api.rss.operations import OperationError,canonicalize_feed_url
from api.tests.rss.test_subscriptions import people,subscribe,client
from api.rss.models import FeedBinding
pytestmark=pytest.mark.django_db(transaction=True)

@pytest.fixture
def generic(settings):
    settings.RSSHUB_GATEWAY={'enabled':True,'verified':True,'version':1,'origin':'https://feeds.example.com',
        'routes':['github.issue'],'repositories':[['DIYgod','RSSHub']],'capabilities':[],
        'auth_required':False,'generic':True,'generic_version':1,'blocked_namespaces':['twitter']}
    return settings.RSSHUB_GATEWAY

@pytest.mark.parametrize('alias,path',[
    ('rsshub://freecomputerbooks','/freecomputerbooks'),
    ('rsshub://freecomputerbooks/compscAlgorithmBooks','/freecomputerbooks/compscAlgorithmBooks'),
    ('rsshub://36kr/newsflashes','/36kr/newsflashes'),
    ('rsshub://bilibili/user/video/123456','/bilibili/user/video/123456'),
    ('rsshub://github/issue/python/cpython/open','/github/issue/python/cpython/open'),
    ('rsshub://some-future-route/a_b/123?limit=15&filter_title=Python','/some-future-route/a_b/123?limit=15&filter_title=Python'),
    ('rsshub://bilibili/search/人工智能','/bilibili/search/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD'),
    ('rsshub://example/item/1234567890abcdef1234567890abcdef','/example/item/1234567890abcdef1234567890abcdef'),
    ('rsshub://example/from/https%3A%2F%2Fexample.com%2Fnews','/example/from/https%3A%2F%2Fexample.com%2Fnews'),
])
def test_generic_alias_and_https_converge(people,generic,alias,path):
    first=subscribe(people[0],feed_url=alias);other=subscribe(people[1],feed_url='https://feeds.example.com'+path)
    assert first.status_code==other.status_code==202,(first.data,other.data)
    binding=FeedBinding.objects.get()
    assert binding.canonical_feed_url=='https://feeds.example.com'+path
    assert binding.rsshub_alias=='rsshub:/'+path
    assert binding.desired_mode=='feed' and binding.published_since is not None

@pytest.mark.parametrize('value',[
    'rsshub://user:password@freecomputerbooks','rsshub://127.0.0.1/private','rsshub://localhost/x','rsshub://api/config',
    'rsshub://foo/../healthz','rsshub://foo/%2e%2e/bar','rsshub://foo/%252e%252e/bar','rsshub://foo/a%0d%0aHeader:x',
    'rsshub://foo/path#fragment','rsshub://foo/path?token=hidden','rsshub://foo/path?proxy=http://127.0.0.1',
    'rsshub://foo/path?url=https%3A%2F%2Fuser%3Apass%40example.org','rsshub://foo/%GG',
])
def test_generic_rejects_unsafe_structure_and_credentials(people,generic,value):
    assert subscribe(people[0],feed_url=value).status_code==400
    assert not FeedBinding.objects.exists()

def test_twitter_skip_is_actionable_not_invalid_format(people,generic):
    result=subscribe(people[0],feed_url='rsshub://twitter/user/elonmusk')
    assert result.status_code==400
    assert '暂停' in str(result.data)

def test_generic_change_fences_its_own_bindings_but_preserves_legacy(generic,settings):
    from api.rss.rsshub import selection
    legacy='rsshub://github/issue/DIYgod/RSSHub/open'
    before=selection(legacy)
    general=selection('rsshub://freecomputerbooks')
    settings.RSSHUB_GATEWAY={**generic,'generic_version':2}
    assert selection(legacy).version==before.version
    assert selection('rsshub://freecomputerbooks').version!=general.version

def test_generic_opml_keeps_alias_and_never_requires_live_config(people,generic,settings):
    from api.rss.opml import parse_opml,export_opml
    from api.tests.rss.registration_fixtures import connect_pending
    alias='rsshub://freecomputerbooks?limit=10'
    assert parse_opml(('<opml><body><outline text="Books" xmlUrl="'+alias+'"/></body></opml>').encode())[0]['feed_url']=='https://feeds.example.com/freecomputerbooks?limit=10'
    assert subscribe(people[0],feed_url=alias).status_code==202
    connect_pending();settings.RSSHUB_GATEWAY={}
    assert alias.encode() in export_opml(people[0])

def test_generic_feed_policy_is_conservative(generic):
    from api.rss.feed_policy import approved_feed_policy
    result=approved_feed_policy('rsshub://freecomputerbooks')
    assert result.desired_mode=='feed' and result.reading_policy=='rss_summary_only'
    assert not result.full_content_allowed
