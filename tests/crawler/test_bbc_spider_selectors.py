from pathlib import Path

from django.utils import timezone
from api.services.feed_support import parse_feed, feed_entry_item
from api.services.source_policy import POLICIES


def test_bbc_preserves_media_thumbnail_in_shared_namespaced_parser():
    fixture = Path(__file__).parent / 'fixtures' / 'bbc_rss_namespaced.xml'
    parsed = parse_feed(fixture.read_bytes())
    news_item = feed_entry_item(parsed.entries[0], 'bbc', feed_url=POLICIES['bbc'].feed_url,
        effective_url=POLICIES['bbc'].feed_url, version=parsed.version, request_started_at=timezone.now())

    assert news_item['title'] == 'Synthetic fixture title'
    assert news_item['cover_image'] == 'https://images.example.invalid/fixture-thumbnail.png'
