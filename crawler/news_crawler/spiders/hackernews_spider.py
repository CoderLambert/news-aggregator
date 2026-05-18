import scrapy
import json
from datetime import datetime
from news_crawler.items import NewsItem

HN_API = 'https://hacker-news.firebaseio.com/v0'


class HackerNewsSpider(scrapy.Spider):
    name = 'hackernews'
    allowed_domains = ['hacker-news.firebaseio.com', 'news.ycombinator.com']
    start_urls = [f'{HN_API}/topstories.json']

    custom_settings = {
        'DOWNLOAD_DELAY': 0.5,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 5,
    }

    def parse(self, response):
        ids = json.loads(response.text)[:80]
        for item_id in ids:
            yield scrapy.Request(
                f'{HN_API}/item/{item_id}.json',
                callback=self.parse_item,
            )

    def parse_item(self, response):
        data = json.loads(response.text)
        if not data or data.get('type') != 'story' or data.get('deleted') or data.get('dead'):
            return

        title = data.get('title', '')
        url = data.get('url', '')
        if not title:
            return

        # If no external URL, link to HN comments page
        if not url:
            url = f"https://news.ycombinator.com/item?id={data['id']}"

        content = data.get('text', '')
        if not content:
            content = f"HN Score: {data.get('score', 0)} | Comments: {data.get('descendants', 0)}"

        author = data.get('by', '')
        publish_time = datetime.fromtimestamp(data.get('time', 0))

        category = '科技'
        title_lower = title.lower()
        if any(kw in title_lower for kw in ['show hn', 'launch', 'startup', 'fundraising']):
            category = '创业'
        elif any(kw in title_lower for kw in ['hire', 'job', 'hiring']):
            category = '招聘'
        elif any(kw in title_lower for kw in ['ask hn']):
            category = '问答'

        news = NewsItem()
        news['title'] = title
        news['content'] = content
        news['author'] = author
        news['publish_time'] = publish_time
        news['source_name'] = 'Hacker News'
        news['category_name'] = category
        news['url'] = url
        news['cover_image'] = ''
        yield news
