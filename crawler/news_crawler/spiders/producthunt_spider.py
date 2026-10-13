from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


class ProductHuntSpider(FeedSpider):
    name = 'producthunt'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = [POLICIES[name].feed_url]
