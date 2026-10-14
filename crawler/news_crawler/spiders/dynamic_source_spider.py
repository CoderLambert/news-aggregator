"""One declarative spider for approved RSS/Atom, JSON, and HTML sources."""
from datetime import timedelta
from urllib.parse import urlsplit

from django.utils import timezone
from scrapy import Request

from api.services.article_identity import InvalidIdentity
from api.services.article_fetcher.types import FullContentCandidate
from api.services.dynamic_source_parsing import (
    InvalidDynamicPayload, parse_html_list, parse_json_list, structured_entry_item,
)
from api.services.feed_state import prepare_feed_request
from api.services.source_policy import install_runtime_policy, policy_for_key
from news_crawler.feed_receipts import FeedReceipt
from news_crawler.items import NewsItem
from news_crawler.spiders.feed import FeedSpider, _database


class DynamicSourceSpider(FeedSpider):
    name = 'dynamic_source'

    def __init__(self, source_key=None, source_snapshot=None, *args, **kwargs):
        if not source_key or not isinstance(source_snapshot, dict):
            raise ValueError('invalid_source_snapshot')
        if source_snapshot.get('source_key') != source_key or source_snapshot.get('schema_version') != 1:
            raise ValueError('invalid_source_snapshot')
        self.source_snapshot = source_snapshot
        self.endpoint = dict(source_snapshot['endpoint'])
        install_runtime_policy(source_snapshot)
        self.feed_parser_config = self.endpoint.get('parser_config') or {}
        self.start_urls = [self.endpoint['url']]
        self.allowed_domains = list(self.endpoint['allowed_domains'])
        super().__init__(name=source_key, *args, **kwargs)

    async def start(self):
        async for request in super().start():
            request.meta['download_maxsize'] = self.endpoint['max_response_bytes']
            request.meta['dynamic_page'] = 1
            request.meta['dynamic_remaining'] = self.endpoint['max_items']
            yield request

    async def parse(self, response):
        if response.status == 304 and self.endpoint['kind'] not in {'rss', 'atom'}:
            from api.services.feed_state import accept_not_modified
            accepted = await _database(
                accept_not_modified, response.meta['feed_context'], effective_url=response.url,
            )
            self.feed_outcomes.append('unchanged' if accepted else 'parse_failed')
            self.feed_errors += int(not accepted)
            return
        if self.endpoint['kind'] in {'rss', 'atom'}:
            async for item in super().parse(response):
                item['publisher_name'] = self.source_snapshot['policy']['description'].split(' · ', 1)[0]
                item['channel_name'] = self.source_snapshot['policy']['name']
                item['endpoint_kind'] = self.endpoint['kind']
                item['endpoint_url'] = self.endpoint['url']
                yield item
            return

        content_type = response.headers.get('Content-Type', b'').decode('latin1').lower()
        expected = 'json' if self.endpoint['kind'] == 'json' else 'html'
        if expected not in content_type:
            await self._reject_payload(response, 'invalid_content_type')
            return
        try:
            parse_endpoint = {**self.endpoint, 'max_items': response.meta.get(
                'dynamic_remaining', self.endpoint['max_items'],
            )}
            if self.endpoint['kind'] == 'json':
                entries, next_url = parse_json_list(response.body, parse_endpoint)
            else:
                entries, next_url = parse_html_list(response.body, parse_endpoint)
        except InvalidDynamicPayload:
            await self._reject_payload(response, 'parse_failed')
            return

        context = response.meta['feed_context']
        receipt = self.feed_receipts.add(FeedReceipt(
            context, len(entries), response.headers.get('ETag', b'').decode('latin1'),
            response.headers.get('Last-Modified', b'').decode('latin1'), response.url,
        ))
        items = []
        for index, entry in enumerate(entries):
            try:
                item = structured_entry_item(entry, self.name, self.endpoint)
            except (InvalidIdentity, ValueError) as error:
                receipt.settle(index, 'policy_skip', str(error))
                continue
            published = item['publish_time']
            if published and published < timezone.now() - timedelta(days=self.window_days):
                known = await _database(self._known_item, item)
                if not known:
                    receipt.settle(index, 'policy_skip', 'older_window')
                    continue
            item['feed_receipt_id'] = receipt.token(index)
            items.append(NewsItem(item))
        receipt.enumerated = True
        for item in items:
            content_selector = self.endpoint['parser_config'].get('content')
            if self.endpoint['kind'] == 'html' and content_selector and policy_for_key(self.name).html_allowed:
                yield Request(
                    item['url'], callback=self.parse_detail, errback=self.feed_failed,
                    meta={
                        'dynamic_item': item, 'feed_context': context,
                        'feed_request_started_at': response.meta['feed_request_started_at'],
                        'download_maxsize': self.endpoint['max_response_bytes'],
                    },
                )
            else:
                yield item

        page = int(response.meta.get('dynamic_page', 1))
        remaining = max(0, int(response.meta.get('dynamic_remaining', self.endpoint['max_items'])) - len(entries))
        if next_url and remaining and page < self.endpoint['max_pages']:
            context = await _database(prepare_feed_request, self.name, next_url, window_days=self.window_days)
            if not context.next_poll_at or context.next_poll_at <= timezone.now():
                yield Request(
                    context.request_url, headers=dict(context.headers), callback=self.parse,
                    errback=self.feed_failed,
                    meta={
                        'feed_context': context, 'feed_conditional_url': context.request_url,
                        'handle_httpstatus_list': [304], 'feed_request_started_at': timezone.now(),
                        'download_maxsize': self.endpoint['max_response_bytes'], 'dynamic_page': page + 1,
                        'dynamic_remaining': remaining,
                    },
                )

    def parse_detail(self, response):
        from bs4 import BeautifulSoup
        item = response.meta['dynamic_item']
        if 'html' not in response.headers.get('Content-Type', b'').decode('latin1').lower():
            self.feed_receipts.settle(item.get('feed_receipt_id'), 'failed', 'invalid_content_type')
            return
        node = BeautifulSoup(response.body, 'html.parser').select_one(
            self.endpoint['parser_config']['content'],
        )
        if node is None:
            self.feed_receipts.settle(item.get('feed_receipt_id'), 'failed', 'body_empty')
            return
        chain = tuple(dict.fromkeys((item['url'], *response.meta.get('redirect_urls', ()), response.url)))
        item['body_candidate'] = FullContentCandidate(
            self.name, item['upstream_id'], item['url'], response.url, None, item['title'],
            item['content_kind'], 'official_html_selector', 'html', 'full', str(node), None, None,
            response.meta['feed_request_started_at'], request_chain=chain,
        )
        yield item

    async def _reject_payload(self, response, outcome):
        from api.services.feed_state import defer_feed
        await _database(defer_feed, response.meta['feed_context'])
        self.feed_errors += 1
        self.feed_outcomes.append(outcome)
