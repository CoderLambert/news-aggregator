from api.services.source_policy import POLICIES
from news_crawler.spiders.feed import FeedSpider


class BbcSpider(FeedSpider):
    name = 'bbc'
    allowed_domains = list(POLICIES[name].domains)
    start_urls = ['https://feeds.bbci.co.uk/news/world/rss.xml',
                  'https://feeds.bbci.co.uk/news/technology/rss.xml',
                  'https://feeds.bbci.co.uk/news/business/rss.xml']
