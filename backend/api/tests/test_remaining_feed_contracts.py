from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.test import override_settings
from django.utils import timezone
from api.models import Source, Category, News, NewsSourceItem
from api.services import feed_state
from api.services.article_fetcher.types import FullContentCandidate
from api.services.news_ingestion import ingest_item
from api.services.source_policy import POLICIES


@pytest.fixture
def item(db):
    return dict(source_key='devto', upstream_id='991', title='A publisher article',
                url='https://dev.to/reader/publisher-story', source_name='Dev.to',
                category_name='test-editorial', summary='Publisher summary', content_kind='article',
                publish_time=timezone.now() - timedelta(days=1))


def test_publisher_promotes_hn_discovery_without_replacing_article_or_history(item):
    first = ingest_item({**item, 'source_key': 'hackernews', 'source_name': 'Hacker News',
                         'upstream_id': '811', 'title': 'HN editorial headline', 'content_kind': 'discussion'})
    article = News.objects.get(pk=first.news_id)
    article.full_content = 'Known full text'
    article.full_content_zh = 'Known full translation'
    article.full_content_revision = 4
    article.save()
    result = ingest_item(item)
    article.refresh_from_db()
    assert result.news_id == first.news_id
    assert article.source.name == 'Dev.to' and article.title == item['title']
    assert article.content == item['summary'] and article.publish_time == item['publish_time']
    assert article.full_content_revision == 4 and article.full_content_zh == 'Known full translation'
    assert article.source_items.count() == 2
    assert NewsSourceItem.objects.get(news=article, source_key='hackernews').upstream_id == '811'
    assert not ingest_item(item).changed


def test_undated_replay_preserves_known_publisher_time(item):
    result = ingest_item(item)
    ingest_item({**item, 'publish_time': None, 'publish_time_inferred': True})
    article = News.objects.get(pk=result.news_id)
    metadata = article.source_items.get(source_key='devto').metadata
    assert article.publish_time == item['publish_time']
    assert metadata['publish_time_inferred'] is False
    assert metadata['source_publish_time'] == item['publish_time'].isoformat()


@pytest.mark.parametrize('invalid', ['', True, [], {}])
def test_malformed_upstream_ids_do_not_mutate_existing_article(item, invalid):
    first = ingest_item(item)
    result = ingest_item({**item, 'upstream_id': invalid, 'title': 'Must not replace'})
    assert result.receipt_outcome == 'policy_skip'
    assert News.objects.get(pk=first.news_id).title == item['title']


def test_incomparable_body_records_one_review_without_overwriting_valid_text(item):
    def candidate(body):
        return FullContentCandidate(source_key='devto', source_item_id='991', target_url=item['url'],
            retrieved_from_url='https://dev.to/api/articles/991', declared_canonical_url=None,
            title=item['title'], content_kind='article', body_field='body_markdown', content_format='markdown',
            declared_completeness='full', raw_content=body, source_modified_at=None,
            source_version=None, request_started_at=timezone.now())
    with override_settings(STRUCTURED_BODY_INGEST_ENABLED=True, STRUCTURED_BODY_SOURCE_KEYS={'devto'},
                           FULL_CONTENT_AUTO_ENQUEUE_ENABLED=False):
        first = ingest_item({**item, 'body_candidate': candidate('Complete first publisher body.')})
        second = ingest_item({**item, 'body_candidate': candidate('A different complete publisher body.')})
        mapping = NewsSourceItem.objects.get(news_id=first.news_id, source_key='devto')
        review = mapping.metadata['body_review']
        ingest_item({**item, 'body_candidate': candidate('A different complete publisher body.')})
        mapping.refresh_from_db()
    article = News.objects.get(pk=first.news_id)
    assert second.reason == 'source_version_conflict'
    assert article.full_content == 'Complete first publisher body.' and article.full_content_revision == 1
    assert review == mapping.metadata['body_review']
    assert review['queue_result'] == 'operator_review_required'
    assert article.full_content_next_attempt_at is None


@pytest.mark.django_db
def test_display_text_keeps_validators_but_semantic_contract_invalidates_them():
    policy = POLICIES['webkit']
    context = feed_state.prepare_feed_request('webkit', policy.feed_url)
    assert feed_state.commit_feed_checkpoint(context, etag='"fixture"')
    with patch.dict(POLICIES, {'webkit': replace(policy, description='New display text')}):
        unchanged = feed_state.prepare_feed_request('webkit', policy.feed_url)
    assert ('If-None-Match', '"fixture"') in unchanged.headers
    with patch.dict(POLICIES, {'webkit': replace(policy, keyword_filter='new admitted subset')}):
        changed = feed_state.prepare_feed_request('webkit', policy.feed_url)
    assert changed.headers == ()
    assert changed.expected_revision > unchanged.expected_revision


@pytest.mark.django_db
@pytest.mark.parametrize('field,value', [('body_fields', ('description',)), ('html_allowed', False),
                                       ('contract_version', 'reviewed-v2'), ('reading_policy', 'summary_only')])
def test_each_content_contract_change_invalidates_signature(field, value):
    policy = POLICIES['webkit']
    before = feed_state.policy_signature('webkit')
    with patch.dict(POLICIES, {'webkit': replace(policy, **{field: value})}):
        assert before != feed_state.policy_signature('webkit')
