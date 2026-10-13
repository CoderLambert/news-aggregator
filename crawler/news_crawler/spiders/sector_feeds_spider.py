from api.services.source_policy import POLICIES
from api.services.sector_feeds import SECTOR_KEYS
from news_crawler.spiders.feed import FeedSpider

# Scrapy discovers module-local subclasses by their unique channel name.
for key in sorted(SECTOR_KEYS):
    policy = POLICIES[key]
    if policy.unsupported_reason:
        continue
    class_name = ''.join(part.capitalize() for part in key.split('_')) + 'Spider'
    globals()[class_name] = type(class_name, (FeedSpider,), {
        '__module__': __name__, 'name': key, 'allowed_domains': list(policy.domains),
        'start_urls': [policy.feed_url],
    })
