from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


class DeepmindBlogSpider(FeedSpider):
    name = 'deepmind'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = [POLICIES[name].feed_url]
