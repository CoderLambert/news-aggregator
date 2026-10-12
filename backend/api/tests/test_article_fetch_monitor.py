import json

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ArticleFetchEvent, Category, JinaFallbackPolicy, News, Source
from api.services.article_fetch_monitor import (
    monitor_dashboard,
    observe_jina_candidate,
    record_fetch_event,
    validate_policy_domain,
)
from api.services.article_fetcher.types import FetchResult


def _news() -> News:
    category = Category.objects.create(name='Monitor', slug='monitor')
    source = Source.objects.create(name='Monitor source', url='https://source.example.test')
    return News.objects.create(
        title='Monitored article',
        content='Summary',
        publish_time=timezone.now(),
        source=source,
        category=category,
        url='https://blocked.example.test/article?private=value',
        full_content_fetch_status='failed',
    )


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('Example.COM.', 'example.com'),
        ('www.example.com', 'example.com'),
        ('news.example.co.uk', 'news.example.co.uk'),
    ],
)
def test_validate_policy_domain_normalizes_exact_dns_names(value, expected):
    assert validate_policy_domain(value) == expected


@pytest.mark.parametrize(
    'value',
    [
        'https://example.com/article',
        'example.com:443',
        'user@example.com',
        '127.0.0.1',
        'localhost',
        'bad_label.example.com',
    ],
)
def test_validate_policy_domain_rejects_urls_addresses_and_invalid_names(value):
    with pytest.raises(ValueError):
        validate_policy_domain(value)


@pytest.mark.django_db
def test_observe_candidate_is_disabled_by_default_and_counts_fallback_hits():
    assert observe_jina_candidate('www.blocked.example.test') is False
    policy = JinaFallbackPolicy.objects.get(pk='blocked.example.test')
    assert policy.enabled is False
    assert policy.auto_discovered is True
    assert policy.failure_count == 1

    policy.enabled = True
    policy.save(update_fields=['enabled'])
    assert observe_jina_candidate('blocked.example.test') is True
    policy.refresh_from_db()
    assert policy.failure_count == 2


@pytest.mark.django_db
def test_record_fetch_event_persists_only_sanitized_diagnostics(caplog):
    news = _news()
    raw_error = 'request failed for https://blocked.example.test/article?token=secret-value'
    failures = [FetchResult(
        ok=False,
        provider='Unsafe Provider / Name',
        url=news.url,
        error=raw_error,
    )]

    record_fetch_event(
        url=news.url,
        news_id=news.pk,
        result=None,
        failures=failures,
        elapsed_ms=123,
    )

    event = ArticleFetchEvent.objects.get()
    assert event.domain == 'blocked.example.test'
    assert event.outcome == 'failed'
    assert event.provider == 'unsafe_provider_name'
    assert event.failure_codes == [{'provider': 'unsafe_provider_name', 'code': 'provider_error'}]
    assert event.elapsed_ms == 123
    serialized = json.dumps(event.failure_codes)
    assert 'secret-value' not in serialized
    assert '/article' not in serialized
    assert raw_error not in caplog.text
    assert 'secret-value' not in caplog.text


@pytest.mark.django_db
def test_monitor_dashboard_aggregates_failures_without_article_content():
    news = _news()
    JinaFallbackPolicy.objects.create(
        domain='blocked.example.test',
        enabled=False,
        auto_discovered=True,
        failure_count=3,
    )
    record_fetch_event(
        url=news.url,
        news_id=news.pk,
        result=None,
        failures=[FetchResult(
            ok=False,
            provider='scrapy_http',
            url=news.url,
            error='HTTP 429',
        )],
        elapsed_ms=450,
    )

    dashboard = monitor_dashboard(days=7)

    assert dashboard['summary'] == {
        'total': 1,
        'success': 0,
        'failed': 1,
        'success_rate': 0.0,
        'unresolved_articles': 1,
    }
    assert dashboard['top_failure_codes'] == [{'code': 'http_429', 'count': 1}]
    assert dashboard['recent_events'][0]['news_id'] == news.pk
    assert dashboard['recent_events'][0]['failure_codes'] == [
        {'provider': 'scrapy_http', 'code': 'http_429'},
    ]
    assert 'url' not in dashboard['recent_events'][0]
    assert 'content' not in dashboard['recent_events'][0]


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full')
def test_article_fetch_admin_requires_active_superuser_and_updates_policy():
    ordinary = User.objects.create_user(username='monitor-user', password='unused')
    admin = User.objects.create_superuser(
        username='monitor-admin',
        email='monitor@example.test',
        password='unused',
    )
    anonymous = APIClient()
    ordinary_client = APIClient()
    ordinary_client.force_authenticate(ordinary)
    admin_client = APIClient()
    admin_client.force_authenticate(admin)

    for client in (anonymous, ordinary_client):
        assert client.get('/api/admin/article-fetch/dashboard/').status_code == 403
        assert client.post(
            '/api/admin/article-fetch/policies/',
            {'domain': 'candidate.example.test'},
            format='json',
        ).status_code == 403

    created = admin_client.post(
        '/api/admin/article-fetch/policies/',
        {'domain': 'www.candidate.example.test'},
        format='json',
    )
    assert created.status_code == 201
    assert created.data['domain'] == 'candidate.example.test'
    assert created.data['enabled'] is False

    enabled = admin_client.patch(
        '/api/admin/article-fetch/policies/candidate.example.test/',
        {'enabled': True},
        format='json',
    )
    assert enabled.status_code == 200
    policy = JinaFallbackPolicy.objects.get(pk='candidate.example.test')
    assert policy.enabled is True
    assert policy.auto_discovered is False
    assert policy.updated_by == admin

    dashboard = admin_client.get('/api/admin/article-fetch/dashboard/?days=7')
    assert dashboard.status_code == 200
    assert dashboard.data['policies'][0]['domain'] == 'candidate.example.test'


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full')
def test_article_fetch_admin_rejects_unsafe_or_extra_policy_fields():
    admin = User.objects.create_superuser(
        username='policy-admin',
        email='policy@example.test',
        password='unused',
    )
    client = APIClient()
    client.force_authenticate(admin)

    response = client.post(
        '/api/admin/article-fetch/policies/',
        {'domain': 'https://127.0.0.1/private', 'enabled': True, 'url': 'secret'},
        format='json',
    )
    assert response.status_code == 400
    assert not JinaFallbackPolicy.objects.filter(pk='127.0.0.1').exists()
