"""The admin dashboard must stay bounded as crawl history grows."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIRequestFactory, force_authenticate

from api.crawler_serializers import CrawlBatchSerializer, CrawlRunSerializer
from api.crawler_views import CrawlerDashboardView, batch_queryset
from api.models import CrawlBatch, CrawlRun, CrawlerTarget
from api.services.crawler_control import sync_crawler_targets


pytestmark = pytest.mark.django_db


def test_run_history_reads_source_registry_once_per_response():
    target = CrawlerTarget.objects.create(spider_name='webkit', display_name='WebKit')
    batches = [CrawlBatch.objects.create(trigger='manual') for _ in range(2)]
    CrawlRun.objects.bulk_create([
        CrawlRun(batch=batch, target=target, status='succeeded')
        for batch in batches for _ in range(30)
    ])
    with patch('api.services.source_registry.runtime_registry', return_value={'webkit': object()}) as registry:
        data = CrawlBatchSerializer(batch_queryset(), many=True).data
    assert sum(len(batch['runs']) for batch in data) == 60
    assert all(run['source_active'] for batch in data for run in batch['runs'])
    assert registry.call_count == 1

    # A later response sees source retirement rather than a process-wide cache.
    with patch('api.services.source_registry.runtime_registry', return_value={}):
        data = CrawlBatchSerializer(batch_queryset(), many=True).data
    assert not any(run['source_active'] for batch in data for run in batch['runs'])


def test_sync_unchanged_targets_does_not_rewrite_or_query_each_source():
    registry = {
        f'fixture_{i}': SimpleNamespace(display_name=f'Fixture {i}', maintenance='code')
        for i in range(60)
    }
    with patch('api.services.crawler_control.runtime_registry', return_value=registry):
        sync_crawler_targets()
        CrawlerTarget.objects.filter(pk='fixture_0').update(enabled=False)
        with CaptureQueriesContext(connection) as queries:
            sync_crawler_targets()
        assert len(queries) <= 4
        assert all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries)
        assert not CrawlerTarget.objects.get(pk='fixture_0').enabled
        registry['fixture_0'] = SimpleNamespace(display_name='Renamed', maintenance='code')
        sync_crawler_targets()
    target = CrawlerTarget.objects.get(pk='fixture_0')
    assert target.display_name == 'Renamed'
    assert not target.enabled


def test_dashboard_summarizes_stats_but_run_details_keep_full_counters():
    sync_crawler_targets()
    target = CrawlerTarget.objects.get(pk='webkit')
    batch = CrawlBatch.objects.create(trigger='manual')
    stats = {
        'finish_reason': 'finished', 'outcome': 'updated',
        'entries_committed': 3, 'entries_changed': 2,
        'warnings': ['robots_unavailable'],
        'request_failures_by_reason': {'timeout': 7},
    }
    run = CrawlRun.objects.create(batch=batch, target=target, status='succeeded', stats=stats)
    request = APIRequestFactory().get('/api/admin/crawler/dashboard/')
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, is_active=True, is_superuser=True))
    response = CrawlerDashboardView.as_view()(request)
    assert response.status_code == 200
    result = next(r for b in response.data['recent_batches'] for r in b['runs'] if r['id'] == str(run.pk))
    assert result['source_active'] is True
    assert result['stats'] == {key: value for key, value in stats.items() if key != 'request_failures_by_reason'}
    assert CrawlRunSerializer(run).data['stats'] == stats


def admin_request(path):
    request = APIRequestFactory().get(path)
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, is_active=True, is_superuser=True))
    return request


def test_light_dashboard_does_not_load_history():
    sync_crawler_targets()
    with patch('api.crawler_views.batch_queryset', side_effect=AssertionError('history queried')):
        response = CrawlerDashboardView.as_view()(admin_request('/?include_history=0'))
    assert response.status_code == 200
    assert response.data['recent_batches'] == []
    assert response.data['targets']


def test_recent_history_is_bounded_and_summarized():
    from api.crawler_views import CrawlBatchListCreateView
    target = CrawlerTarget.objects.create(spider_name='webkit', display_name='WebKit')
    for _ in range(10):
        batch = CrawlBatch.objects.create(trigger='manual')
        CrawlRun.objects.create(batch=batch, target=target, status='succeeded',
                                stats={'outcome': 'updated', 'unused_large_counter': 'x' * 1000})
    response = CrawlBatchListCreateView.as_view()(admin_request('/?page_size=8&summary=1'))
    assert response.status_code == 200
    assert response.data['count'] == 10
    assert len(response.data['results']) == 8
    assert response.data['results'][0]['runs'][0]['stats'] == {'outcome': 'updated'}


def test_source_monitoring_queries_are_bounded_and_keep_latest_values():
    from datetime import timedelta
    from django.utils import timezone
    from api.models import Category, Source, News, NewsSourceItem, FeedState
    from api.crawler_views import SourceConfigListCreateView
    from api.services.crawler_control import get_crawler_settings
    get_crawler_settings()
    sync_crawler_targets()
    source = Source.objects.create(name='Perf fixture', url='https://example.com')
    category = Category.objects.first()
    now = timezone.now()
    target = CrawlerTarget.objects.get(pk='webkit')
    batch = CrawlBatch.objects.create(trigger='manual')
    CrawlRun.objects.create(batch=batch, target=target, status='succeeded', finished_at=now - timedelta(hours=1))
    CrawlRun.objects.create(batch=batch, target=target, status='failed', http_statuses={'503': 2}, finished_at=now)
    for i in range(2):
        article = News.objects.create(title=f'Article {i}', content='summary', full_content='body' * 1000,
                                      publish_time=now + timedelta(minutes=i), source=source, category=category,
                                      url=f'https://example.com/{i}')
        NewsSourceItem.objects.create(source_key='webkit', upstream_id=str(i), news=article,
                                     discovery_url=article.url)
    FeedState.objects.create(source_key='webkit', feed_url='https://webkit.org/feed/',
                             last_success_at=now, next_poll_at=now + timedelta(hours=2))
    with CaptureQueriesContext(connection) as queries:
        response = SourceConfigListCreateView.as_view()(admin_request('/'))
    assert response.status_code == 200
    assert len(response.data) > 30
    assert len(queries) <= 12
    monitoring = next(row['monitoring'] for row in response.data if row['source_key'] == 'webkit')
    assert monitoring['latest_article']['title'] == 'Article 1'
    assert monitoring['last_success_at'] == now - timedelta(hours=1)
    assert monitoring['last_http_statuses'] == {'503': 2}
    assert monitoring['last_feed_success_at'] == now
    assert not any('"api_news"."full_content"' in query['sql'] for query in queries)



def test_index_dashboard_reuses_audit_until_worker_completes():
    from datetime import timedelta
    from django.core.cache import cache
    from django.utils import timezone
    from api.search_index_views import dashboard_index_audit
    cache.clear()
    settings = SimpleNamespace(active_collection='test', model_name='model', schema_version='1', last_success_at=None)
    audit = SimpleNamespace(available=True)
    with patch('api.search_index_views.audit_search_index', return_value=audit) as scan:
        assert dashboard_index_audit(settings).available
        assert dashboard_index_audit(settings).available
        assert scan.call_count == 1
        settings.last_success_at = timezone.now() + timedelta(seconds=1)
        dashboard_index_audit(settings)
        assert scan.call_count == 2
    cache.clear()
