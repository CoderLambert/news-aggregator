import scrapy
import json
from datetime import datetime, timezone
from django.utils.timezone import now
from api.services.article_identity import normalize_article_url, InvalidIdentity
from api.services.structured_articles import hn_candidate
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


HN_API = 'https://hacker-news.firebaseio.com/v0'


class HackerNewsSpider(scrapy.Spider):
    name = 'hackernews'
    allowed_domains = ['hacker-news.firebaseio.com', 'news.ycombinator.com']
    start_urls = [f'{HN_API}/topstories.json']

    custom_settings = {
        'DOWNLOAD_DELAY': 0.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 5,
    }

    def parse(self, response):
        ids = json.loads(response.text)[:80]
        for item_id in ids:
            if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                continue
            yield scrapy.Request(
                f'{HN_API}/item/{item_id}.json',
                callback=self.parse_item,
                meta={'hn_id': str(item_id), 'request_started_at': now()},
            )

    def parse_item(self, response):
        data = json.loads(response.text)
        if (not data or data.get('type') != 'story' or data.get('deleted') or data.get('dead') or
                str(data.get('id')) != response.meta['hn_id']):
            return

        title = data.get('title', '')
        url = data.get('url', '')
        if not title:
            return

        if not url:
            url = f"https://news.ycombinator.com/item?id={data['id']}"

        try:
            url = normalize_article_url(url)
        except InvalidIdentity:
            return
        content = ''

        author = data.get('by', '')
        stamp = data.get('time')
        try:
            publish_time = datetime.fromtimestamp(stamp, timezone.utc) if stamp else None
        except (TypeError, ValueError, OverflowError):
            publish_time = None

        news = NewsItem()
        news['title'] = title
        news['content'] = content
        news['author'] = author
        news['publish_time'] = publish_time
        news['source_name'] = 'Hacker News'
        news['category_name'] = classify(title, content)
        news['url'] = url
        news['cover_image'] = ''
        news['source_key'] = 'hackernews'
        news['upstream_id'] = str(data['id'])
        news['discovery_url'] = f"https://news.ycombinator.com/item?id={data['id']}"
        news['content_kind'] = 'article' if data.get('url') else 'discussion'
        news['publish_time_inferred'] = publish_time is None
        if not data.get('url') and data.get('text'):
            news['body_candidate'] = hn_candidate(data, target_url=url, retrieved_from_url=response.url,
                request_started_at=response.meta['request_started_at'], source_item_id=response.meta['hn_id'])
        yield news
