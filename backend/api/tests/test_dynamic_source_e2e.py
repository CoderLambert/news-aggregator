import os
from pathlib import Path
import subprocess
import sys


def test_dynamic_json_spider_ingests_in_isolated_sqlite(tmp_path):
    root = Path(__file__).resolve().parents[3]
    script = tmp_path / 'dynamic_source_e2e.py'
    script.write_text(r'''
import django
from datetime import datetime, timezone

django.setup()
from django.core.management import call_command
call_command('migrate', verbosity=0)

from api.models import Category, FeedState, News, NewsSourceItem, Source, SourceConfig, SourceEndpoint
from api.services.source_registry import source_snapshot
category, _ = Category.objects.get_or_create(name='医疗健康', defaults={'slug': 'medical-health'})
source = Source.objects.create(name='隔离测试卫生频道', url='https://fixture.example.cn/news/')
now = datetime(2026, 10, 15, tzinfo=timezone.utc)
config = SourceConfig.objects.create(
    source_key='isolated_health', source=source, publisher_name='隔离测试机构', channel_name=source.name,
    category=category, status='approved', probed_config_version=1, probed_at=now,
    approved_config_version=1, approved_at=now, reading_policy='summary_only',
)
SourceEndpoint.objects.create(
    source_config=config, kind='json', url='https://fixture.example.cn/api/news',
    allowed_domains=['fixture.example.cn'], parser_config={
        'list_path': 'data.items',
        'fields': {'identity': 'id', 'title': 'title', 'link': 'url',
                   'summary': 'summary', 'published': 'published'},
    }, max_pages=1, max_items=5,
)
snapshot = source_snapshot(config.source_key)

from scrapy.http import Response
class FixtureHandler:
    lazy = False
    def __init__(self, crawler): self.crawler = crawler
    @classmethod
    def from_crawler(cls, crawler): return cls(crawler)
    async def download_request(self, request, spider=None):
        body = (b'{"data":{"items":[{"id":"notice-1","title":"Official health notice",'
                b'"url":"/news/notice-1","summary":"Publisher summary only",'
                b'"published":"2026-10-15T00:00:00Z"}]}}')
        return Response(request.url, status=200, headers={'Content-Type': 'application/json'},
                        body=body, request=request)
    async def close(self): pass

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from news_crawler.spiders.dynamic_source_spider import DynamicSourceSpider
settings = get_project_settings()
settings.set('DOWNLOAD_HANDLERS', {'http': '__main__.FixtureHandler', 'https': '__main__.FixtureHandler'}, priority='cmdline')
settings.set('ROBOTSTXT_OBEY', False, priority='cmdline')
settings.set('LOG_ENABLED', False, priority='cmdline')
settings.set('TELNETCONSOLE_ENABLED', False, priority='cmdline')
process = CrawlerProcess(settings)
process.crawl(DynamicSourceSpider, source_key=config.source_key, source_snapshot=snapshot)
process.start()

mapping = NewsSourceItem.objects.select_related('news').get(source_key=config.source_key, upstream_id='notice-1')
assert mapping.news.content == 'Publisher summary only'
assert mapping.news.full_content == ''
assert mapping.metadata['publisher_name'] == '隔离测试机构'
assert FeedState.objects.get(source_key=config.source_key).last_success_at is not None
assert News.objects.filter(pk=mapping.news_id).count() == 1
print('dynamic-e2e-ok')
''', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(script)], cwd=root, capture_output=True, text=True, timeout=30,
        env={
            **os.environ,
            'PYTHONPATH': f'{root / "backend"}:{root / "crawler"}',
            'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
            'SCRAPY_SETTINGS_MODULE': 'news_crawler.settings',
            'DJANGO_ENV': 'development', 'RUN_MAIN': 'true',
            'NEWS_CRAWL_ONLY': '1', 'DJANGO_DB_PATH': str(tmp_path / 'dynamic.sqlite3'),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'dynamic-e2e-ok' in result.stdout
