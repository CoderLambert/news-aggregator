"""Reviewed full Feed fields, using local synthetic publisher representations.

URLs and opaque IDs below are explicit fixture inputs, never derived from titles.
The fixtures model each approved RSS/Atom field; they are not live samples or
evidence that production rollout sampling has been completed.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest
from scrapy import Request
from scrapy.http import TextResponse

from api.services.article_identity import InvalidIdentity
from api.services.article_fetcher.types import FullContentCandidate
from api.services.article_fetcher.validators import validate_candidate
from api.services.feed_state import FeedRequestState
from api.services.feed_support import feed_entry_item, parse_feed
from api.services.source_policy import POLICIES
from news_crawler.feed_receipts import FeedReceiptRegistry
from news_crawler.spiders.feed import FeedSpider


NOW = datetime(2026, 10, 13, 2, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 10, 13, 0, 10, tzinfo=timezone.utc)
MODIFIED = datetime(2026, 10, 13, 1, tzinfo=timezone.utc)
SUMMARY = 'An independent publisher summary of this engineering article.'
SHORT_BODY = '<p>A complete short publisher note with one final sentence.</p>'
END_MARKER = 'END-OF-COMPLETE-ARTICLE'
LONG_BODY = (
    '<p>Opening editorial paragraph explaining this complete article.</p>'
    '<h2>Implementation details</h2>'
    '<ul><li>Preserve the first implementation step</li><li>Keep the final step</li></ul>'
    '<p><a href="/documentation">Reference documentation</a></p>'
    '<img src="/images/architecture.png" alt="Architecture diagram"/>'
    '<pre><code>const marker = "keep the complete code";</code></pre>'
    '<table><tr><th>Mode</th><th>Result</th></tr>'
    '<tr><td>Atomic</td><td>Committed</td></tr></table>'
    + '<p>Detailed engineering explanation with the complete measured outcome.</p>' * 90
    + f'<p>{END_MARKER}</p>'
)

SOURCE_CASES = (
    ('webkit', 'content:encoded', 'https://webkit.org/blog/17417/publisher-note/'),
    ('smashing_magazine', 'content:encoded', 'https://www.smashingmagazine.com/2026/10/publisher-note/'),
    ('v8', 'atom:content', 'https://v8.dev/blog/publisher-note'),
    ('mozilla_hacks', 'content:encoded', 'https://hacks.mozilla.org/2026/10/publisher-note/'),
    ('svelte_blog', 'description', 'https://svelte.dev/blog/publisher-note'),
    ('angular_blog', 'content:encoded', 'https://blog.angular.dev/publisher-note-a123'),
)


@pytest.fixture(params=SOURCE_CASES, ids=lambda value: value[0])
def source_case(request):
    return request.param


def local_feed(source_case, bodies=(SHORT_BODY, LONG_BODY), *, publication=True):
    """Return local bytes in the publisher's explicitly approved field."""
    source, field, target = source_case
    policy = POLICIES[source]
    entries = []
    for index, raw_body in enumerate(bodies):
        identity = f'urn:Publisher:{source}:Article:{index}'
        title = 'Same publisher title for two distinct articles'
        link = target + ('' if index == 0 else '?edition=complete')
        if source == 'angular_blog':
            raw_body += '<p class="medium-feed-footer">Publisher footer tracking.</p>'
        if field == 'atom:content':
            published = '<published>2026-10-13T08:10:00+08:00</published>' if publication else ''
            entries.append(
                '<entry><title>' + title + '</title><id>' + identity + '</id>'
                '<link rel="alternate" href="' + escape(link, {'"': '&quot;'}) + '"/>'
                + published + '<updated>2026-10-13T09:00:00+08:00</updated>'
                '<summary type="html">' + SUMMARY + '</summary>'
                '<content type="html"><![CDATA[' + raw_body + ']]></content></entry>'
            )
        else:
            published = '<pubDate>Tue, 13 Oct 2026 08:10:00 +0800</pubDate>' if publication else ''
            body_element = ('<description><![CDATA[' + raw_body + ']]></description>' if field == 'description' else
                            '<description>' + SUMMARY + '</description>'
                            '<content:encoded><![CDATA[' + raw_body + ']]></content:encoded>')
            entries.append(
                '<item><title>' + title + '</title><guid isPermaLink="false">' + identity + '</guid>'
                '<link>' + escape(link) + '</link>' + published +
                '<atom:updated>2026-10-13T09:00:00+08:00</atom:updated>' + body_element +
                '<media:content url="https://media.example.test/video.mp4" type="video/mp4"/>'
                '</item>'
            )
    if field == 'atom:content':
        xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Local publisher fixture</title>'
               '<id>urn:Local:Publisher</id><updated>2026-10-13T09:00:00+08:00</updated>' + ''.join(entries) + '</feed>')
    else:
        xml = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
               'xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">'
               '<channel><title>Local publisher fixture</title><link>' + policy.feed_url + '</link>'
               '<description>Local source contract fixture</description>' + ''.join(entries) + '</channel></rss>')
    return xml.encode('utf-8')


def parsed_items(source_case, bodies=(SHORT_BODY, LONG_BODY), **kwargs):
    parsed = parse_feed(local_feed(source_case, bodies, **kwargs))
    source = source_case[0]
    policy = POLICIES[source]
    return [feed_entry_item(
        entry, source, feed_url=policy.feed_url, effective_url=policy.feed_url,
        request_started_at=NOW, version=parsed.version, request_chain=(policy.feed_url,),
    ) for entry in parsed.entries]


def test_approved_short_and_long_bodies_preserve_publisher_identity_and_aware_dates(source_case):
    source, field, target = source_case
    short, full = parsed_items(source_case)

    assert short['title'] == full['title']
    assert short['url'] == target
    assert full['url'] == target + '?edition=complete'
    assert short['upstream_id'] == f'urn:Publisher:{source}:Article:0'
    assert full['upstream_id'] == f'urn:Publisher:{source}:Article:1'
    for item in (short, full):
        assert item['source_key'] == source
        assert item['source_name'] == POLICIES[source].name
        assert item['discovery_url'] == item['url']
        assert item['publish_time'] == PUBLISHED
        assert item['source_modified_at'] == MODIFIED
        assert not item['publish_time_inferred']
        candidate = item['body_candidate']
        assert isinstance(candidate, FullContentCandidate)
        assert candidate.source_item_id == item['upstream_id']
        assert candidate.source_modified_at == item['source_modified_at']
        assert candidate.body_field == field
        assert candidate.retrieved_from_url == POLICIES[source].feed_url
        assert candidate.target_url == item['url']
        assert candidate.request_started_at == NOW
        result = validate_candidate(candidate, expected_url=item['url'], expected_title=item['title'], summary=item['summary'])
        assert result.ok, result.error_code

    short_result = validate_candidate(short['body_candidate'], expected_url=target)
    assert len(short_result.markdown) < 300  # Reviewed short complete articles are valid.
    full_result = validate_candidate(full['body_candidate'], expected_url=full['url'])
    assert len(full_result.markdown) > 5000
    assert full_result.markdown.endswith(END_MARKER)


def test_full_body_structures_survive_and_summary_never_holds_whole_body(source_case):
    source, field, target = source_case
    _, item = parsed_items(source_case)
    result = validate_candidate(item['body_candidate'], expected_url=item['url'])

    assert result.ok
    assert '## Implementation details' in result.markdown
    assert '- Preserve the first implementation step' in result.markdown
    assert '![Architecture diagram]' in result.markdown
    assert '/images/architecture.png)' in result.markdown
    assert '[Reference documentation]' in result.markdown
    assert '```\nconst marker = "keep the complete code";' in result.markdown
    assert '| Mode | Result |' in result.markdown
    assert '| Atomic | Committed |' in result.markdown
    assert item['content'] == item['summary']
    assert item['summary'] != result.markdown
    assert END_MARKER not in item['summary']
    assert len(item['summary']) <= 500
    if field == 'description':
        assert item['summary'] == 'Opening editorial paragraph explaining this complete article.'
    else:
        assert item['summary'] == SUMMARY
    if source == 'angular_blog':
        assert 'Publisher footer tracking.' not in result.markdown


@pytest.mark.parametrize('bad_body', [
    '<p>Subscribe to read the full article.</p>',
    '<p>Read the rest on the website.</p>',
    '<div class="paywall">Remaining prose behind subscription.</div>',
    '<div data-paywall="true">Restricted prose.</div>',
    '<p class="truncated-preview">Only the opening paragraphs.</p>',
    '<form><input type="password"/></form><p>Protected article text.</p>',
    '<p>Checking your browser before opening the article.</p>',
])
def test_partial_paywall_and_challenge_evidence_is_rejected_per_source(source_case, bad_body):
    # Make the preview long enough that rejecting it cannot depend on length.
    item = parsed_items(source_case, (LONG_BODY + bad_body,))[0]
    result = validate_candidate(item['body_candidate'], expected_url=item['url'], expected_title=item['title'], summary=item['summary'])

    assert not result.ok
    assert result.error_code == 'body_partial'
    assert not result.markdown


def test_declared_partial_is_rejected_even_with_approved_full_body_field(source_case):
    item = parsed_items(source_case, (LONG_BODY,))[0]
    candidate = replace(item['body_candidate'], declared_completeness='partial')

    result = validate_candidate(candidate, expected_url=item['url'])

    assert not result.ok
    assert result.error_code == 'body_partial'


def test_ordinary_subscription_discussion_is_not_a_paywall(source_case):
    body = '<p>We implement subscribe callbacks in this client.</p>' * 20 + '<p>The complete conclusion.</p>'
    item = parsed_items(source_case, (body,))[0]

    result = validate_candidate(item['body_candidate'], expected_url=item['url'])

    assert result.ok
    assert 'The complete conclusion.' in result.markdown


def test_no_publication_date_is_inferred_without_using_modified_as_publication(source_case):
    item = parsed_items(source_case, (SHORT_BODY,), publication=False)[0]

    assert item['publish_time'] is None
    assert item['publish_time_inferred']
    assert item['source_modified_at'] == MODIFIED
    assert item['body_candidate'].source_modified_at == MODIFIED


def test_absent_link_cannot_be_reconstructed_from_title_or_guid(source_case):
    parsed = parse_feed(local_feed(source_case, (SHORT_BODY,)))
    entry = parsed.entries[0]
    entry.pop('link', None)
    entry.pop('links', None)
    source = source_case[0]
    policy = POLICIES[source]

    with pytest.raises(InvalidIdentity):
        feed_entry_item(entry, source, feed_url=policy.feed_url, effective_url=policy.feed_url,
                        request_started_at=NOW, version=parsed.version)


def test_wrong_article_and_unapproved_feed_response_do_not_validate(source_case):
    first, second = parsed_items(source_case)
    candidate = first['body_candidate']

    mismatch = validate_candidate(candidate, expected_url=second['url'])
    unapproved = validate_candidate(replace(candidate, retrieved_from_url='https://unreviewed.example.test/feed'),
                                    expected_url=first['url'])

    assert not mismatch.ok
    assert mismatch.error_code == 'body_mismatch'
    assert not unapproved.ok
    assert unapproved.error_code == 'unsupported'


def test_shared_spider_emits_complete_candidates_and_receipt_without_detail_requests(source_case):
    source = source_case[0]
    policy = POLICIES[source]
    spider = FeedSpider(name=source)
    spider.window_days = 365000  # Fixed local dates must not cause database age-window lookups.
    spider.feed_receipts = FeedReceiptRegistry()
    spider.feed_errors = 0
    spider.feed_outcomes = []
    spider.crawler = SimpleNamespace()
    context = FeedRequestState(17, source, policy.feed_url, policy.feed_url, 5, 'local-policy', (), False)
    response = TextResponse(
        url=policy.feed_url, body=local_feed(source_case), encoding='utf-8',
        headers={'ETag': '"local-fixture"'},
        request=Request(policy.feed_url, meta={'feed_context': context, 'feed_request_started_at': NOW}),
    )

    async def collect():
        return [item async for item in spider.parse(response)]

    items = asyncio.run(collect())

    assert len(items) == 2
    assert all(not isinstance(item, Request) for item in items)
    receipt, = spider.feed_receipts.receipts.values()
    assert receipt.enumerated
    assert receipt.expected_entries == 2
    assert receipt.terminal == {}  # Enumeration alone never proves persistence.
    assert not receipt.can_checkpoint
    for index, item in enumerate(items):
        assert item['feed_receipt_id'] == receipt.token(index)
        assert item['body_candidate'].target_url == item['url']
        assert validate_candidate(item['body_candidate'], expected_url=item['url']).ok
