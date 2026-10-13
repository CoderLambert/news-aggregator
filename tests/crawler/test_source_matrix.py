"""Remaining source discovery contracts, using local RSS/Atom inputs only."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from importlib import import_module
from xml.sax.saxutils import escape

import pytest
from django.test import override_settings
from scrapy import Request, signals
from scrapy.crawler import Crawler
from scrapy.http import TextResponse
from scrapy.statscollectors import MemoryStatsCollector

from api.models import News, NewsSourceItem
from api.services.article_fetcher.types import FullContentCandidate
from api.services.article_fetcher.validators import validate_candidate
from api.services.feed_state import FeedRequestState
from api.services.feed_support import parse_feed, feed_entry_item
from api.services.news_ingestion import ingest_item
from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
ARXIV_ENDPOINT = 'https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL'
SUMMARY = 'Publisher-provided discovery summary.'
UNREVIEWED_BODY = '<p>Unreviewed long body that cannot become a full article.</p>' * 120
FEED_SOURCES = (
    ('bbc', 'bbc', 'BbcSpider'),
    ('techcrunch', 'techcrunch', 'TechCrunchSpider'),
    ('css_tricks', 'css_tricks', 'CssTricksSpider'),
    ('webdev', 'webdev', 'WebDevSpider'),
    ('chrome_dev', 'chrome_dev', 'ChromeDevSpider'),
    ('react_blog', 'react_blog', 'ReactBlogSpider'),
    ('openai_blog', 'openai_blog', 'OpenaiBlogSpider'),
    ('deepmind', 'deepmind_blog', 'DeepmindBlogSpider'),
    ('infoq', 'infoq', 'InfoQSpider'),
    ('ars_technica_ai', 'ars_technica_ai', 'ArsTechnicaAiSpider'),
    ('mit_tech_review_ai', 'mit_tech_review_ai', 'MitTechReviewAiSpider'),
    ('producthunt', 'producthunt', 'ProductHuntSpider'),
    ('frontend_focus', 'frontend_focus', 'FrontendFocusSpider'),
    ('venturebeat_ai', 'venturebeat_ai', 'VenturebeatAiSpider'),
    ('arxiv_ai', 'arxiv_ai', 'ArxivAiSpider'),
)
SUMMARY_SOURCES = tuple(key for key, _, _ in FEED_SOURCES if key != 'frontend_focus')
EXPECTED_KEYS = {
    'devto', 'hackernews', 'github', 'leiphone', 'webkit', 'smashing_magazine',
    'v8', 'mozilla_hacks', 'svelte_blog', 'angular_blog', 'bbc', 'techcrunch',
    'css_tricks', 'webdev', 'chrome_dev', 'react_blog', 'openai_blog', 'deepmind',
    'infoq', 'ars_technica_ai', 'mit_tech_review_ai', 'arxiv_ai', 'producthunt',
    'frontend_focus', 'anthropic', 'meta_ai', 'mistral', 'venturebeat_ai',
    'reuters', 'jiqizhixin', 'sanliu_kr',
}
QUARANTINED = {
    'reuters': ('ReutersSpider', 'authorized_delivery_required'),
    'jiqizhixin': ('JiqizhixinSpider', 'publisher_identity_unavailable'),
    'sanliu_kr': ('SanliuKrSpider', 'invalid_feed_endpoint'),
}


def target_url(source):
    if source == 'arxiv_ai':
        return 'https://arxiv.org/abs/2610.12345v2'
    if source == 'frontend_focus':
        return 'https://frontendfoc.us/issues/663'
    if source == 'producthunt':
        return 'https://www.producthunt.com/posts/publisher-product'
    return 'https://' + POLICIES[source].domains[0] + '/publisher/article-17'


def feed_url(source):
    return ARXIV_ENDPOINT if source == 'arxiv_ai' else POLICIES[source].feed_url


def local_feed(source, *, published='2026-10-13T08:30:00-03:00', include_body=True,
               summary=SUMMARY, body=UNREVIEWED_BODY):
    target = target_url(source)
    identity = 'http://arxiv.org/abs/2610.12345v2' if source == 'arxiv_ai' else f'urn:Publisher:{source}:17'
    if source in {'arxiv_ai', 'producthunt'}:
        publication = '<published>' + published + '</published>' if published else ''
        content = '<content type="html"><![CDATA[' + body + ']]></content>' if include_body else ''
        entry = ('<entry><title>Explicit source title</title><id>' + identity + '</id>'
                 '<link rel="alternate" type="text/html" href="' + target + '"/>'
                 '<link rel="related" type="application/pdf" href="https://arxiv.org/pdf/2610.12345v2"/>'
                 + publication + '<updated>2026-10-13T20:00:00+08:00</updated>'
                 '<summary type="html"><![CDATA[' + summary + ']]></summary>' + content + '</entry>')
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Local fixture</title>'
               '<id>urn:Local:Fixture</id><updated>2026-10-13T12:00:00Z</updated>' + entry + '</feed>')
    else:
        publication = '<atom:published>' + published + '</atom:published>' if published else ''
        content = '<content:encoded><![CDATA[' + body + ']]></content:encoded>' if include_body else ''
        xml = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
               'xmlns:atom="http://www.w3.org/2005/Atom"><channel><title>Local fixture</title>'
               '<link>' + escape(feed_url(source)) + '</link><description>Local fixture</description>'
               '<item><title>Explicit source title</title><guid isPermaLink="false">' + identity + '</guid>'
               '<link>' + target + '</link>' + publication +
               '<atom:updated>2026-10-13T20:00:00+08:00</atom:updated>'
               '<description><![CDATA[' + summary + ']]></description>' + content + '</item></channel></rss>')
    return xml.encode('utf-8')


def item_from_feed(source, **kwargs):
    parsed = parse_feed(local_feed(source, **kwargs))
    return feed_entry_item(parsed.entries[0], source, feed_url=feed_url(source), effective_url=feed_url(source),
                           request_started_at=NOW, version=parsed.version, request_chain=(feed_url(source),))


def candidate_for(source, *, field='content:encoded', kind=None):
    policy = POLICIES[source]
    return FullContentCandidate(
        source, 'http://arxiv.org/abs/2610.12345v2' if source == 'arxiv_ai' else f'urn:Publisher:{source}:17', target_url(source),
        target_url(source) if field == 'article_html' else (feed_url(source) or target_url(source)),
        None, 'Explicit source title', kind or policy.content_kind,
        field, 'html', 'full', UNREVIEWED_BODY, NOW, None, NOW,
    )


def test_all_thirty_one_sources_have_explicit_and_unique_contracts():
    assert set(POLICIES) == EXPECTED_KEYS
    assert len({policy.name for policy in POLICIES.values()}) == 31
    assert all(key == policy.key for key, policy in POLICIES.items())
    assert all(policy.domains and policy.contract_version for policy in POLICIES.values())
    assert {key for key, policy in POLICIES.items() if policy.unsupported_reason} == set(QUARANTINED)
    assert {key: policy.content_kind for key, policy in POLICIES.items() if policy.content_kind != 'article'} == {
        'hackernews': 'discussion', 'github': 'readme', 'arxiv_ai': 'abstract',
        'producthunt': 'product', 'frontend_focus': 'newsletter',
    }


@pytest.mark.parametrize('source', SUMMARY_SOURCES)
def test_unreviewed_feed_body_fields_remain_discovery_summaries(source):
    item = item_from_feed(source)

    assert item['upstream_id'] == ('http://arxiv.org/abs/2610.12345v2' if source == 'arxiv_ai' else f'urn:Publisher:{source}:17')
    assert item['url'] == target_url(source)
    assert item['discovery_url'] == item['url']
    assert item['summary'] == SUMMARY
    assert item['content'] == SUMMARY
    assert 'body_candidate' not in item
    assert item['content_kind'] == POLICIES[source].content_kind
    assert item['publish_time'] == datetime(2026, 10, 13, 11, 30, tzinfo=timezone.utc)
    assert item['source_modified_at'] == NOW
    assert not item['publish_time_inferred']
    if source == 'arxiv_ai':
        assert item['source_version'] == 'http://arxiv.org/abs/2610.12345v2'
        assert item['category_name'] == 'AI'


@pytest.mark.parametrize('source', SUMMARY_SOURCES)
def test_unreviewed_full_field_cannot_be_authorized_by_length_or_declared_full(source):
    result = validate_candidate(candidate_for(source), expected_url=target_url(source))

    assert not result.ok
    assert result.error_code == 'unsupported'
    assert not result.markdown


@pytest.mark.parametrize('source', SUMMARY_SOURCES)
def test_missing_or_naive_publication_does_not_use_updated_or_current_time(source):
    for published in (None, '2026-10-13T08:30:00', 'invalid'):
        item = item_from_feed(source, published=published)
        assert item['publish_time'] is None
        assert item['publish_time_inferred']
        assert item['source_modified_at'] == NOW
        assert 'body_candidate' not in item


def test_deepmind_entry_without_description_is_still_legal_metadata():
    item = item_from_feed('deepmind', summary='')

    assert item['url'] == target_url('deepmind')
    assert item['summary'] == ''
    assert item['content'] == ''
    assert 'body_candidate' not in item


@pytest.mark.parametrize('source', ['arxiv_ai', 'producthunt'])
@pytest.mark.parametrize('field', ['content:encoded', 'article_html'])
@pytest.mark.django_db
def test_abstract_and_product_cannot_write_full_content_even_when_switches_allow_source(source, field):
    item = item_from_feed(source)
    item['body_candidate'] = candidate_for(source, field=field)
    with override_settings(
        STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS=[source],
        FULL_CONTENT_AUTO_ENQUEUE_ENABLED=True, FULL_CONTENT_AUTO_SOURCE_KEYS=[source],
    ):
        result = ingest_item(item)

    news = News.objects.get(pk=result.news_id)
    assert result.receipt_outcome == 'committed'
    assert result.reason == 'unsupported'
    assert not result.body_committed
    assert news.content_kind == ('abstract' if source == 'arxiv_ai' else 'product')
    assert news.content == SUMMARY
    assert news.full_content == ''
    assert news.full_content_state == 'missing'
    assert news.full_content_fetch_status == 'pending'
    if source == 'arxiv_ai':
        mapping = NewsSourceItem.objects.get(news=news, source_key=source)
        assert mapping.upstream_id == 'http://arxiv.org/abs/2610.12345v2'
        assert mapping.metadata['source_version'] == mapping.upstream_id
        assert mapping.discovery_url == 'https://arxiv.org/abs/2610.12345v2'


def test_newsletter_body_is_bound_to_issue_not_linked_articles():
    external = 'https://webkit.org/blog/17417/external-article/'
    body = '<h2>Issue 663</h2><p>Complete newsletter editorial.</p><ul><li><a href="' + external + '">External article</a></li></ul>'
    item = item_from_feed('frontend_focus', body=body)
    candidate = item['body_candidate']

    result = validate_candidate(candidate, expected_url=item['url'], expected_title=item['title'])
    external_result = validate_candidate(candidate, expected_url=external)
    article_result = validate_candidate(replace(candidate, content_kind='article'), expected_url=item['url'])

    assert result.ok
    assert candidate.body_field == 'content:encoded'
    assert item['content_kind'] == candidate.content_kind == 'newsletter'
    assert item['url'] == 'https://frontendfoc.us/issues/663'
    assert candidate.target_url == item['url']
    assert external in result.markdown
    assert item['summary'] == SUMMARY
    assert not external_result.ok
    assert external_result.error_code == 'body_mismatch'
    assert not article_result.ok
    assert article_result.error_code == 'unsupported'


def test_newsletter_description_cannot_substitute_for_missing_approved_content_field():
    item = item_from_feed('frontend_focus', include_body=False, summary=UNREVIEWED_BODY)

    assert item['content_kind'] == 'newsletter'
    assert item['summary']
    assert 'body_candidate' not in item


@pytest.mark.parametrize('source', ['anthropic', 'meta_ai', 'mistral', 'venturebeat_ai', 'ars_technica_ai', 'mit_tech_review_ai'])
def test_unknown_or_partial_structured_fields_do_not_implicitly_grant_full_body(source):
    candidate = candidate_for(source)
    for field in ('description', 'content:encoded', 'full_content', 'unknown_body'):
        result = validate_candidate(replace(candidate, body_field=field), expected_url=target_url(source))
        assert not result.ok
        assert result.error_code == 'unsupported'


@pytest.mark.parametrize('source', tuple(QUARANTINED))
def test_quarantined_sources_never_request_or_accept_direct_manual_response(source):
    class_name, reason = QUARANTINED[source]
    cls = getattr(import_module(f'news_crawler.spiders.{source}_spider'), class_name)
    crawler = Crawler(cls)
    crawler.stats = MemoryStatsCollector(crawler)
    spider = cls.from_crawler(crawler)
    crawler.signals.send_catch_log(signal=signals.spider_opened, spider=spider)

    assert list(spider.start_urls) == []
    assert list(spider.parse(TextResponse(
        url=target_url(source), body=b'<html><article>Unverified article response</article></html>', encoding='utf-8',
    ))) == []
    assert crawler.stats.get_value('outcome') == 'unsupported'
    assert crawler.stats.get_value('policy_skips_by_reason') == {reason: 1}
    assert POLICIES[source].unsupported_reason == reason
    assert not validate_candidate(candidate_for(source, field='article_html'), expected_url=target_url(source)).ok


@pytest.mark.parametrize('source,module,class_name', FEED_SOURCES)
def test_source_subclass_uses_shared_receipts_and_emits_metadata_without_detail_requests(source, module, class_name):
    cls = getattr(import_module(f'news_crawler.spiders.{module}_spider'), class_name)
    assert issubclass(cls, FeedSpider)
    if source == 'arxiv_ai':
        assert cls.start_urls == [ARXIV_ENDPOINT]
        assert POLICIES[source].feed_url == ARXIV_ENDPOINT
    crawler = Crawler(cls)
    crawler.stats = MemoryStatsCollector(crawler)
    spider = cls.from_crawler(crawler)
    spider.window_days = 365000
    context = FeedRequestState(17, source, feed_url(source), feed_url(source), 5, 'local-policy', (), False)
    response = TextResponse(
        url=feed_url(source), body=local_feed(source), encoding='utf-8',
        request=Request(feed_url(source), meta={'feed_context': context, 'feed_request_started_at': NOW}),
    )

    async def collect():
        return [item async for item in spider.parse(response)]

    items = asyncio.run(collect())

    assert len(items) == 1
    assert not isinstance(items[0], Request)
    item = items[0]
    assert item['url'] == target_url(source)
    assert item['summary'] == SUMMARY
    assert item['content_kind'] == POLICIES[source].content_kind
    assert ('body_candidate' in item) is (source == 'frontend_focus')
    receipt, = spider.feed_receipts.receipts.values()
    assert item['feed_receipt_id'] == receipt.token(0)
    assert receipt.enumerated
    assert receipt.expected_entries == 1
    assert not receipt.can_checkpoint
