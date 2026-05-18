import os
import sys
import django
from asgiref.sync import sync_to_async
from django.utils import timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
django.setup()

from django.db import close_old_connections
from api.models import Category, Source, News


def _index_news(news_id, title, content):
    try:
        from api.services.vector_store import VectorStoreService
        text = title
        if content:
            text = title + ' ' + content[:500]
        VectorStoreService().add_news(news_id, text)
    except Exception:
        pass


@sync_to_async
def _save_item(item):
    close_old_connections()

    SOURCE_DEFAULTS = {
        'Hacker News': {'url': 'https://news.ycombinator.com', 'country': 'US', 'language': 'en'},
        'BBC': {'url': 'https://www.bbc.com', 'country': 'UK', 'language': 'en'},
        'Reuters': {'url': 'https://www.reuters.com', 'country': 'US', 'language': 'en'},
        'GitHub Trending': {'url': 'https://github.com/trending', 'country': 'US', 'language': 'en'},
        'Dev.to': {'url': 'https://dev.to', 'country': 'US', 'language': 'en'},
        'TechCrunch': {'url': 'https://techcrunch.com', 'country': 'US', 'language': 'en'},
        'ProductHunt': {'url': 'https://www.producthunt.com', 'country': 'US', 'language': 'en'},
    }
    defaults = SOURCE_DEFAULTS.get(
        item['source_name'],
        {'url': '', 'country': 'CN', 'language': 'zh'},
    )
    source, _ = Source.objects.get_or_create(
        name=item['source_name'],
        defaults=defaults,
    )

    category, _ = Category.objects.get_or_create(
        name=item['category_name'],
        defaults={'slug': item['category_name'].lower().replace(' ', '-')},
    )

    try:
        news = News.objects.get(url=item['url'])
        if len(item.get('content', '')) > len(news.content):
            news.content = item['content']
            news.save()
            _index_news(news.id, news.title, news.content)
    except News.DoesNotExist:
        news = News.objects.create(
            url=item['url'],
            title=item['title'],
            content=item['content'],
            author=item.get('author', ''),
            publish_time=item.get('publish_time') or timezone.now(),
            source=source,
            category=category,
            cover_image=item.get('cover_image', ''),
        )
        _index_news(news.id, news.title, news.content)


class DjangoPipeline:
    async def process_item(self, item, spider):
        await _save_item(item)
        return item
