from datetime import datetime, timezone

import pytest

from api.services.feed_support import parse_feed, feed_entry_item, parse_source_datetime, InvalidFeed
from api.services.article_fetcher.validators import validate_candidate


NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def rss(entries='', *, title='Synthetic publisher'):
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:media="http://search.yahoo.com/mrss/"><channel><title>' + title + '</title>'
            '<link>https://webkit.org/</link><description>Synthetic fixtures</description>' + entries + '</channel></rss>').encode()


def make_item(entry, source='webkit', version='rss20'):
    urls = {'webkit': 'https://webkit.org/feed/', 'v8': 'https://v8.dev/blog.atom'}
    return feed_entry_item(entry, source, feed_url=urls[source], effective_url=urls[source],
                           version=version, request_started_at=NOW)


def test_namespaced_full_field_keeps_guid_separate_from_real_link_and_summary():
    body = rss('<item><title>A short verified article</title><guid isPermaLink="false">publisher-guid</guid>'
               '<link>https://webkit.org/blog/17/short/</link><pubDate>Tue, 13 Oct 2026 08:00:00 +0800</pubDate>'
               '<description>Independent summary</description><content:encoded><![CDATA[<p>The real short article.</p>]]></content:encoded>'
               '<media:content url="https://webkit.org/video.mp4" type="video/mp4"/></item>')
    parsed = parse_feed(body)
    item = make_item(parsed.entries[0])
    assert item['upstream_id'] == 'publisher-guid'
    assert item['summary'] == 'Independent summary'
    assert item['publish_time'] == NOW
    candidate = item['body_candidate']
    assert candidate.body_field == 'content:encoded'
    assert validate_candidate(candidate, expected_url=item['url']).ok


def test_media_content_and_unapproved_description_never_become_body():
    parsed = parse_feed(rss('<item><title>Only a summary</title><link>https://webkit.org/blog/18/summary/</link>'
                            '<description>A long summary.</description><media:content url="https://webkit.org/video.mp4"/></item>'))
    assert 'body_candidate' not in make_item(parsed.entries[0])


def test_atom_text_preserves_type_and_modified_time():
    body = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>V8</title><id>urn:synthetic:v8</id>' \
           b'<updated>2026-10-13T00:00:00Z</updated><entry><title>V8 short note</title><id>urn:post:17</id>' \
           b'<link href="https://v8.dev/blog/short"/><updated>2026-10-13T00:00:00Z</updated>' \
           b'<content type="text">A complete short engine note.</content></entry></feed>'
    parsed = parse_feed(body)
    item = make_item(parsed.entries[0], 'v8', parsed.version)
    assert item['publish_time_inferred']
    assert item['source_modified_at'] == NOW
    assert item['body_candidate'].content_format == 'text'
    assert validate_candidate(item['body_candidate'], expected_url=item['url']).ok


def test_empty_feed_is_distinct_from_html_or_malformed_xml():
    assert parse_feed(rss()).entries == ()
    for data in (b'<html><body>Sign in</body></html>', b'<rss><channel>', b'not XML'):
        with pytest.raises(InvalidFeed):
            parse_feed(data)


def test_parser_enumerates_every_entry_without_top_n_slice():
    items = ''.join(f'<item><title>Entry {i}</title><link>https://webkit.org/blog/{i}/post/</link></item>' for i in range(125))
    assert len(parse_feed(rss(items)).entries) == 125


def test_dates_preserve_timezone_and_do_not_infer_local_naive_publication():
    assert parse_source_datetime('2026-10-13T08:00:00+08:00') == NOW
    assert parse_source_datetime('2026-10-13 08:00:00') is None
    assert parse_source_datetime('invalid') is None
    assert parse_source_datetime('2026-10-13T00:00:00', assume_utc=True) == NOW


def test_feedparser_receives_bytes_never_a_url(monkeypatch):
    from api.services import feed_support
    original = feed_support.feedparser.parse
    calls = []
    def parse(data, **kwargs):
        calls.append(type(data))
        assert kwargs == {'sanitize_html': False}
        return original(data, **kwargs)
    monkeypatch.setattr(feed_support.feedparser, 'parse', parse)
    parse_feed(rss())
    assert calls == [bytes]
