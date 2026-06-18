import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class MistralBlogSpider(scrapy.Spider):
    """Mistral AI blog — HTML scraping (no RSS feed available)."""
    name = 'mistral'
    allowed_domains = ['mistral.ai']
    start_urls = ['https://mistral.ai/news/']

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'USER_AGENT': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    }

    def parse(self, response):
        # Extract article links from the news listing page
        # Links like /news/article-slug/
        article_links = response.css('a[href*="/news/"]')
        seen = set()
        for link in article_links:
            href = link.css('a::attr(href)').get('') or link.attrib.get('href', '')
            if not href:
                continue

            # Skip category/filter URLs and pagination
            if href == '/news/' or '?' in href or '#' in href:
                continue

            if not href.startswith('http'):
                href = 'https://mistral.ai' + href if not href.startswith('/') else 'https://mistral.ai' + href

            if href in seen:
                continue
            seen.add(href)

            yield scrapy.Request(href, callback=self.parse_article)

    def parse_article(self, response):
        title = response.css('h1::text').get()
        if not title:
            title = response.css('[class*="title"] h1::text, [class*="title"]::text').get('')
        if not title:
            return

        # Try multiple selectors for content
        blocks = response.css('article p::text, .prose p::text').getall()
        if not blocks:
            blocks = response.css('.content p::text').getall()
        if not blocks:
            blocks = response.css('main p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        # Try to extract date
        date_text = response.css('time::text, time[datetime]::attr(datetime), [class*="date"]::text').get('')
        publish_time = datetime.now()
        if date_text:
            date_text = date_text.strip()
            for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%B %d, %Y', '%d %B %Y', '%b %d, %Y'):
                try:
                    publish_time = datetime.strptime(date_text, fmt)
                    break
                except ValueError:
                    continue

        author = response.css('[class*="author"]::text, .author::text').get() or ''

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = publish_time
        news['source_name'] = 'Mistral'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), article img::attr(src), .hero img::attr(src)').get() or ''
        yield news
