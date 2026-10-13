from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


class ArxivAiSpider(FeedSpider):
    """Official query discovers paper abstracts, never article or PDF bodies."""
    name = 'arxiv_ai'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = [POLICIES[name].feed_url]
