import scrapy
import json
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class JiqizhixinSpider(scrapy.Spider):
    """机器之心 (Synced / jiqizhixin) — Chinese AI news via API."""
    name = 'jiqizhixin'
    allowed_domains = ['jiqizhixin.com']
    start_urls = ['https://www.jiqizhixin.com/api/v1/articles?page=1&limit=20']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'USER_AGENT': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }

    def parse(self, response):
        try:
            articles = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            return

        for article in articles:
            title = article.get('title', '')
            description = article.get('description', '') or ''
            cover_image = article.get('cover_image', '') or ''
            author_info = article.get('author', {})
            author = author_info.get('author_name', '') if isinstance(author_info, dict) else ''

            if not title:
                continue

            # Build article URL from title slug
            slug = title.lower().replace(' ', '-')[:80]
            url = f'https://www.jiqizhixin.com/articles/{slug}'

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip() if author else '机器之心'
            news['publish_time'] = datetime.now()
            news['source_name'] = '机器之心'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = cover_image
            yield news
