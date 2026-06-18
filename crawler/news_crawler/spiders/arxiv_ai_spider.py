import scrapy
import re
from datetime import datetime
from news_crawler.items import NewsItem


class ArxivAiSpider(scrapy.Spider):
    """arXiv AI/ML/NLP papers — Atom API feed."""
    name = 'arxiv_ai'
    allowed_domains = ['arxiv.org', 'export.arxiv.org']
    start_urls = [
        'https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=50',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
    }

    def parse(self, response):
        response.selector.remove_namespaces()
        for entry in response.css('entry'):
            title = entry.css('title::text').get('')
            if not title:
                continue

            # Atom link with rel="alternate"
            link = entry.css('link[rel="alternate"]::attr(href)').get('')
            if not link:
                link = entry.css('link::attr(href)').get('')
            if not link:
                continue

            summary = entry.css('summary::text').get('') or ''
            summary = re.sub(r'\s+', ' ', summary).strip()

            author = entry.css('author name::text').getall()
            author_str = ', '.join(a.strip() for a in author if a.strip())

            published = entry.css('published::text').get('')
            updated = entry.css('updated::text').get('')

            publish_time = datetime.now()
            date_str = published or updated or ''
            if date_str:
                try:
                    publish_time = datetime.fromisoformat(date_str.strip()[:19])
                except (ValueError, TypeError):
                    try:
                        publish_time = datetime.strptime(date_str.strip()[:19], '%Y-%m-%dT%H:%M:%S')
                    except (ValueError, TypeError):
                        pass

            # arXiv categories/tags
            categories = entry.css('category::attr(term)').getall()
            cat_str = ', '.join(c for c in categories if c)

            content = summary
            if cat_str:
                content = f'{summary}\n\narXiv Categories: {cat_str}'
            if author_str:
                content = f'{content}\n\nAuthors: {author_str}'

            # Build a human-readable arXiv URL
            arxiv_id = link.split('/')[-1] if '/' in link else ''
            arxiv_url = f'https://arxiv.org/abs/{arxiv_id}' if arxiv_id else link

            news = NewsItem()
            news['title'] = title.strip()
            news['content'] = content
            news['author'] = author_str
            news['publish_time'] = publish_time
            news['source_name'] = 'arXiv'
            news['category_name'] = 'AI'  # All entries from this query are AI-related
            news['url'] = arxiv_url
            news['cover_image'] = ''
            yield news
