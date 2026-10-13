from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider
from api.services.source_dates import parse_source_datetime


def parse_venturebeat_publish_time(value, *, fallback=None):
    """Legacy parsing entrypoint: only explicit callers may choose a fallback."""
    return parse_source_datetime(value) or fallback


class VenturebeatAiSpider(FeedSpider):
    name = 'venturebeat_ai'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = [POLICIES[name].feed_url]
