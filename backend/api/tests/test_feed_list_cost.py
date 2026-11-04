"""Feed list cost: history catalog reads and group membership stay bounded."""
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    BlockedNews, Category, ChannelGroup, ChannelGroupMember, ChannelSubscription,
    EngineEntryMap, News, NewsSourceItem, Source, SourcePublication,
)
from api.rss.access import with_authorized_source_counts
from api.services.channel_catalog import subscription_status
from api.tests.rss.reader_fixtures import public_rss_source


pytestmark = pytest.mark.django_db


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(uuid.uuid4()))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '7')


@pytest.fixture
def category(db):
    return Category.objects.create(name='Feed cost', slug='feed-cost')


def _story(source, category, suffix):
    return News.objects.create(
        title=f'Feed cost {suffix}', content='Summary paragraph', source=source, category=category,
        url=f'https://feed-cost.example/{suffix}', publish_time=timezone.now(),
    )


def _queries(client, path, params):
    with CaptureQueriesContext(connection) as captured:
        response = client.get(path, params)
    assert response.status_code == 200, response.data
    return response, captured.captured_queries


def test_history_catalog_does_not_scan_subscription_state_per_field(engine, category):
    ready = [public_rss_source(Source.objects.create(
        name=f'Ready {index}', url=f'https://ready.example/{index}')) for index in range(8)]
    legacy = Source.objects.create(name='WebKit', url='https://webkit.org')
    SourcePublication.objects.create(source=legacy, publication='public', owner='legacy', reading_policy='standard')
    pending = Source.objects.create(name='Pending channel', url='https://pending.example')
    SourcePublication.objects.create(source=pending, publication='public', owner='miniflux', reading_policy='standard')
    for index, source in enumerate(ready[:3]):
        _story(source, category, f'ready-{index}-a')
        _story(source, category, f'ready-{index}-b')
    _story(legacy, category, 'legacy')

    response, queries = _queries(APIClient(), '/api/sources/', {'purpose': 'history'})
    by_id = {row['id']: row for row in response.data}
    # Previously each of status, reason, can_subscribe, and rss_status repeated
    # the link/policy reads, and each source counted articles with its own
    # correlated scan. A few dozen channels was thousands of queries. Admission
    # data for the whole page is now one snapshot, not one scan per channel.
    from collections import Counter
    shapes = Counter(' '.join(query['sql'].split())[:90] for query in queries)
    assert len(queries) < 30, '\n'.join(f'{count} {shape}' for shape, count in shapes.most_common())
    config_scans = [query for query in queries if 'FROM "api_sourceconfig"' in query['sql']]
    assert len(config_scans) <= 2
    assert not any(query['sql'].startswith('SELECT "api_category"') for query in queries)
    for source in ready:
        row = by_id[source.id]
        assert row['news_count'] == (2 if source in ready[:3] else 0)
        assert (row['subscription_status'], row['subscription_reason']) == ('active', '')
        assert row['can_subscribe'] is True
        assert row['rss_status'] == 'ready'
    assert by_id[legacy.id]['news_count'] == 1
    assert by_id[legacy.id]['subscription_status'] == 'inactive'
    assert by_id[legacy.id]['rss_status'] == 'retired'
    assert by_id[pending.id]['subscription_reason'] == 'unconfigured_source'
    assert by_id[pending.id]['can_subscribe'] is False
    # A later single-source read still sees current rows; priming is not a cache.
    assert subscription_status(Source.objects.get(pk=ready[0].pk)) == ('active', '')


def test_source_counts_follow_the_reader_and_not_other_owners(engine, category):
    public = public_rss_source(Source.objects.create(name='Public counter', url='https://public-counter.example'))
    personal = Source.objects.create(name='Personal counter', url='https://personal-counter.example')
    SourcePublication.objects.create(source=personal, publication='personal', owner='miniflux', reading_policy='standard')
    _story(public, category, 'public')
    _story(personal, category, 'personal')
    owner = get_user_model().objects.create_user('counter-owner')
    ChannelSubscription.objects.create(user=owner, source=personal)
    anonymous = with_authorized_source_counts(None, Source.objects.filter(pk__in=[public.pk, personal.pk]))
    assert dict(anonymous.values_list('pk', 'rss_news_count')) == {public.pk: 1, personal.pk: 0}
    owned = with_authorized_source_counts(owner, Source.objects.filter(pk__in=[public.pk, personal.pk]))
    assert dict(owned.values_list('pk', 'rss_news_count')) == {public.pk: 1, personal.pk: 1}


def test_catalog_policy_queries_do_not_grow_per_binding_and_recheck_revocation(engine):
    from api.rss.models import SourceFeedLink
    ready = [public_rss_source(Source.objects.create(
        name=f'Batch policy {index}', url=f'https://batch.example/{index}')) for index in range(2)]
    _, small = _queries(APIClient(), '/api/sources/', {'purpose': 'history'})
    ready.extend(public_rss_source(Source.objects.create(
        name=f'Batch policy {index}', url=f'https://batch.example/{index}')) for index in range(2, 18))
    response, large = _queries(APIClient(), '/api/sources/', {'purpose': 'history'})
    assert len(large) <= len(small) + 1
    assert all(row['can_subscribe'] for row in response.data if row['id'] in {s.pk for s in ready})
    # Even a disabled link to a restricted source must still constrain a shared binding.
    forbidden = Source.objects.create(name='Restricted shared feed', url='https://www.reuters.com/rss')
    SourcePublication.objects.create(source=forbidden, publication='personal', owner='miniflux')
    SourceFeedLink.objects.create(source=forbidden, binding=ready[0].feed_links.get().binding,
                                 enabled=False, association_policy={'version': 1, 'mode': 'all'})
    response, _ = _queries(APIClient(), '/api/sources/', {'purpose': 'history'})
    assert next(row for row in response.data if row['id'] == ready[0].pk)['can_subscribe'] is False


def test_keyword_list_builds_reader_access_once(engine, category):
    from unittest.mock import patch
    from api.rss.access import annotate_article_access
    source = public_rss_source(Source.objects.create(name='Single read', url='https://single.example'))
    article = _story(source, category, 'single-read')
    with patch('api.views.annotate_article_access', wraps=annotate_article_access) as annotate:
        response, _ = _queries(APIClient(), '/api/news/', {'page_size': 20})
    assert [row['id'] for row in response.data['results']] == [article.pk]
    assert annotate.call_count == 1


def test_default_feed_can_filter_duplicates_in_publish_order(engine, category):
    from api.views import NewsListView
    from rest_framework.test import APIRequestFactory
    source = public_rss_source(Source.objects.create(name='Ordered read', url='https://ordered.example'))
    _story(source, category, 'ordered-read')
    view = NewsListView()
    view.request = view.initialize_request(APIRequestFactory().get('/api/news/'))
    plan = view.filter_queryset(view.get_queryset())[:20].explain()
    assert 'USE TEMP B-TREE FOR ORDER BY' not in plan


def test_source_counts_deduplicate_overlapping_membership_paths(engine, category):
    source = public_rss_source(Source.objects.create(name='WebKit', url='https://webkit.org'))
    article = _story(source, category, 'overlapping-paths')
    NewsSourceItem.objects.create(source_key='webkit', upstream_id='overlapping-paths',
                                 news=article, discovery_url=article.url)
    EngineEntryMap.objects.create(binding=source.feed_links.get().binding,
        engine_entry_id=article.pk, news=article, source_url=article.url, disposition='linked')
    counts = with_authorized_source_counts(None, Source.objects.filter(pk=source.pk))
    assert counts.get().rss_news_count == 1


def test_group_feed_uses_source_membership_and_keeps_reader_filters(engine, category):
    user = get_user_model().objects.create_user('group-reader')
    outside = public_rss_source(Source.objects.create(name='Outside', url='https://outside.example'))
    grouped = public_rss_source(Source.objects.create(name='Grouped', url='https://grouped.example'))
    webkit = Source.objects.create(name='WebKit', url='https://webkit.org')
    SourcePublication.objects.create(source=webkit, publication='public', owner='legacy', reading_policy='standard')
    outside_story = _story(outside, category, 'outside')
    grouped_story = _story(grouped, category, 'grouped')
    legacy_story = _story(outside, category, 'legacy-member')
    NewsSourceItem.objects.create(
        source_key='webkit', upstream_id='legacy-member', news=legacy_story,
        discovery_url=legacy_story.url,
    )
    engine_story = _story(outside, category, 'engine-member')
    link = grouped.feed_links.select_related('binding').get()
    EngineEntryMap.objects.create(
        binding=link.binding, engine_entry_id=engine_story.pk, news=engine_story,
        source_url=engine_story.url, disposition='linked',
    )
    duplicate = _story(grouped, category, 'duplicate')
    duplicate.related_to = grouped_story
    duplicate.save(update_fields=['related_to'])
    blocked = _story(grouped, category, 'blocked')
    BlockedNews.objects.create(user=user, news=blocked)
    subscriptions = [
        ChannelSubscription.objects.create(user=user, source=source) for source in (grouped, webkit)
    ]
    group = ChannelGroup.objects.create(user=user, name='人工智能')
    ChannelGroupMember.objects.bulk_create([
        ChannelGroupMember(group=group, subscription=subscription) for subscription in subscriptions
    ])

    client = APIClient()
    client.force_authenticate(user)
    response, queries = _queries(client, '/api/news/', {
        'page': 1, 'page_size': 20, 'scope': 'group', 'group_id': group.pk, 'representation': 'summary',
    })
    assert {row['id'] for row in response.data['results']} == {grouped_story.pk, legacy_story.pk, engine_story.pk}
    assert outside_story.pk not in {row['id'] for row in response.data['results']}
    count_sql = next(query['sql'] for query in queries if 'COUNT(*)' in query['sql'])
    assert 'UNION' in count_sql
    assert '_rss_body_grant' not in count_sql
