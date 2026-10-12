"""Retain source keys without contacting unverified or synthetic endpoints."""
import scrapy
from scrapy import signals


UNSUPPORTED_SOURCES = {
    'reuters': 'authorized_delivery_required',
    'jiqizhixin': 'publisher_identity_unavailable',
    'sanliu_kr': 'invalid_feed_endpoint',
}


class UnsupportedSourceSpider(scrapy.Spider):
    start_urls = []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.record_unsupported, signal=signals.spider_opened)
        return spider

    def record_unsupported(self):
        reason = UNSUPPORTED_SOURCES[self.name]
        self.crawler.stats.set_value('outcome', 'unsupported')
        self.crawler.stats.set_value('policy_skips_by_reason', {reason: 1})
        self.logger.warning('source=%s unsupported reason=%s', self.name, reason)

    def parse(self, response):
        # Also refuse direct/manual calls: enabling a target is not authorization
        # to synthesize an identity from an unverified response.
        return iter(())
