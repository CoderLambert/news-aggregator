from pathlib import Path

from scrapy.http import XmlResponse

from news_crawler.items import NewsItem
from news_crawler.spiders.bbc_spider import BbcSpider


def test_bbc_parses_media_thumbnail_after_removing_xml_namespaces():
    fixture = Path(__file__).parent / 'fixtures' / 'bbc_rss_namespaced.xml'
    response = XmlResponse(
        url='https://feeds.example.invalid/bbc.xml',
        body=fixture.read_bytes(),
        encoding='utf-8',
    )

    results = list(BbcSpider().parse(response))
    news_item = next(result for result in results if isinstance(result, NewsItem))

    assert news_item['title'] == 'Synthetic fixture title'
    assert news_item['cover_image'] == 'https://images.example.invalid/fixture-thumbnail.png'
