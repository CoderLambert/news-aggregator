"""Regression coverage for real channel failures without publisher traffic."""
from types import SimpleNamespace
import asyncio

from scrapy import Request
from scrapy.crawler import Crawler
from scrapy.http import HtmlResponse
from scrapy.settings import Settings
from scrapy.statscollectors import MemoryStatsCollector
from scrapy.downloadermiddlewares.offsite import OffsiteMiddleware

from api.services.crawl_metrics import crawl_result, describe_crawl_result
from news_crawler.spiders.bbc_spider import BbcSpider
from news_crawler.spiders.feed import FeedSpider
from news_crawler.spiders.mistral_blog_spider import MistralBlogSpider
from news_crawler.spiders.meta_ai_blog_spider import MetaAiBlogSpider


def test_bbc_reviewed_feed_host_is_admitted_without_admitting_unrelated_hosts():
    crawler = Crawler(BbcSpider, Settings())
    crawler.stats = MemoryStatsCollector(crawler)
    spider = BbcSpider.from_crawler(crawler)
    crawler.spider = spider
    middleware = OffsiteMiddleware.from_crawler(crawler)
    middleware.spider_opened(spider)
    assert middleware.should_follow(Request('https://feeds.bbci.co.uk/news/world/rss.xml'), spider)
    assert not middleware.should_follow(Request('https://unreviewed.example/rss.xml'), spider)


def test_robots_403_does_not_mark_a_successful_feed_blocked():
    result = crawl_result({'finish_reason':'finished', 'outcome':'updated',
        'entries_committed':48, 'entries_changed':48, 'request_classification_available':True,
        'budget/http_status_count/403':1, 'budget/http_status_count/200':1,
        'auxiliary/http_status_count/403':1, 'discovery/http_status_count/200':1})
    assert result['outcome']=='updated'
    assert result['http_statuses']=={'403':1,'200':1}
    assert result['warnings']==['robots_unavailable']
    assert 'robots.txt' in describe_crawl_result(result)


def test_robots_timeouts_remain_warnings_when_all_discovery_requests_succeed():
    result=crawl_result({'finish_reason':'finished', 'entries_committed':310,
        'entries_changed':310, 'request_classification_available':True,
        'discovery/http_status_count/200':7, 'auxiliary/failures/timeout':2, 'log_count/ERROR':2})
    assert result['outcome']=='updated' and result['network_failures']==0
    assert result['auxiliary_failures']==2 and result['warnings']==['robots_unavailable']


def test_primary_network_failure_and_filtered_requests_have_specific_results():
    result=crawl_result({'finish_reason':'finished','request_classification_available':True,
        'discovery/failures/timeout':2,'log_count/ERROR':2})
    assert result['outcome']=='network_error'
    assert '超时' in describe_crawl_result(result)
    filtered=crawl_result({'finish_reason':'finished','outcome':'deferred','offsite/filtered':3})
    assert filtered['outcome']=='filtered'


def test_partial_ingestion_keeps_committed_count_and_underlying_parse_reason():
    result=crawl_result({'finish_reason':'finished','entries_committed':17,'parse_failures':3})
    assert result['outcome']=='partial' and result['failure_outcome']=='parse_failed'
    assert '17 条成功入库' in describe_crawl_result(result)


def test_feed_transport_timeout_is_not_a_parser_error():
    spider=FeedSpider(name="webkit")
    spider.feed_outcomes=[];spider.feed_errors=0
    failure=SimpleNamespace(request=Request('https://webkit.org/feed/'),value=TimeoutError())
    asyncio.run(spider.feed_failed(failure))
    assert spider.feed_outcomes==['network_error'] and spider.feed_errors==0


def test_mistral_summary_preserves_nested_title_and_inline_prose():
    url='https://mistral.ai/news/test-article'
    body='<article><h1><span>Nested publisher title</span></h1><p><strong>'+('Real publisher prose. '*20)+'</strong></p></article>'
    response=HtmlResponse(url,request=Request(url,meta={'discovery_target_url':url}),body=body.encode(),encoding='utf-8')
    item=list(MistralBlogSpider().parse_article(response))[0]
    assert item['title']=='Nested publisher title' and 'Real publisher prose.' in item['content']


def test_meta_error_page_is_not_parsed_as_an_article_listing():
    spider=MetaAiBlogSpider()
    spider._set_crawler(SimpleNamespace(settings=Settings(),signals=SimpleNamespace(connect=lambda *a,**kw:None),stats=SimpleNamespace(set_value=lambda k,v:values.update({k:v}))))
    values={}
    response=HtmlResponse('https://ai.meta.com/blog/',status=400,request=Request('https://ai.meta.com/blog/'),body=b'<a href="/blog/fake">Error page</a>',encoding='utf-8')
    assert list(spider.parse(response))==[] and values['outcome']=='http_error'


def test_infoq_and_mistral_use_publisher_advertised_feed_endpoints():
    from api.services.source_policy import POLICIES
    from news_crawler.spiders.infoq_spider import InfoQSpider
    assert POLICIES['infoq'].feed_url == 'https://feed.infoq.com/news/'
    assert InfoQSpider.start_urls == [POLICIES['infoq'].feed_url]
    assert MistralBlogSpider.start_urls == ['https://mistral.ai/news/rss']
    assert issubclass(MistralBlogSpider, FeedSpider)
    assert POLICIES['mistral'].body_fields == ()  # RSS description remains a summary.


def test_restricted_channels_cannot_be_enabled_through_the_admin_serializer():
    from api.models import CrawlerTarget
    from api.crawler_serializers import CrawlerTargetSerializer
    target = CrawlerTarget(spider_name='reuters', enabled=False)
    serializer = CrawlerTargetSerializer(target, data={'enabled':True}, partial=True)
    assert not serializer.is_valid() and 'enabled' in serializer.errors
    disabled = CrawlerTargetSerializer(target, data={'enabled':False}, partial=True)
    assert disabled.is_valid()
    assert CrawlerTargetSerializer(target).data['supported'] is False


import pytest

@pytest.mark.django_db
def test_batch_excludes_unsupported_channels_even_if_a_legacy_flag_is_enabled():
    from api.models import CrawlerTarget
    from api.services.crawler_control import create_crawl_batch
    CrawlerTarget.objects.create(spider_name='bbc',display_name='BBC',enabled=True)
    CrawlerTarget.objects.create(spider_name='jiqizhixin',display_name='机器之心',enabled=True)
    batch,_ = create_crawl_batch(trigger='manual',spider_names=['bbc','jiqizhixin'])
    assert list(batch.runs.values_list('target_id',flat=True)) == ['bbc']
    assert not CrawlerTarget.objects.get(pk='jiqizhixin').enabled  # Retired sources cannot resume.


def test_arxiv_uses_the_published_subscription_host_and_keeps_abstract_kind():
    from api.services.source_policy import POLICIES
    from news_crawler.spiders.arxiv_ai_spider import ArxivAiSpider
    assert ArxivAiSpider.start_urls == ['https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL']
    assert POLICIES['arxiv_ai'].content_kind == 'abstract' and not POLICIES['arxiv_ai'].html_allowed


def test_robots_denial_is_reported_as_access_policy_not_network_failure():
    from scrapy.exceptions import IgnoreRequest
    values={}
    spider=FeedSpider(name='arxiv_ai')
    spider.feed_outcomes=[];spider.feed_errors=0
    spider._set_crawler(SimpleNamespace(settings=Settings(),signals=SimpleNamespace(connect=lambda *a,**kw:None),
        stats=SimpleNamespace(set_value=lambda k,v:values.update({k:v}))))
    failure=SimpleNamespace(request=Request('https://export.arxiv.org/api/query'),value=IgnoreRequest('Forbidden by robots.txt'))
    asyncio.run(spider.feed_failed(failure))
    assert spider.feed_outcomes==['blocked'] and spider.feed_errors==0
    assert values['robots_disallowed'] is True
    result=crawl_result({'finish_reason':'finished','outcome':'blocked',**values})
    assert 'robots.txt 不允许' in describe_crawl_result(result)


@pytest.mark.django_db
def test_dashboard_target_status_uses_latest_result_without_rewriting_history():
    from api.models import CrawlerTarget, CrawlBatch, CrawlRun
    from api.crawler_views import target_queryset
    from api.crawler_serializers import CrawlerTargetSerializer
    from django.utils import timezone
    target=CrawlerTarget.objects.create(spider_name='webkit',display_name='WebKit',last_status='failed')
    batch=CrawlBatch.objects.create(trigger='manual',status='failed')
    run=CrawlRun.objects.create(batch=batch,target=target,status='failed',exit_code=0,
        finished_at=timezone.now(),stats={'outcome':'deferred','entries_committed':0})
    data=CrawlerTargetSerializer(target_queryset().get(pk=target.pk)).data
    assert data['last_result_status']=='deferred'
    run.refresh_from_db();assert run.status=='failed'


def test_meta_div_wrapped_article_preview_excludes_the_footer_and_checks_canonical():
    url='https://ai.meta.com/blog/published-article/'
    body='<link rel="canonical" href="'+url+'"><div><div><h1><span>Real Meta title</span></h1></div><div><p><strong>'+('Publisher article prose. '*20)+'</strong></p></div></div><footer><p>Unrelated footer text</p></footer>'
    response=HtmlResponse(url,request=Request(url,meta={'discovery_target_url':url}),body=body.encode(),encoding='utf-8')
    item=list(MetaAiBlogSpider().parse_article(response))[0]
    assert item['title']=='Real Meta title' and 'Publisher article prose.' in item['content']
    assert 'Unrelated footer text' not in item['content'] and 'body_candidate' not in item
    mismatched=body.replace('href="'+url+'"','href="https://ai.meta.com/blog/other-article/"')
    spider=MetaAiBlogSpider()
    spider._set_crawler(SimpleNamespace(settings=Settings(),signals=SimpleNamespace(connect=lambda *a,**kw:None),stats=SimpleNamespace(inc_value=lambda *a,**kw:None)))
    wrong=HtmlResponse(url,request=Request(url,meta={'discovery_target_url':url}),body=mismatched.encode(),encoding='utf-8')
    assert list(spider.parse_article(wrong))==[]


@pytest.mark.django_db
def test_latest_retry_displays_waiting_without_overwriting_the_original_failure():
    from api.models import CrawlerTarget, CrawlBatch, CrawlRun
    from api.crawler_serializers import CrawlRunSerializer
    from api.crawler_views import batch_queryset
    target=CrawlerTarget.objects.create(spider_name='webkit',display_name='WebKit')
    batch=CrawlBatch.objects.create(trigger='manual',status='failed')
    old=CrawlRun.objects.create(batch=batch,target=target,status='failed',exit_code=0)
    retry=CrawlRun.objects.create(batch=batch,target=target,status='failed',exit_code=0,
        retry_of=old,stats={'outcome':'deferred','entries_committed':0})
    data=CrawlRunSerializer(batch_queryset().get(pk=batch.pk).runs.get(pk=old.pk)).data
    assert data['latest_retry_status']=='failed' and data['latest_retry_display_status']=='deferred'
    retry.refresh_from_db();assert retry.status=='failed'
