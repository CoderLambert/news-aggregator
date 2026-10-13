import scrapy
from api.services.crawl_metrics import parse_failure
from urllib.parse import urlsplit
from api.services.article_identity import normalize_article_url, same_article_identity, InvalidIdentity
from api.services.source_policy import POLICIES
from api.services.source_dates import parse_source_datetime
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
        if not article_links:
            parse_failure(self)
            return
        seen = set()
        for link in article_links:
            href = link.css('a::attr(href)').get('') or link.attrib.get('href', '')
            if not href or '/blog/' not in href:
                continue


            try:
                href = normalize_article_url(response.urljoin(href))
            except InvalidIdentity:
                continue
            if urlsplit(href).hostname not in POLICIES[self.name].domains:
                continue
            if href in seen:
                continue
            if len(seen) >= 20:
                break
            seen.add(href)

            yield scrapy.Request(href, callback=self.parse_article, meta={'discovery_target_url': href})

    def parse_article(self, response):
        if not same_article_identity(response.url, response.meta.get('discovery_target_url', response.request.url), allow_host_alias=True):
            return
        if urlsplit(response.url).hostname not in POLICIES[self.name].domains:
            return
        title = response.css('h1::text').get()
        if not title:
            title = response.css('[class*="title"]::text').get('')
        if not title:
            parse_failure(self)
            return

        blocks = response.css('article p::text, .post-content p::text').getall()
        if not blocks:
            blocks = response.css('.content p::text, main p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            parse_failure(self)
            return

        publish_time = parse_source_datetime(response.css('meta[property="article:published_time"]::attr(content), time[datetime]::attr(datetime)').get())

        author = response.css('[class*="author"]::text, .author::text').get() or ''

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content[:1000]
        news['author'] = author.strip()
        news['publish_time'] = publish_time
        news['source_name'] = 'Meta AI'
        news['category_name'] = classify(title.strip(), content)
        news['source_key'] = self.name
        news['upstream_id'] = normalize_article_url(response.url)
        news['content_kind'] = 'article'
        news['publish_time_inferred'] = publish_time is None
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), article img::attr(src), .hero img::attr(src)').get() or ''
        yield news
