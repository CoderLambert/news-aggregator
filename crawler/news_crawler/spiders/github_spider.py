import scrapy
from api.services.crawl_metrics import parse_failure
import re
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class GithubTrendingSpider(scrapy.Spider):
    name = 'github'
    allowed_domains = ['github.com']
    start_urls = [
        'https://github.com/trending',
        'https://github.com/trending?since=weekly',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        since = 'daily' if 'since' not in response.url else response.url.split('since=')[-1]
        articles = response.css('article.Box-row')
        if not articles:
            parse_failure(self)
            return

        for article in articles:
            repo_path = article.css('h2 a::attr(href)').get()
            if not repo_path:
                continue

            repo_path = repo_path.strip().lstrip('/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo_path):
                continue
            url = f'https://github.com/{repo_path}'

            description = article.css('p::text').get('')
            if description:
                description = description.strip()

            language = article.css('[itemprop="programmingLanguage"]::text').get('')
            language = language.strip() if language else ''

            stars_total = article.css('.Link--muted.d-inline-block.mr-3 svg.octicon-star + span::text').get('')
            if not stars_total:
                stars_total = article.css('a.Link--muted:nth-of-type(1) span::text').get('')
            stars_total = stars_total.strip().replace(',', '') if stars_total else '0'

            stars_today = article.css('.float-sm-right::text').get('')
            if stars_today:
                stars_today = stars_today.strip().replace(',', '')

            content_parts = []
            if description:
                content_parts.append(description)
            content_parts.append(f'Total Stars: {stars_total}')
            if stars_today:
                content_parts.append(f'Stars {since}: {stars_today}')
            if language:
                content_parts.append(f'Language: {language}')
            content = ' | '.join(content_parts)

            news = NewsItem()
            news['title'] = repo_path
            news['content'] = content
            news['author'] = repo_path.split('/')[0] if '/' in repo_path else ''
            news['publish_time'] = None
            news['publish_time_inferred'] = True
            news['source_name'] = 'GitHub Trending'
            news['category_name'] = language if language else classify(repo_path, content)
            news['url'] = url
            news['cover_image'] = ''
            news['source_key'] = 'github'
            news['upstream_id'] = repo_path
            news['discovery_url'] = response.url
            news['content_kind'] = 'readme'
            yield news
