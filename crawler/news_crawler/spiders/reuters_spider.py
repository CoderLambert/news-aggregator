import scrapy
from datetime import datetime
from news_crawler.items import NewsItem


class ReutersSpider(scrapy.Spider):
    name = 'reuters'
    allowed_domains = ['reuters.com']
    start_urls = [
        'https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for item in response.css('item'):
            url = item.css('link::text').get()
            title = item.css('title::text').get()
            if not url or not title:
                continue

            description = item.css('description::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip(), '%a, %d %b %Y %H:%M:%S %Z')
                except ValueError:
                    pass

            category = '国际'
            if 'technology' in url.lower() or 'tech' in title.lower():
                category = '科技'
            elif 'business' in url.lower() or 'finance' in title.lower():
                category = '财经'

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description.strip()
            news['author'] = ''
            news['publish_time'] = publish_time
            news['source_name'] = 'Reuters'
            news['category_name'] = category
            news['url'] = url.strip()
            news['cover_image'] = ''
            yield news
