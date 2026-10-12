import json
from datetime import timedelta

import scrapy
from asgiref.sync import sync_to_async
from news_crawler.django_support import initialize_django
initialize_django()
from django.conf import settings
from django.utils import timezone
from api.models import News
from api.services.article_identity import InvalidIdentity
from api.services.news_ingestion import ingest_item
from api.services.full_content_status import has_full_content
from api.services.structured_articles import dev_article_item, dev_candidate
from api.services.feed_support import parse_source_datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class DevToSpider(scrapy.Spider):
    name = 'devto'
    allowed_domains = ['dev.to']
    custom_settings = {'DOWNLOAD_DELAY': 1, 'CONCURRENT_REQUESTS_PER_DOMAIN': 3}
    start_urls = [
        'https://dev.to/api/articles?top=50',
        'https://dev.to/api/articles?per_page=50&tag=python',
        'https://dev.to/api/articles?per_page=50&tag=javascript',
        'https://dev.to/api/articles?per_page=50&tag=webdev',
        'https://dev.to/api/articles?per_page=50&tag=css',
        'https://dev.to/api/articles?per_page=50&tag=typescript',
        'https://dev.to/api/articles?per_page=50&tag=react',
    ]


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_ids = set()
        self.details_started = 0

    async def parse(self, response):
        try:
            articles = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            self.crawler.stats.inc_value('parse_failures')
            return
        if not isinstance(articles, list):
            self.crawler.stats.inc_value('parse_failures')
            return
        for article in articles:
            try:
                item = dev_article_item(article, classify=classify)
            except (InvalidIdentity, ValueError, TypeError):
                self.crawler.stats.inc_value('policy_skips/invalid_identity')
                continue
            identity = item['upstream_id']
            if identity in self.seen_ids:
                continue
            self.seen_ids.add(identity)
            # Persist discovery before the optional HTTP request. A failed detail
            # must never erase a legitimate discovered article or durable intent.
            result = await sync_to_async(ingest_item, thread_sensitive=True)(item)
            if result.receipt_outcome != 'committed':
                self.crawler.stats.inc_value('persistence_failures')
                continue
            yield NewsItem(item)
            if not (getattr(settings, 'STRUCTURED_BODY_INGEST_ENABLED', False) and
                    self.name in getattr(settings, 'STRUCTURED_BODY_SOURCE_KEYS', ())):
                continue
            published = item['publish_time']
            if not published or published < timezone.now() - timedelta(days=7):
                continue
            news = await sync_to_async(News.objects.get, thread_sensitive=True)(pk=result.news_id)
            known_modified = parse_source_datetime(news.full_content_provenance.get('source_modified_at'))
            modified = item.get('source_modified_at')
            if has_full_content(news) and not (modified and known_modified and modified > known_modified):
                continue
            if self.details_started >= 20:
                self.crawler.stats.inc_value('details_deferred')
                continue
            self.details_started += 1
            yield scrapy.Request(
                f'https://dev.to/api/articles/{identity}', callback=self.parse_article,
                errback=self.detail_failed, priority=1,
                meta={'discovered_item': item, 'expected_revision': news.full_content_revision,
                      'expected_url': news.url, 'detail_started_at': timezone.now(),
                      'handle_httpstatus_list': [401, 403, 404, 429, 503]},
            )

    def parse_article(self, response):
        item = dict(response.meta['discovered_item'])
        if response.status != 200:
            self.crawler.stats.inc_value('details_failed')
            yield NewsItem(item)
            return
        try:
            payload = json.loads(response.text)
            candidate = dev_candidate(payload, target_url=response.meta['expected_url'],
                source_item_id=item['upstream_id'], retrieved_from_url=response.url,
                request_started_at=response.meta['detail_started_at'],
                expected_revision=response.meta['expected_revision'])
            item.update(dev_article_item(payload, classify=classify))
            item['body_candidate'] = candidate
        except (InvalidIdentity, ValueError, TypeError):
            self.crawler.stats.inc_value('details_failed')
        yield NewsItem(item)

    def detail_failed(self, failure):
        self.crawler.stats.inc_value('details_failed')
        yield NewsItem(failure.request.meta['discovered_item'])
