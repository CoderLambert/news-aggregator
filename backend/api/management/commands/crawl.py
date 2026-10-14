import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from scrapy.crawler import CrawlerProcess
from scrapy.settings import default_settings as scrapy_default_settings
from scrapy.utils.project import get_project_settings
from api.services.source_policy import install_runtime_policy
from api.services.source_registry import CODE_SPIDERS, runtime_registry

CRAWLER_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'crawler')
# Compatibility export for code that enumerates reviewed Python spiders.
# Execution and admin validation use the live merged registry below.
SPIDERS = CODE_SPIDERS


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
    settings.set('LOG_INSTALL_ROOT_HANDLER', False, priority='spider')


def _configure_crawl_only_logging():
    """Keep persistent worker logs operational and free of scraped item bodies."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in root_logger.handlers:
        handler.setLevel(logging.INFO)
    logging.getLogger('scrapy').setLevel(logging.INFO)
    logging.getLogger('asyncio').setLevel(logging.WARNING)


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


def _parse_crawl_result(output):
    from api.services.crawl_metrics import RESULT_PREFIX
    for line in reversed(output.splitlines()):
        if not line.startswith(RESULT_PREFIX):
            continue
        try:
            result = json.loads(line[len(RESULT_PREFIX):])
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict):
            return result
    return {}


class Command(BaseCommand):
    help = '运行Scrapy爬虫抓取新闻'

    def add_arguments(self, parser):
        parser.add_argument(
            'spider',
            nargs='?',
            default='all',
            help='指定来源标识 (all=全部已注册来源)',
        )

    def handle(self, *args, **options):
        sys.path.insert(0, CRAWLER_DIR)
        os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'news_crawler.settings')

        spider_name = options['spider']
        if spider_name == 'all':
            return self._crawl_all_serially()
        entry = runtime_registry().get(spider_name)
        if entry is None or not entry.runnable:
            raise CommandError(f'未知、未审批或不可运行的来源：{spider_name}')

        source_snapshot = None
        if entry.maintenance == 'database':
            try:
                source_snapshot = json.loads(os.environ.get('NEWS_SOURCE_SNAPSHOT', 'null'))
                install_runtime_policy(source_snapshot)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise CommandError('动态来源缺少有效的任务配置快照。') from error
            if source_snapshot.get('source_key') != spider_name:
                raise CommandError('动态来源任务快照与运行目标不匹配。')

        from scrapy.crawler import CrawlerProcess

        settings = get_project_settings()
        crawl_only = os.environ.get('NEWS_CRAWL_ONLY') == '1'
        if crawl_only:
            _apply_crawl_only_politeness(settings)
            # Set the existing Django handler before CrawlerProcess logs its
            # own initialization at DEBUG.
            _configure_crawl_only_logging()
        # Django already owns the command's root handler. Scrapy 2.19 reads
        # LOG_INSTALL_ROOT_HANDLER; 2.18 requires the legacy constructor flag.
        process_kwargs = {}
        if crawl_only and not hasattr(scrapy_default_settings, 'LOG_INSTALL_ROOT_HANDLER'):
            process_kwargs['install_root_handler'] = False
        process = CrawlerProcess(settings, **process_kwargs)
        if crawl_only:
            # Scrapy configures its namespace at DEBUG even without adding a
            # handler. Clamp both the logger and Django's existing handler so
            # item dumps never reach persistent worker logs.
            _configure_crawl_only_logging()

        spiders = [(entry.spider, {
            'source_key': spider_name,
            'source_snapshot': source_snapshot,
        } if entry.maintenance == 'database' else {})]

        crawlers = []
        for spider, spider_kwargs in spiders:
            crawler = process.create_crawler(spider)
            # Spider.custom_settings are applied by create_crawler. Clamp the
            # final settings after that step, before the engine freezes them.
            if crawl_only:
                _apply_crawl_only_politeness(crawler.settings)
            crawler.settings.set('DOWNLOAD_HANDLERS', {
                'http': 'news_crawler.download_handlers.BudgetedHTTPDownloadHandler',
                'https': 'news_crawler.download_handlers.BudgetedHTTPDownloadHandler',
            }, priority='cmdline')
            crawler.settings.set('DOWNLOAD_TIMEOUT', 15, priority='cmdline')
            crawler.settings.set('DOWNLOAD_MAXSIZE', 8 * 1024 * 1024, priority='cmdline')
            crawler.settings.set('RETRY_TIMES', 1, priority='cmdline')
            crawler.settings.set('RETRY_HTTP_CODES', [500, 502, 504, 522, 524], priority='cmdline')
            process.crawl(crawler, **spider_kwargs)
            crawlers.append((spider_name, crawler))
            self.stdout.write(self.style.SUCCESS(f'启动爬虫: {spider_name}'))

        process.start()
        for spider, crawler in crawlers:
            stats = crawler.stats.get_stats()
            self.stdout.write(_format_crawl_summary(spider, stats))
            from api.services.crawl_metrics import crawl_result, RESULT_PREFIX
            self.stdout.write(RESULT_PREFIX + json.dumps(crawl_result(stats), ensure_ascii=True, default=str))
        self.stdout.write(self.style.SUCCESS('爬取完成'))

    def _crawl_all_serially(self):
        """Run sources in isolated reactors so the shared budget cannot starve them."""
        sources = tuple(runtime_registry())
        manage_py = Path(__file__).resolve().parents[3] / 'manage.py'
        max_attempts = 3
        max_wait = 15.0
        failures = []
        for index, spider in enumerate(sources, 1):
            self.stdout.write(f'批量进度 {index}/{len(sources)} source={spider}')
            final = {}
            return_code = 0
            for attempt in range(1, max_attempts + 1):
                completed = subprocess.run(
                    [sys.executable, str(manage_py), 'crawl', spider],
                    cwd=str(manage_py.parent), env=os.environ.copy(), text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                return_code = completed.returncode
                if completed.stdout:
                    self.stdout.write(completed.stdout, ending='' if completed.stdout.endswith('\n') else '\n')
                final = _parse_crawl_result(completed.stdout or '')
                outcome = final.get('outcome')
                if return_code == 0 and outcome in {'updated', 'unchanged', 'valid_empty', 'not_due'}:
                    break
                if attempt == max_attempts or outcome not in {'deferred', 'network_error'}:
                    break
                delay = min(2.0 * attempt, max_wait)
                if outcome == 'deferred' and final.get('next_attempt_at'):
                    deadline = parse_datetime(str(final['next_attempt_at']))
                    if deadline is not None:
                        delay = max(delay, (deadline - timezone.now()).total_seconds())
                if delay > max_wait:
                    break
                self.stdout.write(
                    f'批量重试 source={spider} attempt={attempt + 1} wait_seconds={max(0.0, delay):.1f}'
                )
                time.sleep(max(0.0, delay))
            if return_code != 0 or final.get('outcome') not in {'updated', 'unchanged', 'valid_empty', 'not_due'}:
                failures.append(f'{spider}:{final.get("outcome", "missing_result")}:{return_code}')
        if failures:
            raise CommandError('批量抓取未全部完成：' + ', '.join(failures))
        self.stdout.write(self.style.SUCCESS(f'批量抓取完成：{len(sources)} 个来源均获得终态。'))
