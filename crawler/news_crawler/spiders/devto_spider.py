import scrapy
from datetime import datetime
from news_crawler.items import NewsItem


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
        import json
        try:
            articles = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            return

        for article in articles:
            title = article.get('title', '')
            url = article.get('url', '')
            if not title or not url:
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

            category = '科技'
            if tags:
                tag_lower = [t.lower() for t in tags]
                if any(t in tag_lower for t in ['webdev', 'javascript', 'typescript', 'react', 'vue']):
                    category = '前端'
                elif any(t in tag_lower for t in ['python', 'go', 'rust', 'java', 'backend']):
                    category = '后端'
                elif any(t in tag_lower for t in ['devops', 'cloud', 'aws', 'docker', 'kubernetes']):
                    category = 'DevOps'
                elif any(t in tag_lower for t in ['ai', 'machinelearning', 'datascience']):
                    category = 'AI'

            news = NewsItem()
            news['title'] = title
            news['content'] = content
            news['author'] = author
            news['publish_time'] = publish_time
            news['source_name'] = 'Dev.to'
            news['category_name'] = category
            news['url'] = url
            news['cover_image'] = cover_image
            yield news
