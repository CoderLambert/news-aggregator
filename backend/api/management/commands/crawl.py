import os
import sys
from django.core.management.base import BaseCommand

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

CRAWLER_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'crawler')
SPIDERS = {
    'sina': 'sina',
    'bbc': 'bbc',
    'reuters': 'reuters',
    'hackernews': 'hackernews',
    'github': 'github',
    'devto': 'devto',
    'techcrunch': 'techcrunch',
    'producthunt': 'producthunt',
}


class Command(BaseCommand):
    help = '运行Scrapy爬虫抓取新闻'

    def add_arguments(self, parser):
        parser.add_argument(
            'spider',
            nargs='?',
            default='all',
            choices=['all'] + list(SPIDERS.keys()),
            help='指定爬虫名称 (all=sina,bbc,reuters)',
        )

    def handle(self, *args, **options):
        sys.path.insert(0, CRAWLER_DIR)
        os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'news_crawler.settings')

        from scrapy.crawler import CrawlerProcess

        settings = get_project_settings()
        process = CrawlerProcess(settings)

        spider_name = options['spider']
        if spider_name == 'all':
            spiders = SPIDERS.values()
        else:
            spiders = [SPIDERS[spider_name]]

        for spider in spiders:
            process.crawl(spider)
            self.stdout.write(self.style.SUCCESS(f'启动爬虫: {spider}'))

        process.start()
        self.stdout.write(self.style.SUCCESS('爬取完成'))
