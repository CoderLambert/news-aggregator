import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class OpenaiBlogSpider(scrapy.Spider):
    name = 'openai_blog'
    allowed_domains = ['openai.com']
    start_urls = ['https://openai.com/news/rss.xml']
    max_items = 50

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for item in response.css('item')[:self.max_items]:
            title = item.css('title::text').get('')
            link = item.css('link::text').get('')
            if not title or not link:
                continue

            description = item.css('description::text').get('') or ''
            description = re.sub(r'<[^>]+>', '', description).strip()

            author = item.css('creator::text').get('') or ''
            if not author:
                author = item.css('author::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')
            cover_image = item.css('enclosure::attr(url)').get('') or ''

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip()[:32], '%a, %d %b %Y %H:%M:%S').replace(tzinfo=None)
                except ValueError:
                    try:
                        publish_time = datetime.fromisoformat(pub_date.strip().replace('Z', '+00:00')).replace(tzinfo=None)
                    except (ValueError, TypeError):
                        pass

            url = link.strip()
            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'OpenAI Blog'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = cover_image
            yield news
