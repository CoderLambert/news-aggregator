import copy
import pytest
from django.utils import timezone
from api.models import Source, Category, News, NewsSourceItem
from api.services.category_corrections import build_plan, execute_plan, CorrectionConflict
from api.services.channel_catalog import catalog_defaults, sync_channel_catalog
from api.services.source_policy import POLICIES
from news_crawler.category_map import classify


@pytest.mark.parametrize('title,expected', [('Email from Main', '科技'), ('AI agent', 'AI'),
    ('An AI-driven future', 'AI'), ('使用AI改进体验', 'AI'), ('人工智能新闻', 'AI'),
    ('JavaScript and CSS', '前端'), ('Go server', '后端'), ('Google announces a release', '科技'),
    ('main thread', '科技'), ('ＲＥＡＣＴ hooks', '前端')])
def test_latin_keywords_do_not_match_inside_unrelated_words(title, expected):
    assert classify(title) == expected


@pytest.fixture
def article(db):
    source, _ = Source.objects.get_or_create(name='Dev.to', defaults={'url': 'https://dev.to'})
    category, _ = Category.objects.get_or_create(name='AI', defaults={'slug': 'ai'})
    news = News.objects.create(source=source, category=category, title='Email from Main', content='A routine update',
        url='https://dev.to/reader/email', publish_time=timezone.now(), full_content='retain body', full_content_zh='retain translation')
    mapping = NewsSourceItem.objects.create(news=news, source_key='devto', upstream_id='audit-1', discovery_url=news.url)
    return news, mapping


def test_dry_run_apply_replay_and_undo_preserve_article_content(article):
    news, mapping = article
    old = news.category_id
    plan = build_plan('devto')
    news.refresh_from_db()
    assert news.category_id == old and len(plan['rows']) == 1
    assert execute_plan(plan)['changed'] == 1
    assert execute_plan(plan)['changed'] == 0
    news.refresh_from_db()
    assert news.category.name == '科技'
    assert news.full_content == 'retain body' and news.full_content_zh == 'retain translation'
    assert execute_plan(plan, undo=True)['changed'] == 1
    assert execute_plan(plan, undo=True)['changed'] == 0
    news.refresh_from_db()
    assert news.category_id == old
    mapping.refresh_from_db()
    assert mapping.metadata['category_corrections'][0]['undone_at']


def test_changed_article_rejects_entire_plan_without_overwriting_manual_work(article):
    news, _ = article
    plan = build_plan('devto')
    News.objects.filter(pk=news.pk).update(title='AI agent correction by editor')
    with pytest.raises(CorrectionConflict):
        execute_plan(plan)
    news.refresh_from_db()
    assert news.title == 'AI agent correction by editor' and news.category.name == 'AI'


def test_plan_cannot_target_a_secondary_publisher(article):
    plan = build_plan('devto')
    plan['source_key'] = 'hackernews'
    with pytest.raises(CorrectionConflict):
        execute_plan(plan)


@pytest.mark.django_db
def test_unknown_country_is_not_inferred_from_market_and_existing_values_are_preserved():
    assert catalog_defaults(POLICIES['bbc_health'])['country'] == 'UK'
    assert catalog_defaults(POLICIES['pv_magazine_china'])['country'] == ''
    assert catalog_defaults(POLICIES['pv_magazine_global'])['country'] == ''
    source, _ = Source.objects.update_or_create(name='BBC Health', defaults={'url': 'https://www.bbc.com', 'country': 'CA'})
    sync_channel_catalog()
    source.refresh_from_db()
    assert source.country == 'CA'
