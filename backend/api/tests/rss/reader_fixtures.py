"""Explicit legacy-public grants for pre-migration reader test fixtures."""
from hashlib import sha256
from api.models import LegacyTranslationSnapshot
from api.rss.models import SourcePublication


def public_legacy_article(news):
    SourcePublication.objects.update_or_create(source=news.source,
        defaults={'publication': 'public', 'owner': 'legacy', 'reading_policy': 'standard'})
    news.body_owner_source = news.source
    news.save(update_fields=['body_owner_source'])
    for field in ('title', 'content', 'full_content'):
        original, translated = getattr(news, field), getattr(news, field + '_zh')
        if translated:
            LegacyTranslationSnapshot.objects.get_or_create(news=news, field=field,
                source_hash=sha256(original.encode()).hexdigest(),
                translation_hash=sha256(translated.encode()).hexdigest(),
                defaults={'source_text': original, 'translated_text': translated, 'origin': 'legacy'})
    return news


def without_article_context(message):
    return {key: value for key, value in message.items() if key != 'article_context'}


def public_rss_source(source):
    """A synthetic connected Miniflux source; does not run engine/network work."""
    import uuid
    from api.rss.models import FeedBinding, SourceFeedLink
    SourcePublication.objects.update_or_create(source=source, defaults={
        'publication': 'public', 'owner': 'miniflux', 'reading_policy': 'standard'})
    if not SourceFeedLink.objects.filter(source=source).exists():
        binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=1,
            engine_feed_id=source.pk, canonical_feed_url=f'https://feed.example/{source.pk}',
            desired_enabled=True, connection_state='ready', applied_policy_version=1)
        SourceFeedLink.objects.create(source=source, binding=binding, enabled=True,
            association_policy={'version': 1, 'mode': 'all'})
    return source
