from news_crawler.spiders.unsupported import UnsupportedSourceSpider


class JiqizhixinSpider(UnsupportedSourceSpider):
    """Quarantined until the publisher supplies reliable IDs and article URLs."""
    name = 'jiqizhixin'
    allowed_domains = ['jiqizhixin.com']
