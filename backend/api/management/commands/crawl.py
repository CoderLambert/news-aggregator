import os
import sys
from django.core.management.base import BaseCommand

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

CRAWLER_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'crawler')
SPIDERS = {
    # General tech news & aggregators
    'bbc': 'bbc',
    'reuters': 'reuters',
    'hackernews': 'hackernews',
    'github': 'github',
    'devto': 'devto',
    'techcrunch': 'techcrunch',
    'producthunt': 'producthunt',
    'infoq': 'infoq',
    # Frontend Development
    'css_tricks': 'css_tricks',
    'webdev': 'webdev',
    'chrome_dev': 'chrome_dev',
    'smashing_magazine': 'smashing_magazine',
    'react_blog': 'react_blog',
    'svelte_blog': 'svelte_blog',
    'angular_blog': 'angular_blog',
    'webkit': 'webkit',
    'v8': 'v8',
    'mozilla_hacks': 'mozilla_hacks',
    'frontend_focus': 'frontend_focus',
    # AI Company Blogs
    'openai_blog': 'openai_blog',
    'anthropic': 'anthropic',
    'deepmind': 'deepmind',
    'meta_ai': 'meta_ai',
    'mistral': 'mistral',
    # AI Specialized Media
    'venturebeat_ai': 'venturebeat_ai',
    'ars_technica_ai': 'ars_technica_ai',
    'mit_tech_review_ai': 'mit_tech_review_ai',
    # AI Papers
    'arxiv_ai': 'arxiv_ai',
    # Chinese AI News
    'jiqizhixin': 'jiqizhixin',
    'leiphone': 'leiphone',
    'sanliu_kr': 'sanliu_kr',
}


def _apply_crawl_only_politeness(settings):
    """Clamp source-specific Scrapy overrides to conservative crawl-only rates."""
    delay = max(3.0, settings.getfloat('DOWNLOAD_DELAY', 3.0))
    global_concurrency = min(4, settings.getint('CONCURRENT_REQUESTS', 4))
    settings.set('DOWNLOAD_DELAY', delay, priority='spider')
    settings.set('CONCURRENT_REQUESTS', global_concurrency, priority='spider')
    settings.set('CONCURRENT_REQUESTS_PER_DOMAIN', 1, priority='spider')
    settings.set('AUTOTHROTTLE_ENABLED', True, priority='spider')
    settings.set('AUTOTHROTTLE_START_DELAY', 3.0, priority='spider')
    settings.set('AUTOTHROTTLE_MAX_DELAY', 60.0, priority='spider')
    settings.set('AUTOTHROTTLE_TARGET_CONCURRENCY', 1.0, priority='spider')
    # DEBUG item dumps may contain full upstream article bodies. Persistent
    # worker logs only need operational INFO/WARNING/ERROR records.
    settings.set('LOG_LEVEL', 'INFO', priority='spider')


def _format_crawl_summary(spider_name, stats):
    """Return one stable, grep-friendly result line for a completed spider."""
    http_statuses = sorted(
        (
            key.rsplit('/', 1)[-1], value
        )
        for key, value in stats.items()
        if key.startswith('downloader/response_status_count/')
    )
    status_text = ','.join(f'{code}:{count}' for code, count in http_statuses) or '-'
    return (
        f'爬虫汇总 source={spider_name} '
        f'finish={stats.get("finish_reason", "unknown")} '
        f'items={stats.get("item_scraped_count", 0)} '
        f'responses={stats.get("downloader/response_count", 0)} '
        f'errors={stats.get("log_count/ERROR", 0)} '
        f'http={status_text}'
    )


class Command(BaseCommand):
    help = '运行Scrapy爬虫抓取新闻'

    def add_arguments(self, parser):
        parser.add_argument(
            'spider',
            nargs='?',
            default='all',
            choices=['all'] + list(SPIDERS.keys()),
            help='指定爬虫名称 (all=全部爬虫)',
        )

    def handle(self, *args, **options):
        sys.path.insert(0, CRAWLER_DIR)
        os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'news_crawler.settings')

        from scrapy.crawler import CrawlerProcess

        settings = get_project_settings()
        if os.environ.get('NEWS_CRAWL_ONLY') == '1':
            _apply_crawl_only_politeness(settings)
        process = CrawlerProcess(settings)

        spider_name = options['spider']
        if spider_name == 'all':
            spiders = SPIDERS.values()
        else:
            spiders = [SPIDERS[spider_name]]

        crawlers = []
        for spider in spiders:
            crawler = process.create_crawler(spider)
            process.crawl(crawler)
            crawlers.append((spider, crawler))
            self.stdout.write(self.style.SUCCESS(f'启动爬虫: {spider}'))

        process.start()
        for spider, crawler in crawlers:
            self.stdout.write(_format_crawl_summary(spider, crawler.stats.get_stats()))
        self.stdout.write(self.style.SUCCESS('爬取完成'))
