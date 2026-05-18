import scrapy
from datetime import datetime
from news_crawler.items import NewsItem


class BbcSpider(scrapy.Spider):
    name = 'bbc'
    allowed_domains = ['bbc.com', 'bbc.co.uk']
    start_urls = [
        'https://feeds.bbci.co.uk/news/world/rss.xml',
        'https://feeds.bbci.co.uk/news/technology/rss.xml',
        'https://feeds.bbci.co.uk/news/business/rss.xml',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for item in response.css('item'):
            url = item.css('link::text').get()
            title = item.css('title::text').get()
            if not url or not title:
                continue

            category = '国际'
            if 'technology' in response.url:
                category = '科技'
            elif 'business' in response.url:
                category = '财经'

            description = item.css('description::text').get('') or ''
            pub_date = item.css('pubDate::text').get('')

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip(), '%a, %d %b %Y %H:%M:%S %Z')
                except ValueError:
                    pass

            cover_image = ''
            thumbnail = item.css('media\\:thumbnail::attr(url)').get()
            if thumbnail:
                cover_image = thumbnail

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description.strip()
            news['author'] = ''
            news['publish_time'] = publish_time
            news['source_name'] = 'BBC'
            news['category_name'] = category
            news['url'] = url.strip()
            news['cover_image'] = cover_image
            yield news

            # Fetch full article
            yield scrapy.Request(url.strip(), callback=self.parse_article, priority=1)

    def parse_article(self, response):
        title = (
            response.css('h1::text').get()
            or response.css('[data-component="headline"]::text').get()
        )
        if not title:
            return

        blocks = response.css('[data-component="text-block"] p::text').getall()
        if not blocks:
            blocks = response.css('.ssrcss-1q0x1qg-Paragraph p::text').getall()
        if not blocks:
            blocks = response.css('article p::text').getall()
        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if not content:
            return

        author = (
            response.css('[data-component="byline"]::text').get()
            or response.css('.ssrcss-1rv0moy-Contributor::text').get()
            or ''
        )
        cover_image = (
            response.css('[data-component="image"] img::attr(src)').get()
            or response.css('.ssrcss-1drmwog-Image img::attr(src)').get()
            or ''
        )

        category = '国际'
        if 'technology' in response.url:
            category = '科技'
        elif 'business' in response.url:
            category = '财经'

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now()
        news['source_name'] = 'BBC'
        news['category_name'] = category
        news['url'] = response.url
        news['cover_image'] = cover_image
        yield news
