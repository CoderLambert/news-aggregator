import hashlib
import os
import sys
import django
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.utils.timezone import now as tz_now

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
django.setup()

from django.db import close_old_connections
from api.models import Category, News, Source
from api.services.translator import translate, is_chinese


SOURCE_DEFAULTS = {
    'Hacker News': {'url': 'https://news.ycombinator.com', 'country': 'US', 'language': 'en', 'source_type': 'discussion'},
    'BBC': {'url': 'https://www.bbc.com', 'country': 'UK', 'language': 'en', 'source_type': 'news'},
    'Reuters': {'url': 'https://www.reuters.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'GitHub Trending': {'url': 'https://github.com/trending', 'country': 'US', 'language': 'en', 'source_type': 'aggregator'},
    'Dev.to': {'url': 'https://dev.to', 'country': 'US', 'language': 'en', 'source_type': 'discussion'},
    'TechCrunch': {'url': 'https://techcrunch.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'ProductHunt': {'url': 'https://www.producthunt.com', 'country': 'US', 'language': 'en', 'source_type': 'aggregator'},
    # Frontend Development Sources
    'CSS-Tricks': {'url': 'https://css-tricks.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'web.dev': {'url': 'https://web.dev', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Chrome Developers': {'url': 'https://developer.chrome.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Smashing Magazine': {'url': 'https://www.smashingmagazine.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'React Blog': {'url': 'https://react.dev', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Svelte Blog': {'url': 'https://svelte.dev', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Angular Blog': {'url': 'https://blog.angular.dev', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'WebKit': {'url': 'https://webkit.org', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'V8': {'url': 'https://v8.dev', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Mozilla Hacks': {'url': 'https://hacks.mozilla.org', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Frontend Focus': {'url': 'https://frontendfoc.us', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    # AI Company Blogs
    'OpenAI Blog': {'url': 'https://openai.com/news', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Anthropic': {'url': 'https://www.anthropic.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'DeepMind': {'url': 'https://deepmind.google', 'country': 'UK', 'language': 'en', 'source_type': 'news'},
    'Meta AI': {'url': 'https://ai.meta.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Mistral': {'url': 'https://mistral.ai', 'country': 'FR', 'language': 'en', 'source_type': 'news'},
    # AI Specialized Media
    'VentureBeat AI': {'url': 'https://venturebeat.com/category/ai/', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'Ars Technica AI': {'url': 'https://arstechnica.com/tag/artificial-intelligence/', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    'MIT Tech Review AI': {'url': 'https://www.technologyreview.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    # AI Papers
    'arXiv': {'url': 'https://arxiv.org', 'country': 'US', 'language': 'en', 'source_type': 'aggregator'},
    # Software Engineering & Architecture
    'InfoQ': {'url': 'https://www.infoq.com', 'country': 'US', 'language': 'en', 'source_type': 'news'},
    # Chinese AI News
    '机器之心': {'url': 'https://www.jiqizhixin.com', 'country': 'CN', 'language': 'zh', 'source_type': 'news'},
    '量子位': {'url': 'https://www.leiphone.com', 'country': 'CN', 'language': 'zh', 'source_type': 'news'},
    '36氪': {'url': 'https://36kr.com', 'country': 'CN', 'language': 'zh', 'source_type': 'news'},
}


def _title_hash(title):
    import hashlib
    return int(hashlib.md5(title.lower().strip().encode()).hexdigest()[:8], 16)


def _find_similar_titles(title, exclude_id=None, threshold=0.65):
    """Use vector embeddings to find near-duplicate titles."""
    try:
        from api.services.vector_store import VectorStoreService
        results = VectorStoreService().search(title, n=5)
    except Exception:
        return None

    if not results:
        return None

    news_ids = News.objects.filter(id__in=[r[0] for r in results]).values_list('id', 'title')
    id_to_title = {nid: t for nid, t in news_ids}

    for nid, distance in results:
        if exclude_id and nid == exclude_id:
            continue
        if distance > threshold:
            continue
        similar_title = id_to_title.get(nid)
        if not similar_title:
            continue
        # Additional character-level check for confidence
        t1 = title.lower().strip()
        t2 = similar_title.lower().strip()
        if len(t1) < 5 or len(t2) < 5:
            continue
        # Simple overlap: shared words ratio
        words1 = set(t1.split())
        words2 = set(t2.split())
        if not words1 or not words2:
            continue
        overlap = len(words1 & words2) / min(len(words1), len(words2))
        if overlap >= 0.7:
            return nid

    return None


def _index_news(news_id, title, content):
    try:
        from api.services.vector_store import VectorStoreService
        text = title
        if content:
            text = title + ' ' + content[:500]
        VectorStoreService().add_news(news_id, text)
    except Exception:
        pass


def _try_translate(news):
    """Try to translate English news to Chinese if not already translated.
    Records translation status on the news object.
    """
    if not news.title or is_chinese(news.title):
        news.translation_status = 'success'
        news.save(update_fields=['translation_status'])
        return

    if news.title_zh:
        news.translation_status = 'success'
        news.save(update_fields=['translation_status'])
        return  # Already translated

    # Mark as translating
    news.translation_status = 'translating'
    news.last_translation_attempt = tz_now()
    news.save(update_fields=['translation_status', 'last_translation_attempt'])

    try:
        title_zh, err_type, err_msg = translate(news.title, src="en", tgt="zh-CN")
        if title_zh:
            news.title_zh = title_zh
            if news.content and not is_chinese(news.content) and not news.content_zh:
                content_zh, c_err_type, c_err_msg = translate(
                    news.content, src="en", tgt="zh-CN"
                )
                if content_zh:
                    news.content_zh = content_zh

            news.translation_status = 'success'
            news.translation_error = ''
            news.save(update_fields=[
                'title_zh', 'content_zh', 'translation_status', 'translation_error'
            ])
        else:
            # Translation returned empty result with error
            # Map 'unknown' error type to 'failed' status
            news.translation_status = 'failed' if err_type == 'unknown' else err_type
            news.translation_error = err_msg or 'Translation returned empty result'
            news.save(update_fields=['translation_status', 'translation_error'])

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Translation failed for news {news.id}: {e}")
        # Classify the error
        err_str = str(e).lower()
        if any(kw in err_str for kw in ["network is unreachable", "connection refused",
                                         "no address associated"]):
            news.translation_status = 'network_error'
        elif "timed out" in err_str or "timeout" in err_str:
            news.translation_status = 'network_error'
        else:
            news.translation_status = 'failed'
        news.translation_error = str(e)
        news.save(update_fields=['translation_status', 'translation_error'])


@sync_to_async
def _save_item(item):
    close_old_connections()

    source_name = item['source_name']
    defaults = SOURCE_DEFAULTS.get(
        source_name,
        {'url': '', 'country': 'CN', 'language': 'zh', 'source_type': 'news'},
    )
    source, _ = Source.objects.get_or_create(
        name=source_name,
        defaults=defaults,
    )
    # Sync source_type and language if source already exists but fields are empty or outdated
    needs_save = False
    if not source.source_type:
        source.source_type = defaults['source_type']
        needs_save = True
    if not source.language or source.language != defaults['language']:
        source.language = defaults['language']
        needs_save = True
    if needs_save:
        source.save()

    category, _ = Category.objects.get_or_create(
        name=item['category_name'],
        defaults={'slug': item['category_name'].lower().replace(' ', '-')},
    )

    title = item['title']
    content = item['content']
    url = item['url']
    thash = _title_hash(title)

    # Use filter().first() instead of get(): a URL may appear more than once
    # (e.g. duplicate dev.to articles), and get() raises MultipleObjectsReturned.
    news = News.objects.filter(url=url).first()

    # If URL changed (e.g. Google News redirect -> real Reuters URL),
    # fall back to matching by title_hash + source
    if news is None and thash is not None:
        news = News.objects.filter(title_hash=thash, source=source).first()

    if news:
        # Update only if full article content is longer than existing
        if len(content) > len(news.content):
            # Update URL if it changed (e.g. Google News -> Reuters)
            if news.url != url:
                news.url = url
            news.content = content
            # Also update author and cover_image if newly available
            if item.get('author') and not news.author:
                news.author = item['author']
            if item.get('cover_image') and not news.cover_image:
                news.cover_image = item['cover_image']
            news.save()
            _index_news(news.id, news.title, news.content)
            _try_translate(news)
    else:
        # Cross-source dedup: check if a similar title already exists
        similar_id = _find_similar_titles(title, threshold=0.65)
        related_to_id = similar_id if similar_id else None

        news = News.objects.create(
            url=url,
            title=title,
            content=content,
            author=item.get('author', ''),
            publish_time=item.get('publish_time') or timezone.now(),
            source=source,
            category=category,
            cover_image=item.get('cover_image', ''),
            title_hash=thash,
            related_to_id=related_to_id,
        )
        _index_news(news.id, news.title, news.content)
        _try_translate(news)


class DjangoPipeline:
    async def process_item(self, item, spider):
        await _save_item(item)
        return item
