import scrapy
from datetime import datetime
from news_crawler.items import NewsItem


class SinaSpider(scrapy.Spider):
    name = 'sina'
    allowed_domains = ['sina.com.cn']
    start_urls = [
        'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=50&page=1',
        'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2510&k=&num=50&page=1',
        'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2511&k=&num=50&page=1',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 2,
    }

    def parse(self, response):
        import json
        try:
            data = json.loads(response.text)
            items = data.get('result', {}).get('data', [])
        except (json.JSONDecodeError, AttributeError):
            items = []

        for item in items:
            url = item.get('url', '')
            title = item.get('title', '')
            if not url or not title:
                continue

            category_map = {'2509': '国内', '2510': '国际', '2511': '社会'}
            lid = response.url.split('lid=')[-1].split('&')[0] if 'lid=' in response.url else ''
            category = category_map.get(lid, '国内')

            author = item.get('author', '') or item.get('media_name', '') or ''
            cover_image = item.get('img', {}).get('u', '') if isinstance(item.get('img'), dict) else ''
            ctime = item.get('ctime', '')

            publish_time = datetime.now()
            if ctime:
                try:
                    publish_time = datetime.fromtimestamp(int(ctime))
                except (ValueError, TypeError):
                    pass

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = item.get('intro', '') or item.get('summary', '') or title
            news['author'] = author.strip()
            news['publish_time'] = publish_time
            news['source_name'] = '新浪新闻'
            news['category_name'] = category
            news['url'] = url
            news['cover_image'] = cover_image
            yield news

        # Fetch article detail for full content
        for item in items:
            url = item.get('url', '')
            if url and url.endswith('.shtml'):
                yield scrapy.Request(url, callback=self.parse_article, priority=1)

    def parse_article(self, response):
        title = response.css('h1::text').get() or response.css('.main-title::text').get()
        if not title:
            return

        paragraphs = response.css('#artibody p::text').getall()
        if not paragraphs:
            paragraphs = response.css('.article p::text').getall()
        content = '\n'.join(p.strip() for p in paragraphs if p.strip())
        if not content:
            return

        author = response.css('.author::text').get() or response.css('.media-name::text').get() or ''
        date_str = response.css('.date::text').get() or response.css('.pub_time::text').get() or ''
        cover_image = response.css('.img_wrapper img::attr(src)').get() or ''

        publish_time = datetime.now()
        if date_str:
            for fmt in ('%Y年%m月%d日 %H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
                try:
                    publish_time = datetime.strptime(date_str.strip(), fmt)
                    break
                except ValueError:
                    continue

        category = '国内'
        if 'world' in response.url:
            category = '国际'
        elif 'tech' in response.url or 'digital' in response.url:
            category = '科技'
        elif 'finance' in response.url or 'business' in response.url:
            category = '财经'

        news = NewsItem()
        news['title'] = title.strip()
        news['content'] = content
        news['author'] = author.strip()
        news['publish_time'] = publish_time
        news['source_name'] = '新浪新闻'
        news['category_name'] = category
        news['url'] = response.url
        news['cover_image'] = cover_image
        yield news
