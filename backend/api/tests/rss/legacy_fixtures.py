"""Explicit legacy public-source fixtures for pre-migration endpoint regressions."""
from api.models import News, SourcePublication


def public_legacy(source):
    SourcePublication.objects.update_or_create(source=source, defaults={
        'publication': 'public', 'owner': 'legacy', 'reading_policy': 'standard'})
    return source


def legacy_news(**values):
    source = public_legacy(values['source'])
    values.setdefault('body_owner_source', source)
    return News.objects.create(**values)


def ingest_fixture(item, **kwargs):
    # These unit fixtures model acquisition completed under a pre-captured source
    # token. Tests of stale tokens use the actual explicit service APIs instead.
    from api.rss.legacy_fencing import capture_source_token
    from api.services.news_ingestion import ingest_item
    token = capture_source_token(item['source_key'])
    return ingest_item(item, legacy_token=token, **kwargs)
