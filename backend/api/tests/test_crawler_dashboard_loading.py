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
