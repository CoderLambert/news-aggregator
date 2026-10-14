# NH-22/NH-26 and old HN-first assertion updated for NH-19's intentional behavior.
P.replace('backend/api/tests/test_news_ingestion.py',
    "    assert has_full_content(news) and news.source.name == 'Hacker News'\n    assert news.title == 'An editorial HN headline'\n    assert news.source_items.count() == 2",
    "    assert has_full_content(news) and news.source.name == 'Dev.to'\n    assert news.title == 'The exact publisher headline'\n    assert news.source_items.count() == 2\n    assert news.source_items.filter(source_key='hackernews', upstream_id='999').exists()")
P.replace('crawler/news_crawler/category_map.py', 'ALL_CATEGORIES = {',
    "import re\nfrom functools import lru_cache\n\nCLASSIFIER_VERSION = 'token-boundaries-2'\n\nALL_CATEGORIES = {")
P.replace('crawler/news_crawler/category_map.py',
    "def classify(title, description=''):\n    text = f'{title} {description}'.lower()\n    for category, keywords in KEYWORD_MAP.items():\n        if any(kw in text for kw in keywords):\n            return category\n    return DEFAULT_CATEGORY",
    '''@lru_cache(maxsize=512)
def _keyword_pattern(keyword):
    # ASCII words/phrases must not match inside Email, Main, goal, etc.
    # Chinese phrases retain intentional substring semantics.
    if keyword.isascii():
        return re.compile(r'(?<![a-z0-9_])' + re.escape(keyword) + r'(?![a-z0-9_])')
    return None


def classify(title, description=''):
    text = f'{title} {description}'.lower()
    for category, keywords in KEYWORD_MAP.items():
        if any((_keyword_pattern(kw).search(text) is not None) if kw.isascii() else kw in text for kw in keywords):
            return category
    return DEFAULT_CATEGORY''')
P.replace('backend/api/models.py',
    "    country = models.CharField('国家', max_length=50, default='CN')",
    "    country = models.CharField('国家', max_length=50, blank=True, default='')")
P.replace('backend/api/models.py', 'from django.utils import timezone',
    'from django.utils import timezone\nfrom api.metadata_models import MetadataCorrectionAudit')
P.replace('backend/api/services/channel_catalog.py',
    'from api.services.source_policy import POLICIES, policy_for_name',
    'from api.services.source_policy import POLICIES, policy_for_name\nfrom api.services.source_metadata import publisher_country')
P.replace('backend/api/services/channel_catalog.py',
    "        'country': 'CN' if policy.region == 'domestic' else 'UK' if policy.key in {'bbc', 'deepmind'} else 'FR' if policy.key == 'mistral' else 'US',",
    "        'country': publisher_country(policy.key),")
P.replace('backend/api/services/news_ingestion.py',
    "    source, _ = Source.objects.get_or_create(name=policy.name, defaults={**source_defaults, 'region': policy.region})",
    "    from api.services.channel_catalog import catalog_defaults\n    from api.services.source_metadata import publisher_country\n    source, _ = Source.objects.get_or_create(name=policy.name, defaults={\n        **catalog_defaults(policy), **source_defaults, 'region': policy.region,\n        'country': publisher_country(policy.key)})")
P.replace('backend/api/serializers.py',
    "        return bool(items) and all(item.metadata.get('publish_time_inferred', False) for item in items)",
    "        from api.services.source_metadata import primary_publication_evidence\n        return primary_publication_evidence(obj)['inferred']")
P.replace('frontend/src/components/NewsCard.tsx',
    "`${new Date(news.publish_time).toLocaleDateString()}（时间推断）`",
    "`${new Date(news.created_at).toLocaleDateString()} 收录 · 发布时间未确认`")
P.replace('frontend/src/pages/NewsDetail.tsx',
    "<time>{new Date(news.publish_time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}{news.publish_time_inferred && '（时间推断）'}</time>",
    "<time dateTime={news.publish_time_inferred ? news.created_at : news.publish_time}>{new Date(news.publish_time_inferred ? news.created_at : news.publish_time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}{news.publish_time_inferred ? ' 收录（发布时间未确认）' : ' 发布'}</time>")
