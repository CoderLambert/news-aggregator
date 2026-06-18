import scrapy
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class MetaAiBlogSpider(scrapy.Spider):
    """Meta AI blog — HTML scraping (RSS feed not accessible)."""
    name = 'meta_ai'
    allowed_domains = ['ai.meta.com']
    start_urls = ['https://ai.meta.com/blog/']

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'USER_AGENT': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Cookie': '_js=1',
            'Sec-Ch-Ua': '"Chromium";v="131", "Google Chrome";v="131"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
        },
        'HTTPERROR_ALLOWED_CODES': [400],
    }

    def parse(self, response):
        # Extract article links from the blog listing page
        article_links = response.css('a[href*="/blog/"]')
        seen = set()
        for link in article_links:
            href = link.css('a::attr(href)').get('') or link.attrib.get('href', '')
            if not href or '/blog/' not in href:
                continue

            if not href.startswith('http'):
                href = 'https://ai.meta.com' + href if not href.startswith('/') else 'https://ai.meta.com' + href

            if href in seen:
                continue
            seen.add(href)

            yield scrapy.Request(href, callback=self.parse_article)

    def parse_article(self, response):
        title = response.css('h1::text').get()
        if not title:
            title = response.css('[class*="title"]::text').get('')
        if not title:
            return

        blocks = response.css('article p::text, .post-content p::text').getall()
        if not blocks:
            blocks = response.css('.content p::text, main p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        date_text = response.css('time::text, [class*="date"]::text, [class*="published"]::text').get('')
        publish_time = datetime.now()
        if date_text:
            date_text = date_text.strip()
            for fmt in ('%Y-%m-%d', '%B %d, %Y', '%d %B %Y', '%b %d, %Y'):
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
        news['source_name'] = 'Meta AI'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), article img::attr(src), .hero img::attr(src)').get() or ''
        yield news
