import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


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
            description = re.sub(r'<[^>]+>', '', description).strip()

            # dc namespace: use CSS selector
            author = item.css('creator::text').get('') or ''
            if not author:
                author = item.css('author::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')
            cover_image = item.css('enclosure::attr(url)').get('') or ''

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip(), '%a, %d %b %Y %H:%M:%S %z').replace(tzinfo=None)
                except ValueError:
                    try:
                        publish_time = datetime.strptime(pub_date.strip()[:25], '%a, %d %b %Y %H:%M:%S')
                    except ValueError:
                        pass

            url = url.strip()
            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'TechCrunch'
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
            blocks = response.css('.wp-block-post-content p::text').getall()
        if not blocks:
            blocks = response.css('article p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        author = (
            response.css('.author-name::text').get()
            or response.css('.entry-author a::text').get()
            or response.css('[class*="author"] a::text').get()
            or ''
        )

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now()
        news['source_name'] = 'TechCrunch'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), .post-content img::attr(src)').get() or ''
        yield news
