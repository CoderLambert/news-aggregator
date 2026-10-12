from news_crawler.spiders.feed import FeedSpider


class WebkitSpider(FeedSpider):
    name = 'webkit'
    allowed_domains = ['webkit.org']
    start_urls = ['https://webkit.org/feed/']
