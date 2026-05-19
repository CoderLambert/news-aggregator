import scrapy
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


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
        for item in response.xpath('//item'):
            url = item.xpath('link/text()').get()
            title = item.xpath('title/text()').get()
            if not url or not title:
                continue

            description = item.xpath('description/text()').get('') or ''
            pub_date = item.xpath('pubDate/text()').get()

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip(), '%a, %d %b %Y %H:%M:%S %Z')
                except ValueError:
                    pass

            cover_image = item.xpath('media:thumbnail/@url').get() or ''

            url = url.strip()
            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = description.strip()
            news['author'] = ''
            news['publish_time'] = publish_time
            news['source_name'] = 'BBC'
            news['category_name'] = classify(title.strip(), description)
            news['url'] = url
            news['cover_image'] = cover_image
            yield news

            # Fetch full article
            yield scrapy.Request(url, callback=self.parse_article, priority=1)

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

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now()
        news['source_name'] = 'BBC'
        news['category_name'] = classify(title.strip(), content)
        news['url'] = response.url
        news['cover_image'] = cover_image
        yield news
