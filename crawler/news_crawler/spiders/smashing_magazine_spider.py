from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


class SmashingMagazineSpider(FeedSpider):
    name = 'smashing_magazine'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = [POLICIES[name].feed_url]
