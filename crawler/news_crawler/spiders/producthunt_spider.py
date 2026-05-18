import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem


class ProductHuntSpider(scrapy.Spider):
    name = 'producthunt'
    allowed_domains = ['producthunt.com']
    start_urls = ['https://www.producthunt.com/feed']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for entry in response.css('entry'):
            title = entry.css('title::text').get('')
            url = entry.css('link[rel="alternate"]::attr(href)').get('')
            if not title or not url:
                continue

            content_html = entry.css('content::text').get('') or ''
            # Strip HTML tags
            description = re.sub(r'<[^>]+>', '', content_html).strip()
            # Clean up whitespace
            description = re.sub(r'\s+', ' ', description).strip()

            author = entry.css('author name::text').get('') or ''
            pub_date = entry.css('published::text').get('')

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.fromisoformat(pub_date.strip().replace('Z', '+00:00')).replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            category = '产品'
            title_lower = title.lower()
            desc_lower = description.lower()
            if any(kw in title_lower or kw in desc_lower for kw in ['ai', 'llm', 'gpt', 'agent']):
                category = 'AI'
            elif any(kw in title_lower or kw in desc_lower for kw in ['developer', 'api', 'code', 'open source']):
                category = '开发工具'
            elif any(kw in title_lower or kw in desc_lower for kw in ['saas', 'productivity', 'workflow']):
                category = 'SaaS'

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'ProductHunt'
            news['category_name'] = category
            news['url'] = url.strip()
            news['cover_image'] = ''
            yield news
