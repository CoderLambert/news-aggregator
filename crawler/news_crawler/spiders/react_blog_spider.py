import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class ReactBlogSpider(scrapy.Spider):
    name = 'react_blog'
    allowed_domains = ['react.dev']
    start_urls = ['https://react.dev/rss.xml']

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
            if not author:
                author = item.css('author::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')

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
            news['source_name'] = 'React Blog'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = item.css('enclosure::attr(url)').get('') or ''
            yield news

            yield scrapy.Request(url, callback=self.parse_article, priority=1)

    def parse_article(self, response):
        title = response.css('h1::text').get()
        if not title:
            return

        blocks = response.css('article p::text').getall()
        if not blocks:
            blocks = response.css('.mdx p::text').getall()
        if not blocks:
            blocks = response.css('p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        author = response.css('[class*="author"]::text, .author::text').get() or ''

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now()
        news['source_name'] = 'React Blog'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), article img::attr(src)').get() or ''
        yield news
