import json
from io import StringIO
import pytest
from django.core.management import call_command
from django.utils import timezone
from api.models import Source, Category, News, NewsSourceItem
from api.metadata_models import MetadataCorrectionAudit
from api.services.metadata_corrections import preview, apply, undo
from api.services.source_metadata import publisher_country, primary_publication_evidence
from news_crawler.category_map import classify


@pytest.mark.parametrize('title,expected', [('Email threading', '科技'), ('Main branch', '科技'),
    ('Rust compiler', '后端'), ('AI agents', 'AI'), ('LLM inference', 'AI'),
    ('人工智能技术', 'AI'), ('AI模型', 'AI'), ('A goal for tomorrow', '科技')])
def test_ascii_short_words_are_matched_at_token_boundaries(title, expected):
    assert classify(title) == expected


@pytest.fixture
def article(db):
    source, _ = Source.objects.get_or_create(name='Dev.to', defaults={'url': 'https://dev.to'})
    category, _ = Category.objects.get_or_create(name='AI', defaults={'slug': 'ai'})
    news = News.objects.create(source=source, category=category, title='Email threading', content='mail client behavior',
        url='https://dev.to/team/classifier-test', publish_time=timezone.now())
    NewsSourceItem.objects.create(source_key='devto', upstream_id='metadata-test', news=news,
        discovery_url=news.url, metadata={'category_name': 'AI', 'publish_time_inferred': True})
    return news


def test_preview_apply_replay_and_undo_are_bounded_and_audited(article):
    original_id, original_url = article.pk, article.url
    plan = preview('devto', 'news_category')
    assert len(plan['rows']) == 1 and plan['rows'][0]['after']['name'] == '科技'
    assert MetadataCorrectionAudit.objects.count() == 0
    assert News.objects.get(pk=article.pk).category.name == 'AI'
    result = apply(plan, operator='isolated-test')
    assert result['results'][0]['result'] == 'applied'
    assert apply(plan, operator='isolated-test')['results'][0]['result'] == 'already_applied'
    article.refresh_from_db(); assert article.category.name == '科技'
    assert article.pk == original_id and article.url == original_url
    assert MetadataCorrectionAudit.objects.count() == 1
    assert undo(plan['run_id'])['results'][0]['result'] == 'undone'
    article.refresh_from_db(); assert article.category.name == 'AI'
    assert undo(plan['run_id'])['results'][0]['result'] == 'already_undone'


def test_concurrent_manual_metadata_change_fails_closed(article):
    plan = preview('devto', 'news_category')
    News.objects.filter(pk=article.pk).update(title='AI actual topic')
    assert apply(plan, operator='test')['results'][0]['result'] == 'evidence_changed'
    assert MetadataCorrectionAudit.objects.count() == 0


def test_undo_does_not_erase_new_edits(article):
    plan = preview('devto', 'news_category'); apply(plan, operator='test')
    News.objects.filter(pk=article.pk).update(title='Edited since correction')
    assert undo(plan['run_id'])['results'][0]['result'] == 'evidence_changed'


def test_cli_is_dry_run_unless_explicitly_executed(article, tmp_path):
    target = tmp_path / 'review.json'
    call_command('correct_article_metadata', source_key='devto', output=str(target), stdout=StringIO())
    assert target.exists() and (target.stat().st_mode & 0o777) == 0o600
    assert MetadataCorrectionAudit.objects.count() == 0
    call_command('correct_article_metadata', plan=str(target), stdout=StringIO())
    assert MetadataCorrectionAudit.objects.count() == 0


def test_unknown_country_and_secondary_discovery_do_not_claim_publisher_evidence(article):
    assert publisher_country('bbc_health') == 'GB'
    assert publisher_country('pv_magazine_china') == ''
    assert publisher_country('unregistered') == ''
    NewsSourceItem.objects.create(source_key='hackernews', upstream_id='hn', news=article,
        discovery_url='https://news.ycombinator.com/item?id=12',
        metadata={'publish_time_inferred': False, 'source_publish_time': timezone.now().isoformat()})
    assert primary_publication_evidence(article)['inferred'] is True
    article.source_items.filter(source_key='devto').update(metadata={'publish_time_inferred': False,
        'source_publish_time': timezone.now().isoformat()})
    assert primary_publication_evidence(article)['origin'] == 'publisher'


@pytest.mark.django_db
def test_country_correction_changes_only_reviewed_field_and_can_undo():
    source, _ = Source.objects.update_or_create(name='BBC Health', defaults={'url': 'https://feeds.bbci.co.uk/news/health/rss.xml', 'country': 'US'})
    plan = preview('bbc_health', 'source_country')
    assert plan['rows'][0]['after'] == {'country': 'GB'}
    apply(plan, operator='test'); source.refresh_from_db(); assert source.country == 'GB'
    undo(plan['run_id']); source.refresh_from_db(); assert source.country == 'US'
