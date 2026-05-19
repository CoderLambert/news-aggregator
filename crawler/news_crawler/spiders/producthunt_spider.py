import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class ProductHuntSpider(scrapy.Spider):
    name = 'producthunt'
    allowed_domains = ['producthunt.com']
    start_urls = ['https://www.producthunt.com/feed']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'USER_AGENT': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for entry in response.css('entry'):
            title = entry.css('title::text').get('')
            links = entry.css('link[rel="alternate"]')
            if links:
                url = links.attrib.get('href', '')
            else:
                url = entry.css('link::attr(href)').get('') or ''
            if not title or not url:
                continue

            content_html = entry.css('content::text').get('') or ''
            description = re.sub(r'<[^>]+>', '', content_html).strip()
            description = re.sub(r'\s+', ' ', description).strip()

            author = entry.css('author name::text').get('') or ''
            pub_date = entry.css('published::text').get('')

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.fromisoformat(pub_date.strip().replace('Z', '+00:00')).replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            url = url.strip().strip('"')
            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'ProductHunt'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = ''
            yield news
