import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class SanliuKrSpider(scrapy.Spider):
    """36氪 (36Kr) — Chinese tech/AI news via RSS."""
    name = 'sanliu_kr'
    allowed_domains = ['36kr.com']
    start_urls = ['https://36kr.com/feed']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'USER_AGENT': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
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

            pub_date = item.css('pubDate::text').get('')

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.fromisoformat(pub_date.strip().replace('Z', '+00:00')).replace(tzinfo=None)
                except (ValueError, TypeError):
                    try:
                        publish_time = datetime.strptime(pub_date.strip()[:32], '%a, %d %b %Y %H:%M:%S').replace(tzinfo=None)
                    except (ValueError, TypeError):
                        pass

            url = link.strip()
            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = '36氪'
            news['publish_time'] = publish_time
            news['source_name'] = '36氪'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = item.css('enclosure::attr(url), media\\:content::attr(url)').get('') or ''
            yield news

            # Fetch full article
            yield scrapy.Request(url, callback=self.parse_article, priority=1)

    def parse_article(self, response):
        title = response.css('h1::text').get()
        if not title:
            return

        blocks = response.css('.article-detail p::text, article p::text').getall()
        if not blocks:
            blocks = response.css('.content p::text, main p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = '36氪'
        news['publish_time'] = datetime.now()
        news['source_name'] = '36氪'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('article img::attr(src), .article-detail img::attr(src)').get() or ''
        yield news
