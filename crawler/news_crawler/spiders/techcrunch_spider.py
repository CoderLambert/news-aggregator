import scrapy
from datetime import datetime
from news_crawler.items import NewsItem


class TechCrunchSpider(scrapy.Spider):
    name = 'techcrunch'
    allowed_domains = ['techcrunch.com']
    start_urls = [
        'https://techcrunch.com/feed/',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for item in response.css('item'):
            title = item.css('title::text').get('')
            url = item.css('link::text').get('')
            if not title or not url:
                continue

            description = item.css('description::text').get('') or ''
            # Strip HTML tags from description
            import re
            description = re.sub(r'<[^>]+>', '', description).strip()

            author = item.css('dc\\:creator::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')
            cover_image = ''
            enclosure = item.css('enclosure::attr(url)').get()
            if enclosure:
                cover_image = enclosure

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip(), '%a, %d %b %Y %H:%M:%S %z').replace(tzinfo=None)
                except ValueError:
                    try:
                        publish_time = datetime.strptime(pub_date.strip()[:25], '%a, %d %b %Y %H:%M:%S')
                    except ValueError:
                        pass

            categories_raw = item.css('category::text').getall()
            category = '科技'
            if categories_raw:
                cats_lower = [c.lower() for c in categories_raw]
                if any(c in cats_lower for c in ['ai', 'artificial intelligence', 'machine learning']):
                    category = 'AI'
                elif any(c in cats_lower for c in ['startups', 'venture', 'funding']):
                    category = '创业'
                elif any(c in cats_lower for c in ['security', 'privacy']):
                    category = '安全'
                elif any(c in cats_lower for c in ['crypto', 'blockchain', 'web3']):
                    category = '区块链'
                elif any(c in cats_lower for c in ['apps', 'mobile', 'gadgets']):
                    category = '产品'

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'TechCrunch'
            news['category_name'] = category
            news['url'] = url.strip()
            news['cover_image'] = cover_image
            yield news
