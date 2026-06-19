import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class V8BlogSpider(scrapy.Spider):
    """V8 JavaScript engine blog — Atom feed format."""
    name = 'v8'
    allowed_domains = ['v8.dev']
    start_urls = ['https://v8.dev/blog.atom']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
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

            # Try summary first, then content
            description = entry.css('summary::text').get('') or ''
            if not description:
                content_html = entry.css('content::text').get('') or ''
                description = re.sub(r'<[^>]+>', '', content_html).strip()
            description = re.sub(r'\s+', ' ', description).strip()

            author = entry.css('author name::text').get('') or ''
            pub_date = entry.css('published::text').get('') or entry.css('updated::text').get('')

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
            news['source_name'] = 'V8'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = ''
            yield news

            yield scrapy.Request(url, callback=self.parse_article, priority=1)

    def parse_article(self, response):
        title = response.css('h1::text').get()
        if not title:
            return

        blocks = response.css('article p::text').getall()
        if not blocks:
            blocks = response.css('.content p::text').getall()
        if not blocks:
            blocks = response.css('.post-content p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        author = response.css('[class*="author"]::text, .author::text').get() or ''

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now()
        news['source_name'] = 'V8'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), article img::attr(src)').get() or ''
        yield news
