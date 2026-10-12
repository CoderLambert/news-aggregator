from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


class V8BlogSpider(FeedSpider):
    name = 'v8'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = [POLICIES[name].feed_url]
