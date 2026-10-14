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

    source_key = scrapy.Field()
    upstream_id = scrapy.Field()
    discovery_url = scrapy.Field()
    content_kind = scrapy.Field()
    summary = scrapy.Field()
    body_candidate = scrapy.Field()
    feed_receipt_id = scrapy.Field()
    source_modified_at = scrapy.Field()
    source_version = scrapy.Field()
    publish_time_inferred = scrapy.Field()
    publisher_name = scrapy.Field()
    channel_name = scrapy.Field()
    endpoint_kind = scrapy.Field()
    endpoint_url = scrapy.Field()
