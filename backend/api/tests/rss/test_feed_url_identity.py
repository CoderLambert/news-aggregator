"""Feed replay identity over the real adapter, with a synthetic SDK boundary."""
from unittest import TestCase
from unittest.mock import Mock

import requests

from api.rss.engine import EngineAdapter, EngineConfig, EngineError, _url
from api.rss.feed_policy import required_entry_url_block_rules


class FeedURLIdentityTests(TestCase):
    def setUp(self):
        self.adapter = EngineAdapter(EngineConfig(
            'be22a55a-11c1-4ae4-9038-c919ec75aa42', 3,
            'http://127.0.0.1:1', 'synthetic-feed-identity-key'))
        self.addCleanup(self.adapter.close)
        self.client = self.adapter._client = Mock()
        self.client.me.return_value = {'id': 3, 'is_admin': False}

    def feed(self, url):
        return {'id': 7, 'user_id': 3, 'feed_url': url, 'title': 'Synthetic feed',
                'crawler': False, 'disabled': False, 'blocklist_rules': '',
                'keeplist_rules': '', 'block_filter_entry_rules': required_entry_url_block_rules()}

    def test_returned_feed_uses_the_same_canonical_identity_as_input(self):
        row = self.feed('https://PUBLISHER.EXAMPLE.:443/Feed?tag=AI%20News#section')
        self.assertEqual(self.adapter._feed(row).feed_url,
                         'https://publisher.example/Feed?tag=AI%20News')
        self.assertEqual(_url('https://例子.测试./Feed'),
                         'https://xn--fsqu00a.xn--0zwm56d/Feed')
        self.assertEqual(_url('https://PUBLISHER.EXAMPLE。:443/Feed'),
                         'https://publisher.example/Feed')

    def test_equivalent_existing_feed_is_reused_without_a_create(self):
        row = self.feed('https://PUBLISHER.EXAMPLE:443/Feed?tag=AI#section')
        self.client.get_feeds.return_value = [row]
        self.client.get_feed.return_value = row
        self.assertEqual(self.adapter.create_feed('https://publisher.example/Feed?tag=AI').id, 7)
        self.client.create_feed.assert_not_called()

    def test_unknown_create_reconciles_equivalent_url_without_second_create(self):
        row = self.feed('https://PUBLISHER.EXAMPLE:443/Feed#section')
        self.client.get_feeds.side_effect = [[], [row]]
        self.client.create_feed.side_effect = requests.ConnectionError()
        self.client.get_feed.return_value = row
        self.assertEqual(self.adapter.create_feed('https://publisher.example/Feed').id, 7)
        self.client.create_feed.assert_called_once()

    def test_business_path_query_and_nondefault_port_are_distinct(self):
        base = 'https://publisher.example/Feed?tag=AI'
        for other in ['https://publisher.example/feed?tag=AI',
                      'https://publisher.example/Feed?tag=ai',
                      'https://publisher.example/Feed/?tag=AI',
                      'https://publisher.example:8443/Feed?tag=AI']:
            with self.subTest(other=other):
                self.assertNotEqual(_url(base), _url(other))

    def test_article_urls_are_preserved_instead_of_feed_normalized(self):
        value = 'https://PUBLISHER.EXAMPLE:443/Article?x=A#section'
        self.assertEqual(_url(value, feed=False), value)

    def test_unsafe_feed_inputs_still_fail_before_sdk_dispatch(self):
        for value in ['http://publisher.example/feed', 'https://127.0.0.1/feed',
                      'https://user:password@publisher.example/feed',
                      'https://publisher.internal/feed', 'https://publisher.ｌｏｃａｌ/feed',
                      'https://publisher.local。/feed', 'https://１２７.０.０.１/feed',
                      'https://publisher.example/\nfeed']:
            with self.subTest(value=value), self.assertRaises(EngineError):
                self.adapter.create_feed(value)
        self.client.create_feed.assert_not_called()
