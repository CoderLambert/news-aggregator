from datetime import datetime, timezone

from django.db import migrations


PROBED_AT = datetime(2026, 10, 15, tzinfo=timezone.utc)

SOURCES = (
    {
        'key': 'chinanews_health', 'publisher': '中国新闻社', 'channel': '中新网健康',
        'kind': 'rss', 'url': 'https://www.chinanews.com.cn/rss/jk.xml',
        'domains': ['www.chinanews.com.cn'], 'policy': 'summary_only', 'content_kind': 'article',
        'status': 'probed', 'format': 'rss20', 'http_status': 200,
        'samples': [{'title': '全球第一不可逆致盲眼病！40岁后，这项检查务必要做→',
                     'url': 'https://www.chinanews.com.cn/jk/2026/03-06/10581992.shtml',
                     'published_at': '2026-03-06T07:50:05+08:00'}],
        'parser': {'identity_field': 'id|guid|link', 'title_field': 'title', 'link_field': 'link',
                   'summary_field': 'summary', 'published_field': 'published', 'full_content_fields': []},
    },
    {
        'key': 'china_cdc_news', 'publisher': '中国疾病预防控制中心', 'channel': '中国疾控中心要闻',
        'kind': 'html', 'url': 'https://www.chinacdc.cn/zxyw/', 'domains': ['www.chinacdc.cn'],
        'policy': 'official_html', 'content_kind': 'article', 'status': 'probed', 'format': 'html',
        'http_status': 200, 'parser': {'list_item': 'ul.xw_list li', 'title': 'a', 'link': 'a',
                                      'summary': 'p.zy', 'date': 'a span', 'date_format': '%Y-%m-%d'},
        'samples': [{'title': '2026年世界标准日卫生健康和疾病预防控制标准化主题宣传活动在宁波举行',
                     'url': 'https://www.chinacdc.cn/zxyw/202610/t20261014_1842267.html',
                     'published_at': '2026-10-14'}],
    },
    {
        'key': 'nhc_news', 'publisher': '国家卫生健康委员会', 'channel': '国家卫健委新闻动态',
        'kind': 'html', 'url': 'https://www.nhc.gov.cn/wjw/xwdt/list.shtml', 'domains': ['www.nhc.gov.cn'],
        'policy': 'official_html', 'content_kind': 'article', 'status': 'blocked', 'format': 'html',
        'http_status': 412, 'reason': 'http_412',
        'parser': {'list_item': 'li', 'title': 'a', 'link': 'a', 'date': 'span'},
    },
    {
        'key': 'nhsa_news', 'publisher': '国家医疗保障局', 'channel': '国家医保局医保动态',
        'kind': 'html', 'url': 'https://www.nhsa.gov.cn/col/col14/index.html', 'domains': ['www.nhsa.gov.cn'],
        'policy': 'official_html', 'content_kind': 'article', 'status': 'probed', 'format': 'html',
        'http_status': 200, 'parser': {'list_item': 'record li', 'title': 'a', 'link': 'a',
                                      'date': 'span', 'date_format': '%Y-%m-%d'},
        'samples': [{'title': '国家医疗保障局党组召开会议专题传达学习贯彻全国卫生与健康大会精神',
                     'url': 'https://www.nhsa.gov.cn/art/2026/10/14/art_14_23143.html',
                     'published_at': '2026-10-14T10:59:00+08:00'}],
    },
    {
        'key': 'nmpa_news', 'publisher': '国家药品监督管理局', 'channel': '国家药监局要闻',
        'kind': 'html', 'url': 'https://www.nmpa.gov.cn/directory/web/nmpa/yaowen/index.html',
        'domains': ['www.nmpa.gov.cn'], 'policy': 'official_html', 'content_kind': 'article',
        'status': 'blocked', 'format': 'html', 'http_status': 412, 'reason': 'http_412',
        'parser': {'list_item': 'li', 'title': 'a', 'link': 'a', 'date': 'span'},
    },
    {
        'key': 'nmpa_udi_daily', 'publisher': '国家药品监督管理局', 'channel': '医疗器械唯一标识每日增量',
        'kind': 'rss', 'url': 'https://udi.nmpa.gov.cn/rss/download.html?files=daily',
        'domains': ['udi.nmpa.gov.cn', 'udid.nmpa.gov.cn'], 'policy': 'regulatory_data',
        'content_kind': 'regulatory_data', 'status': 'probed', 'format': 'rss20', 'http_status': 200,
        'samples': [{'title': 'UDID_DAY_UPDATE_20261014.zip',
                     'url': 'https://udi.nmpa.gov.cn/rss/download.html?files=daily',
                     'published_at': '2026-10-14T15:35:39+00:00'}],
        'parser': {'identity_field': 'id|guid|link', 'title_field': 'title', 'link_field': 'link',
                   'summary_field': 'summary', 'published_field': 'published', 'full_content_fields': []},
    },
)


def seed_sources(apps, schema_editor):
    Category = apps.get_model('api', 'Category')
    Source = apps.get_model('api', 'Source')
    SourceConfig = apps.get_model('api', 'SourceConfig')
    SourceEndpoint = apps.get_model('api', 'SourceEndpoint')
    CrawlerTarget = apps.get_model('api', 'CrawlerTarget')
    category, _ = Category.objects.get_or_create(
        name='医疗健康', defaults={'slug': 'medical-health', 'description': '医疗、公共卫生与药品器械监管资讯'},
    )
    for row in SOURCES:
        source, _ = Source.objects.get_or_create(
            name=row['channel'],
            defaults={'url': row['url'], 'region': 'domestic', 'country': 'CN', 'language': 'zh',
                      'source_type': 'news', 'description': f"{row['publisher']} · {row['channel']}"},
        )
        summary = {
            'probed_at': PROBED_AT.isoformat(), 'endpoint_kind': row['kind'], 'url': row['url'],
            'http_status': row['http_status'], 'format': row['format'],
            'outcome': 'SUPPORTED' if row['status'] == 'probed' else 'BLOCKED',
            'evidence': 'docs/features/domestic-medical-sources/source-probes.json',
            'sample_articles': row.get('samples', []),
        }
        config, created = SourceConfig.objects.get_or_create(
            source_key=row['key'],
            defaults={
                'source': source, 'publisher_name': row['publisher'], 'channel_name': row['channel'],
                'category': category, 'region': 'domestic', 'language': 'zh',
                'content_kind': row['content_kind'], 'reading_policy': row['policy'], 'status': row['status'],
                'summary_allowed': True, 'feed_full_content_allowed': False,
                'official_html_full_content_allowed': False, 'probe_summary': summary,
                'probed_config_version': 1 if row['status'] == 'probed' else None,
                'probed_at': PROBED_AT, 'unavailable_reason': row.get('reason', ''),
            },
        )
        if created:
            SourceEndpoint.objects.create(
                source_config=config, kind=row['kind'], url=row['url'], allowed_domains=row['domains'],
                parser_config=row['parser'], conditional_requests=True, request_interval_seconds=10,
                max_response_bytes=2 * 1024 * 1024, max_pages=1, max_items=50,
            )
        CrawlerTarget.objects.update_or_create(
            spider_name=row['key'], defaults={'display_name': row['channel'], 'enabled': False},
        )


class Migration(migrations.Migration):
    dependencies = [('api', '0050_crawlrun_config_snapshot')]
    operations = [migrations.RunPython(seed_sources, migrations.RunPython.noop)]
