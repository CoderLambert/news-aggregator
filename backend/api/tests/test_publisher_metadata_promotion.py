from datetime import timedelta
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from api.models import News, NewsSourceItem, Favorite, ChatSession
from api.services.news_ingestion import ingest_item


def entry(source_key, source_name, **kwargs):
    value = dict(source_key=source_key, source_name=source_name, upstream_id='100',
        title='A shared link', summary='Community summary', category_name='科技',
        publish_time=timezone.now(), content_kind='article', url='https://dev.to/team/publisher-metadata')
    value.update(kwargs)
    return value


@pytest.mark.django_db
def test_official_publisher_promotes_hn_discovery_without_resetting_history():
    first = ingest_item(entry('hackernews', 'Hacker News', discovery_url='https://news.ycombinator.com/item?id=100'))
    news = News.objects.get(pk=first.news_id)
    user = get_user_model().objects.create_user('publisher-reader')
    saved = Favorite.objects.create(user=user, news=news, type='bookmark')
    chat = ChatSession.objects.create(user=user, news=news)
    news.full_content = 'Already verified publisher body'; news.full_content_state = 'legacy'
    news.full_content_revision = 4; news.title_zh = 'Old community headline translation'
    news.save(update_fields=['full_content', 'full_content_state', 'full_content_revision', 'title_zh'])
    published = timezone.now() - timedelta(days=2)
    official = entry('devto', 'Dev.to', upstream_id='publisher-17', title='Publisher headline',
        summary='Official publisher summary', category_name='开发工具', publish_time=published, author='Publisher author')
    result = ingest_item(official)
    news.refresh_from_db()
    assert result.news_id == news.pk and result.changed
    assert news.source.name == 'Dev.to' and news.title == 'Publisher headline'
    assert news.category.name == '开发工具' and news.content == 'Official publisher summary'
    assert news.publish_time == published and news.title_zh == ''
    assert news.full_content_revision == 4 and news.full_content == 'Already verified publisher body'
    assert Favorite.objects.get(pk=saved.pk).news_id == news.pk
    assert ChatSession.objects.get(pk=chat.pk).news_id == news.pk
    assert news.source_items.count() == 2
    assert news.source_items.get(source_key='devto').metadata['publisher_promotion']['from_source_key'] == 'hackernews'
    assert not ingest_item(official).changed
    ingest_item(entry('hackernews', 'Hacker News', title='Community edited headline'))
    news.refresh_from_db(); assert news.title == 'Publisher headline'


@pytest.mark.django_db
def test_unknown_or_wrong_domain_cannot_promote_publisher():
    first = ingest_item(entry('hackernews', 'Hacker News'))
    refused = ingest_item(entry('webkit', 'WebKit', title='Unrelated publisher'))
    assert refused.receipt_outcome == 'policy_skip'
    assert News.objects.get(pk=first.news_id).source.name == 'Hacker News'
