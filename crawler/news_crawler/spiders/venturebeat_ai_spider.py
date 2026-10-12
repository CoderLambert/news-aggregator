import scrapy
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


def parse_venturebeat_publish_time(value, *, fallback=None):
    """Parse RSS RFC 822 dates without silently replacing valid dates with now."""
    fallback = fallback or datetime.now(timezone.utc)
    text = (value or '').strip()
    if not text:
        return fallback
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except (TypeError, ValueError, OverflowError):
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class VenturebeatAiSpider(scrapy.Spider):
    name = 'venturebeat_ai'
    allowed_domains = ['venturebeat.com']
    start_urls = ['https://venturebeat.com/category/ai/feed/']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for item in response.css('item'):
            title = item.css('title::text').get('')
            link = item.css('link::text').get('')
            if not title or not link:
                continue

            description = item.css('description::text').get('') or ''
            description = re.sub(r'<[^>]+>', '', description).strip()

            author = item.css('creator::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')
            cover_image = item.css('enclosure::attr(url)').get('') or ''

            publish_time = parse_venturebeat_publish_time(pub_date)

            url = link.strip()
            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'VentureBeat AI'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = cover_image
            yield news

            # Fetch full article
            yield scrapy.Request(url, callback=self.parse_article, priority=1)

    def parse_article(self, response):
        title = response.css('h1::text').get()
        if not title:
            return

        blocks = response.css('.entry-content p::text').getall()
        if not blocks:
            blocks = response.css('article p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        author = response.css('.entry-author-name::text, .author-name::text').get() or ''

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now(timezone.utc)
        news['source_name'] = 'VentureBeat AI'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), .entry-content img::attr(src)').get() or ''
        yield news
