"""Shared RSS/Atom lifecycle with commit-after-Pipeline conditional state."""
import asyncio
from datetime import timedelta, datetime, timezone as utc_timezone

from asgiref.sync import sync_to_async
from scrapy import Request, Spider, signals

from news_crawler.django_support import initialize_django
initialize_django()

from django.utils import timezone
from api.models import News, NewsSourceItem
from api.services.article_identity import InvalidIdentity
from api.services.feed_state import prepare_feed_request, accept_not_modified, defer_feed
from api.services.feed_support import parse_feed, feed_entry_item, InvalidFeed
from api.services.source_policy import POLICIES
from news_crawler.category_map import classify
from news_crawler.feed_receipts import FeedReceipt, FeedReceiptRegistry
from news_crawler.items import NewsItem


async def _database(function, *args, **kwargs):
    return await sync_to_async(function, thread_sensitive=True)(*args, **kwargs)


class FeedSpider(Spider):
    window_days = 30

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.feed_receipts = FeedReceiptRegistry()
        spider.feed_outcomes = []
        spider.feed_errors = 0
        crawler.signals.connect(spider._feed_closed, signal=signals.spider_closed)
        crawler.signals.connect(spider._item_error, signal=signals.item_error)
        crawler.signals.connect(spider._item_dropped, signal=signals.item_dropped)
        crawler.signals.connect(spider._item_scraped, signal=signals.item_scraped)
        return spider

    async def start(self):
        urls = self.start_urls or [POLICIES[self.name].feed_url]
        for url in urls:
            context = await _database(prepare_feed_request, self.name, url, window_days=self.window_days)
            if context.next_poll_at and context.next_poll_at > timezone.now():
                self.feed_outcomes.append('deferred')
                self.crawler.stats.set_value('next_attempt_at', context.next_poll_at.isoformat())
                continue
            yield Request(context.request_url, headers=dict(context.headers), callback=self.parse,
                          errback=self.feed_failed, meta={'feed_context': context,
                          'feed_conditional_url': context.request_url, 'handle_httpstatus_list': [304],
                          'feed_request_started_at': timezone.now(), 'download_maxsize': 8 * 1024 * 1024})

    async def parse(self, response):
        context = response.meta['feed_context']
        if response.status == 304:
            accepted = await _database(accept_not_modified, context, effective_url=response.url)
            self.feed_outcomes.append('unchanged' if accepted else 'parse_failed')
            if not accepted:
                self.feed_errors += 1
            return
        try:
            parsed = parse_feed(response.body)
        except InvalidFeed:
            self.feed_errors += 1
            self.feed_outcomes.append('parse_failed')
            await _database(defer_feed, context)
            return
        receipt = self.feed_receipts.add(FeedReceipt(
            context, len(parsed.entries), response.headers.get('ETag', b'').decode('latin1'),
            response.headers.get('Last-Modified', b'').decode('latin1'), response.url,
        ))
        # Build every entry before yielding. Capacity limits must not truncate the
        # representation whose ETag is about to be acknowledged.
        chain = tuple(dict.fromkeys((context.feed_url, *response.meta.get('redirect_urls', ()), response.url)))
        items = []
        for index, entry in enumerate(parsed.entries):
            try:
                item = feed_entry_item(entry, self.name, feed_url=context.feed_url,
                                       effective_url=response.url, version=parsed.version,
                                       request_started_at=response.meta['feed_request_started_at'],
                                       request_chain=chain, classify=classify)
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
            yield item

    def _known_item(self, item):
        return (NewsSourceItem.objects.filter(source_key=self.name, upstream_id=item['upstream_id']).exists() or
                News.objects.filter(url=item['url']).exists())

    async def feed_failed(self, failure):
        context = failure.request.meta.get('feed_context')
        error = failure.value
        code = getattr(error, 'error_code', '')
        status = getattr(error, 'http_status', None)
        if status is None and getattr(error, 'response', None) is not None:
            status = error.response.status
        outcome = ('rate_limited' if code == 'rate_limited' or status == 429 else
                   'deferred' if code == 'budget_deferred' else 'blocked' if status in {401, 403} else 'parse_failed')
        retry_at = getattr(error, 'retry_after_at', None)
        if outcome == 'blocked':
            retry_at = datetime.max.replace(tzinfo=utc_timezone.utc)
        if context:
            await _database(defer_feed, context, next_poll_at=retry_at)
        self.feed_outcomes.append(outcome)
        self.feed_errors += int(outcome == 'parse_failed')
        if retry_at:
            self.crawler.stats.set_value('next_attempt_at', retry_at.isoformat())

    def _item_error(self, item, **kwargs):
        self.feed_receipts.settle(item.get('feed_receipt_id'), 'failed', 'pipeline_error')

    def _item_dropped(self, item, exception, **kwargs):
        result = getattr(exception, 'ingest_result', None)
        self.feed_receipts.settle(item.get('feed_receipt_id'), result.receipt_outcome if result else 'failed',
                                  result.reason if result else 'unclassified_drop')

    def _item_scraped(self, item, **kwargs):
        # An explicit deferred result stays deferred. Unsettled success is a
        # broken Pipeline contract, never proof of a database commit.
        self.feed_receipts.settle(item.get('feed_receipt_id'), 'failed', 'unsettled_item')

    async def _feed_closed(self, reason):
        tasks = tuple(self.feed_receipts.active_pipeline_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        totals = await _database(self.feed_receipts.finish, reason)
        totals['parse_failures'] += self.feed_errors
        all_outcomes = [totals['outcome'], *self.feed_outcomes]
        for priority in ('partial', 'parse_failed', 'blocked', 'rate_limited', 'deferred', 'updated', 'unchanged', 'valid_empty'):
            if priority in all_outcomes and (self.feed_receipts.receipts or priority != 'deferred' or not self.feed_outcomes):
                totals['outcome'] = priority
                break
        if not self.feed_receipts.receipts and self.feed_outcomes:
            totals['outcome'] = next((o for o in ('parse_failed', 'blocked', 'rate_limited', 'deferred', 'unchanged') if o in self.feed_outcomes), 'deferred')
        if any(o in {'partial', 'parse_failed', 'blocked', 'rate_limited', 'deferred'} for o in self.feed_outcomes):
            totals['checkpoint_committed'] = False
        elif not self.feed_receipts.receipts and self.feed_outcomes and all(o == 'unchanged' for o in self.feed_outcomes):
            totals['checkpoint_committed'] = True
        for key, value in totals.items():
            self.crawler.stats.set_value(key, value)
