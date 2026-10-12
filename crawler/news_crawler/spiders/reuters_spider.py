from news_crawler.spiders.unsupported import UnsupportedSourceSpider


class ReutersSpider(UnsupportedSourceSpider):
    """Requires real article identities from an authorized delivery channel."""
    name = 'reuters'
    allowed_domains = ['reuters.com']
