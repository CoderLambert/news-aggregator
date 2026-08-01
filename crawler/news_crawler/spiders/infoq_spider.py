import scrapy
from datetime import datetime
import re
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class InfoQSpider(scrapy.Spider):
    """InfoQ news — RSS feed + article scraping."""
    name = 'infoq'
    allowed_domains = ['infoq.com']
    start_urls = ['https://www.infoq.com/feed']

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        # Parse RSS XML
        for item in response.css('item'):
            title = item.css('title::text').get() or ''
            title = title.strip()
            if not title:
                continue

            link = item.css('link::text').get() or ''
            if not link:
                continue

            # Extract clean URL (remove UTM params)
            clean_url = link.split('?')[0] if '?' in link else link

            # Extract description (strip HTML tags)
            description = item.css('description::text').get() or ''
            # Remove HTML tags for content
            plain_text = re.sub(r'<[^>]+>', '', description).strip()
            # Remove author suffix like "By John Doe"
            plain_text = re.sub(r'By\s+[A-Z][a-zA-Z\s]+$', '', plain_text).strip()

            # Extract date
            pub_date_text = item.css('pubDate::text').get() or item.css('dc\\:date::text').get() or ''
            publish_time = datetime.now()
            if pub_date_text:
                for fmt in ('%a, %d %b %Y %H:%M:%S %Z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S'):
                    try:
                        publish_time = datetime.strptime(pub_date_text.strip(), fmt)
                        break
                    except ValueError:
                        continue

            # Extract author
            author = item.css('dc\\:creator::text').get() or ''

            news = NewsItem()
            news['title'] = title
            news['content'] = plain_text
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = 'InfoQ'
            news['category_name'] = classify(title, plain_text)
            news['url'] = clean_url
            news['cover_image'] = ''

            # Extract cover image from description HTML
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description)
            if img_match:
                news['cover_image'] = img_match.group(1)

            yield news

            # Also yield request to fetch full article for richer content
            yield scrapy.Request(clean_url, callback=self.parse_article, priority=1)

    def parse_article(self, response):
        # Extract title from article page
        title = response.css('h1::text').get() or ''
        title = title.strip()
        if not title:
            return

        # Extract main content
        blocks = response.css('article p::text, .content p::text, main p::text').getall()
        if not blocks:
            blocks = response.css('[class*="article"] p::text').getall()

        content = '\n'.join(p.strip() for p in blocks if p.strip())
        if len(content) < 50:
            return

        # Extract author
        author = response.css('[class*="author"]::text, .author::text').get() or ''

        news = NewsItem()
        news['title'] = title
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = datetime.now()
        news['source_name'] = 'InfoQ'
        news['category_name'] = classify(title, content)
        news['url'] = response.url
        news['cover_image'] = response.css('figure img::attr(src), article img::attr(src), .hero img::attr(src)').get() or ''
        yield news
