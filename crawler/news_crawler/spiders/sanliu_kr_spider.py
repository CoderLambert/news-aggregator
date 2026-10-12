from news_crawler.spiders.unsupported import UnsupportedSourceSpider


class SanliuKrSpider(UnsupportedSourceSpider):
    """The existing /feed returns HTML, not a verified publisher feed."""
    name = 'sanliu_kr'
    allowed_domains = ['36kr.com']
