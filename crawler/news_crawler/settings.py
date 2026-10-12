import os

BOT_NAME = "news_crawler"

SPIDER_MODULES = ["news_crawler.spiders"]
NEWSPIDER_MODULE = "news_crawler.spiders"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# Crawl-only jobs honor source robots rules; the default development behavior is unchanged.
CRAWL_ONLY_MODE = os.environ.get("NEWS_CRAWL_ONLY") == "1"
ROBOTSTXT_OBEY = CRAWL_ONLY_MODE
TELNETCONSOLE_ENABLED = not CRAWL_ONLY_MODE

# Tuned for Termux/mobile: lower concurrency to avoid CPU/IO contention.
# On a server/desktop, set CONCURRENT_REQUESTS=16 and CONCURRENT_REQUESTS_PER_DOMAIN=4.
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 3

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

ITEM_PIPELINES = {
    "news_crawler.pipelines.DjangoPipeline": 300,
}

FEED_EXPORT_ENCODING = "utf-8"

# Playwright - only enabled per-spider via meta={'playwright': True}
# Uncomment below when Playwright deps are installed:
# DOWNLOAD_HANDLERS = {
#     "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
#     "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
# }
# TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
# PLAYWRIGHT_BROWSER_TYPE = "chromium"
# PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

LOG_LEVEL = "INFO"

# Admission wraps the maintained HTTP handler at the actual download boundary.
DOWNLOAD_HANDLERS = {
    'http': 'news_crawler.download_handlers.BudgetedHTTPDownloadHandler',
    'https': 'news_crawler.download_handlers.BudgetedHTTPDownloadHandler',
}
DOWNLOAD_TIMEOUT = 15
DOWNLOAD_MAXSIZE = 8 * 1024 * 1024
RETRY_TIMES = 1
RETRY_HTTP_CODES = [500, 502, 504, 522, 524]
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 1

# Do not expose the new Scrapy 2.19 control listener in ordinary crawl jobs.
REMOTE_CONTROL_ENABLED = False

TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'
