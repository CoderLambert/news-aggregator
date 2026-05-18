import scrapy


class NewsItem(scrapy.Item):
    title = scrapy.Field()
    content = scrapy.Field()
    author = scrapy.Field()
    publish_time = scrapy.Field()
    source_name = scrapy.Field()
    category_name = scrapy.Field()
    url = scrapy.Field()
    cover_image = scrapy.Field()
