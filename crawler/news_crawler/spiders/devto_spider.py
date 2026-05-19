import scrapy
import json
from datetime import datetime
from news_crawler.items import NewsItem
from news_crawler.category_map import classify


class DevToSpider(scrapy.Spider):
    name = 'devto'
    allowed_domains = ['dev.to']
    start_urls = [
        'https://dev.to/api/articles?top=50',
        'https://dev.to/api/articles?per_page=50&tag=python',
        'https://dev.to/api/articles?per_page=50&tag=javascript',
    ]

    custom_settings = {
        'DOWNLOAD_DELAY': 1,
        'CONCURRENT_REQUESTS_PER_DOMAIN': 3,
    }

    def parse(self, response):
        try:
            articles = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            return

        for article in articles:
            title = article.get('title', '')
            url = article.get('url', '')
            article_id = article.get('id')
            if not title or not url or not article_id:
                continue

            description = article.get('description', '') or ''
            positive_reactions = article.get('positive_reactions_count', 0)
            comments = article.get('comments_count', 0)
            tags = article.get('tag_list', [])
            cover_image = article.get('cover_image', '') or ''
            author = article.get('user', {}).get('name', '') or article.get('user', {}).get('username', '')

            content_parts = []
            if description:
                content_parts.append(description)
            content_parts.append(f'Reactions: {positive_reactions} | Comments: {comments}')
            if tags:
                content_parts.append(f'Tags: {", ".join(tags)}')
            content = '\n'.join(content_parts)

            published_at = article.get('published_at', '')
            publish_time = datetime.now()
            if published_at:
                try:
                    publish_time = datetime.fromisoformat(published_at.replace('Z', '+00:00')).replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            news = NewsItem()
            news['title'] = title
            news['content'] = content
            news['author'] = author
            news['publish_time'] = publish_time
            news['source_name'] = 'Dev.to'
            news['category_name'] = classify(title, description + ' ' + ' '.join(tags))
            news['url'] = url
            news['cover_image'] = cover_image
            yield news

            # Fetch full body markdown via API
            yield scrapy.Request(
                f'https://dev.to/api/articles/{article_id}',
                callback=self.parse_article,
                priority=1,
            )

    def parse_article(self, response):
        try:
            article = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            return

        title = article.get('title', '')
        body_markdown = article.get('body_markdown', '')
        if not title or not body_markdown:
            return

        author = article.get('user', {}).get('name', '') or article.get('user', {}).get('username', '')
        published_at = article.get('published_at', '')
        cover_image = article.get('cover_image', '') or ''
        tags = article.get('tag_list', [])

        if len(body_markdown) > 5000:
            body_markdown = body_markdown[:5000]

        publish_time = datetime.now()
        if published_at:
            try:
                publish_time = datetime.fromisoformat(published_at.replace('Z', '+00:00')).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        news = NewsItem()
        news['title'] = title
        news['content'] = body_markdown
        news['author'] = author
        news['publish_time'] = publish_time
        news['source_name'] = 'Dev.to'
        news['category_name'] = classify(title, body_markdown[:500] + ' ' + ' '.join(tags))
        news['url'] = article.get('url', '')
        news['cover_image'] = cover_image
        yield news
