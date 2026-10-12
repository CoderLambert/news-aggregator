"""Full Scrapy → Pipeline → SQLite → conditional-request lifecycle, offline."""
import os
from pathlib import Path
import subprocess
import sys


def test_failed_pipeline_replays_without_checkpoint_then_304_uses_committed_feed(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = tmp_path / 'feed_lifecycle_probe.py'
    script.write_text(r'''
import django, threading, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import replace
from datetime import timedelta
from email.utils import format_datetime
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

django.setup()
call_command('migrate', verbosity=0)
from api.services.source_policy import POLICIES
POLICIES['webkit'] = replace(POLICIES['webkit'], feed_url='http://webkit.org/feed/')
from scrapy.crawler import CrawlerProcess
from scrapy.utils.reactor import install_reactor
install_reactor('twisted.internet.asyncioreactor.AsyncioSelectorReactor')
from twisted.internet import reactor
from scrapy.utils.defer import deferred_from_coro, maybe_deferred_to_future
from asgiref.sync import sync_to_async
from news_crawler.spiders.feed import FeedSpider
from news_crawler.pipelines import DjangoPipeline
from api.models import FeedState, News, NewsSourceItem
requests = []
body = ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
        '<title>Synthetic WebKit</title><link>https://webkit.org/</link><description>Offline fixture</description>' +
        ''.join(f'<item><title>Synthetic post {i}</title><guid isPermaLink="false">publisher-{i}</guid>'
                f'<link>https://webkit.org/blog/{i}/synthetic/</link><pubDate>{format_datetime(timezone.now(),usegmt=True)}</pubDate>'
                f'<content:encoded><![CDATA[<p>Complete synthetic body {i}.</p>]]></content:encoded></item>' for i in (1,2)) +
        '</channel></rss>').encode()
class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        requests.append(self.headers.get('If-None-Match'))
        assert self.path == 'http://webkit.org/feed/'
        if requests[-1] == '"stable"':
            self.send_response(304)
            self.send_header('Content-Length','0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type','application/rss+xml')
        self.send_header('ETag','"stable"')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
proxy = ThreadingHTTPServer(('127.0.0.1',0),Proxy)
threading.Thread(target=proxy.serve_forever,daemon=True).start()
fail_once = True
class FaultPipeline(DjangoPipeline):
    async def process_item(self,item,spider=None):
        global fail_once
        if item['upstream_id'] == 'publisher-2' and fail_once:
            fail_once = False
            raise RuntimeError('synthetic_persistence_failure')
        return await super().process_item(item,spider)
class Probe(FeedSpider):
    name='webkit'
    start_urls=['http://webkit.org/feed/']
    async def start(self):
        async for request in super().start():
            # All TCP traffic goes to this local proxy. The public URL remains
            # genuine-shaped synthetic identity and is never contacted.
            request.meta['proxy']=f'http://127.0.0.1:{proxy.server_port}'
            yield request
process = CrawlerProcess({
    'DOWNLOAD_HANDLERS': {'http':'news_crawler.download_handlers.BudgetedHTTPDownloadHandler',
                          'https':'news_crawler.download_handlers.BudgetedHTTPDownloadHandler'},
    'DOWNLOADER_MIDDLEWARES': {'news_crawler.middlewares.FeedConditionalHeadersMiddleware':610},
    'ITEM_PIPELINES': {'__main__.FaultPipeline':300}, 'ROBOTSTXT_OBEY':False,
    'RETRY_HTTP_CODES':[500,502,504], 'RETRY_TIMES':1,
    'LOG_LEVEL':'WARNING','TELNETCONSOLE_ENABLED':False,'REMOTE_CONTROL_ENABLED':False,
})
report={}
def inspect_first():
    state=FeedState.objects.get(source_key='webkit')
    assert state.etag == '' and state.last_success_at is None
    assert News.objects.filter(full_content_state='complete').count()==1
    state.next_poll_at=timezone.now()-timedelta(seconds=1)
    state.save(update_fields=['next_poll_at'])
def inspect_second():
    state=FeedState.objects.get(source_key='webkit')
    assert state.etag=='"stable"' and state.last_success_at is not None
    assert News.objects.count()==2 and NewsSourceItem.objects.count()==2
    assert News.objects.filter(full_content_state='complete').count()==2
    assert set(News.objects.values_list('full_content_revision',flat=True))=={1}
    state.next_poll_at=timezone.now()-timedelta(seconds=1)
    state.save(update_fields=['next_poll_at'])
async def run():
    first=process.create_crawler(Probe)
    await maybe_deferred_to_future(process.crawl(first))
    assert first.stats.get_value('outcome')=='partial'
    assert not first.stats.get_value('checkpoint_committed')
    await sync_to_async(inspect_first)()
    second=process.create_crawler(Probe)
    await maybe_deferred_to_future(process.crawl(second))
    assert second.stats.get_value('checkpoint_committed')
    await sync_to_async(inspect_second)()
    third=process.create_crawler(Probe)
    await maybe_deferred_to_future(process.crawl(third))
    assert third.stats.get_value('outcome')=='unchanged'
    assert requests==[None,None,'"stable"'], requests
    report.update(replayed=True, checkpoint_after_commit=True, conditional_304=True)
errors=[]
def launch():
    task=deferred_from_coro(run())
    def done(result):
        if hasattr(result,'getTraceback'): errors.append(result.getTraceback())
        reactor.stop()
    task.addBoth(done)
with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS={'webkit'}):
    reactor.callWhenRunning(launch)
    process.start(stop_after_crawl=False)
proxy.shutdown()
assert not errors, '\n'.join(errors)
print(json.dumps(report))
''', encoding='utf-8')
    result = subprocess.run([sys.executable, str(script)], cwd=root, env={
        **os.environ, 'PYTHONPATH': f'{root / "backend"}:{root / "crawler"}',
        'DJANGO_ENV': 'development', 'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_DB_PATH': str(tmp_path / 'feed.sqlite3'), 'RUN_MAIN': 'true', 'NEWS_CRAWL_ONLY': '1',
    }, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"checkpoint_after_commit": true' in result.stdout
