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
        'USER_AGENT': 'NewsHub/1.0 (+https://github.com/CoderLambert/news-aggregator)',
        'DEFAULT_REQUEST_HEADERS': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        },
        'HTTPERROR_ALLOWED_CODES': [400],
    }

    def parse(self, response):
        if response.status != 200:
            self.crawler.stats.set_value('outcome', 'http_error')
            return
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
            if urlsplit(href).path.rstrip('/') == '/blog':
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
        canonical = response.css('link[rel="canonical"]::attr(href)').get()
        if canonical and not same_article_identity(response.url, response.urljoin(canonical), allow_host_alias=True):
            parse_failure(self)
            return
        title = ''.join(response.css('h1 ::text').getall()).strip()
        if not title:
            title = response.css('[class*="title"]::text').get('')
        if not title:
            parse_failure(self)
            return

        blocks = response.css('article p, .post-content p').xpath('string(.)').getall()
        if not blocks:
            blocks = response.css('.content p, main p').xpath('string(.)').getall()
        if not blocks:
            # The publisher currently wraps the headline and prose in ordinary
            # divs. Scope the preview to the nearest headline ancestor with
            # paragraphs, instead of collecting unrelated footer/navigation text.
            blocks = response.css('h1').xpath('ancestor::*[.//p][1]//p').xpath('string(.)').getall()

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
