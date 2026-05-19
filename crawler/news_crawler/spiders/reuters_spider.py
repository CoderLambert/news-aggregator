import scrapy
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class ReutersSpider(scrapy.Spider):
    name = 'reuters'
    allowed_domains = ['google.com', 'reuters.com']
    start_urls = [
        'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=World',
        'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=Technology',
        'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en&topic=Business',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 1,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for item in response.xpath('//item'):
            title = item.xpath('title/text()').get('')
            # Title format from Google News: "Title - Source"
            if 'Reuters' not in title:
                continue

            # Extract just the title without source suffix
            if ' - Reuters' in title:
                title = title.rsplit(' - Reuters', 1)[0].strip()
            elif ' - ' in title:
                title = title.rsplit(' - ', 1)[0].strip()

            link = item.xpath('link/text()').get('')
            description = item.xpath('description/text()').get('') or ''
            pub_date = item.xpath('pubDate/text()').get()

            # Strip HTML from description
            import re
            description = re.sub(r'<[^>]+>', '', description).strip()

            publish_time = datetime.now()
            if pub_date:
                try:
                    publish_time = datetime.strptime(pub_date.strip(), '%a, %d %b %Y %H:%M:%S %Z')
                except ValueError:
                    pass

            # Generate a stable URL from title for dedup
            # Google News RSS links are not followable, so use a hash-based URL
            url_hash = re.sub(r'[^a-z0-9]+', '-', title.lower())[:80]
            url = f'https://www.reuters.com/search/news?query={url_hash}'

            category = self._categorize(response.url)

            news = NewsItem()
            news['title'] = title
            news['content'] = description
            news['author'] = 'Reuters'
            news['publish_time'] = publish_time
            news['source_name'] = 'Reuters'
            news['category_name'] = category
            news['url'] = url
            news['cover_image'] = ''
            yield news

    def _categorize(self, feed_url):
        if 'Technology' in feed_url:
            return '科技'
        elif 'Business' in feed_url:
            return '财经'
        return '国际'
