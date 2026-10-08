from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient, override_settings
from django.utils import timezone

from api.management.commands.auto_fetch_full_content import _fetch_one
from api.models import Category, News, Source
from api.services.article_fetcher import FetchError, FetchResult


@pytest.fixture
def src(db):
    return Source.objects.create(name='TestSource', url='https://example.com', language='en')


@pytest.fixture
def cat(db):
    return Category.objects.create(name='科技', slug='tech')


def _news(src, cat, **overrides):
    defaults = dict(
        title='测试文章标题',
        content='这是一段已有摘要内容，但不能冒充原文。',
        publish_time=timezone.now(),
        source=src,
        category=cat,
        url='https://example.com/article',
    )
    defaults.update(overrides)
    return News.objects.create(**defaults)


@pytest.fixture
def authenticated_client(db):
    client = DjangoClient()
    client.force_login(get_user_model().objects.create_user(username='full-reader'))
    return client


@pytest.mark.django_db
class TestNewsFetchFullView:
    def test_authenticated_fetch_accepts_the_session_csrf_token(self, src, cat):
        news = _news(src, cat, content='')
        user = get_user_model().objects.create_user(username='csrf-reader', password='unused')
        client = DjangoClient(enforce_csrf_checks=True)
        client.force_login(user)
        csrf_response = client.get('/api/auth/csrf/')
        csrf_token = csrf_response.cookies['csrftoken'].value
        result = FetchResult(
            ok=True, provider='scrapy_http', url=news.url, markdown='REAL BODY', quality_score=0.9,
        )

        with patch('api.views.fetch_article_markdown', return_value=result) as fetch:
            response = client.post(
                f'/api/news/{news.pk}/fetch-full/',
                HTTP_ORIGIN='http://127.0.0.1:5173',
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        assert response.status_code == 200
        fetch.assert_called_once()
        news.refresh_from_db()
        assert news.full_content == 'REAL BODY'

    def test_anonymous_fetch_is_rejected_before_extraction(self, src, cat):
        news = _news(src, cat, content='')

        with patch('api.views.fetch_article_markdown') as fetch:
            response = DjangoClient().post(f'/api/news/{news.pk}/fetch-full/')

        assert response.status_code == 403
        fetch.assert_not_called()
        news.refresh_from_db()
        assert news.full_content_fetch_status == 'pending'
        assert news.last_full_content_attempt is None

    def test_authenticated_fetch_without_csrf_is_rejected_before_extraction(self, src, cat):
        news = _news(src, cat, content='')
        user = get_user_model().objects.create_user(username='csrf-missing', password='unused')
        client = DjangoClient(enforce_csrf_checks=True)
        client.force_login(user)

        with patch('api.views.fetch_article_markdown') as fetch:
            response = client.post(
                f'/api/news/{news.pk}/fetch-full/',
                HTTP_ORIGIN='http://127.0.0.1:5173',
            )

        assert response.status_code == 403
        assert response.json() == {'detail': 'CSRF Failed: CSRF cookie not set.'}
        fetch.assert_not_called()
        news.refresh_from_db()
        assert news.full_content_fetch_status == 'pending'
        assert news.last_full_content_attempt is None

    @override_settings(CSRF_TRUSTED_ORIGINS=[
        'http://localhost:5173', 'http://localhost:5174', 'http://localhost:5175',
        'http://127.0.0.1:9527', 'http://localhost:9527',
    ])
    def test_stale_origin_allowlist_reproduces_the_live_403_response(self, src, cat):
        news = _news(src, cat, content='')
        user = get_user_model().objects.create_user(username='origin-mismatch', password='unused')
        client = DjangoClient(enforce_csrf_checks=True)
        client.force_login(user)
        csrf_response = client.get('/api/auth/csrf/')
        csrf_token = csrf_response.cookies['csrftoken'].value

        with patch('api.views.fetch_article_markdown') as fetch:
            response = client.post(
                f'/api/news/{news.pk}/fetch-full/',
                HTTP_ORIGIN='http://127.0.0.1:5173',
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        expected = {
            'detail': 'CSRF Failed: Origin checking failed - '
            'http://127.0.0.1:5173 does not match any trusted origins.'
        }
        assert response.status_code == 403
        assert response.json() == expected
        assert len(response.content) == 108
        fetch.assert_not_called()
        news.refresh_from_db()
        assert news.full_content_fetch_status == 'pending'
        assert news.last_full_content_attempt is None

    def test_active_fetch_is_reused_instead_of_starting_a_duplicate(self, authenticated_client, src, cat):
        news = _news(src, cat, content='')
        news.full_content_fetch_status = 'fetching'
        news.last_full_content_attempt = timezone.now()
        news.save(update_fields=['full_content_fetch_status', 'last_full_content_attempt'])

        with patch('api.views.fetch_article_markdown') as fetch:
            response = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert response.status_code == 202
        assert response.json()['full_content_fetch_status'] == 'fetching'
        fetch.assert_not_called()

    def test_background_worker_does_not_fetch_after_losing_the_atomic_claim(self, src, cat):
        news = _news(src, cat, content='')

        with patch('api.management.commands.auto_fetch_full_content.claim_fetch', return_value=False), \
                patch('api.services.article_fetcher.fetch_article_markdown') as fetch:
            result = _fetch_one(news, providers_chain=[])

        assert result is None
        fetch.assert_not_called()

    def test_whitespace_only_cached_body_is_replaced_with_readable_content(self, authenticated_client, src, cat):
        news = _news(src, cat, content='', full_content='  \n  ')
        result = FetchResult(ok=True, provider='scrapy_http', url=news.url, markdown='READABLE BODY')

        with patch('api.views.fetch_article_markdown', return_value=result) as fetch:
            response = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert response.status_code == 200
        fetch.assert_called_once()
        news.refresh_from_db()
        assert news.full_content == 'READABLE BODY'

    def test_only_literal_true_forces_replacing_a_cached_body(self, authenticated_client, src, cat):
        news = _news(src, cat, full_content='CACHED BODY')

        with patch('api.views.fetch_article_markdown') as fetch:
            response = authenticated_client.post(
                f'/api/news/{news.pk}/fetch-full/',
                {'force': 'true'},
                content_type='application/json',
            )

        assert response.status_code == 200
        assert response.json()['full_content'] == 'CACHED BODY'
        fetch.assert_not_called()

    def test_blank_provider_result_is_not_reported_as_success(self, authenticated_client, src, cat):
        news = _news(src, cat, content='')
        result = FetchResult(ok=True, provider='scrapy_http', url=news.url, markdown='  \n ')

        with patch('api.views.fetch_article_markdown', return_value=result):
            response = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert response.status_code == 502
        assert response.json()['full_content_fetch_status'] == 'validation_failed'
        news.refresh_from_db()
        assert not news.full_content.strip()
        assert news.full_content_fetch_status == 'validation_failed'

    def test_stale_fetch_can_be_reclaimed(self, authenticated_client, src, cat):
        news = _news(src, cat, content='')
        news.full_content_fetch_status = 'fetching'
        news.last_full_content_attempt = timezone.now() - timedelta(minutes=6)
        news.save(update_fields=['full_content_fetch_status', 'last_full_content_attempt'])
        result = FetchResult(ok=True, provider='scrapy_http', url=news.url, markdown='RECOVERED BODY')

        with patch('api.views.fetch_article_markdown', return_value=result) as fetch:
            response = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert response.status_code == 200
        fetch.assert_called_once()
        news.refresh_from_db()
        assert news.full_content == 'RECOVERED BODY'

    def test_expired_worker_does_not_overwrite_reclaimed_fetch(self, authenticated_client, src, cat):
        news = _news(src, cat, content='')
        result = FetchResult(ok=True, provider='old_worker', url=news.url, markdown='STALE BODY')

        def reclaim_while_first_worker_is_waiting(*args, **kwargs):
            stale_row = News.objects.get(pk=news.pk)
            stale_row.last_full_content_attempt = timezone.now() - timedelta(minutes=6)
            stale_row.save(update_fields=['last_full_content_attempt'])
            reclaimed = News.objects.get(pk=news.pk)
            from api.services.full_content_status import claim_fetch
            assert claim_fetch(reclaimed)
            return result

        with patch('api.views.fetch_article_markdown', side_effect=reclaim_while_first_worker_is_waiting):
            response = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert response.status_code == 202
        assert response.json()['full_content_fetch_status'] == 'fetching'
        news.refresh_from_db()
        assert news.full_content == ''
        assert news.full_content_fetch_status == 'fetching'

    def test_fetch_full_uses_article_fetcher_and_persists_real_content(self, authenticated_client, src, cat):
        news = _news(src, cat)
        result = FetchResult(
            ok=True,
            provider='scrapy_http',
            url=news.url,
            title=news.title,
            markdown='FETCHED FULL BODY',
            quality_score=0.88,
        )

        with patch('api.views.fetch_article_markdown', return_value=result) as fetch:
            resp = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert resp.status_code == 200
        fetch.assert_called_once_with(
            news.url,
            expected_title=news.title,
            summary=news.content,
        )
        news.refresh_from_db()
        assert news.full_content == 'FETCHED FULL BODY'
        assert news.full_content_fetched_at is not None
        assert news.full_content_fetch_status == 'success'
        assert news.full_content_fetch_error == ''
        assert news.full_content_fetch_provider == 'scrapy_http'
        assert news.full_content_quality_score == 0.88
        assert news.last_full_content_attempt is not None

        refreshed_response = authenticated_client.get(f'/api/news/{news.pk}/')
        assert refreshed_response.status_code == 200
        assert refreshed_response.json()['full_content'] == 'FETCHED FULL BODY'

    def test_fetch_full_does_not_persist_summary_as_full_content_when_fetchers_fail(self, authenticated_client, src, cat):
        """Summary/fallback text must not masquerade as fetched original content."""
        news = _news(src, cat, title='LLMs Are Closer to Religion Than They Appear')

        with patch('api.views.fetch_article_markdown', side_effect=FetchError('全部真实原文抓取方式失败')):
            resp = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert resp.status_code == 502
        data = resp.json()
        assert '原文抓取失败' in data['error']
        assert '可稍后重试' in data['error']
        assert data['full_content_fetch_status'] == 'failed'
        assert data['full_content_fetch_error'] == '全部真实原文抓取方式失败'
        assert data['full_content_fetch_provider'] == ''
        assert data['full_content_quality_score'] is None
        assert data['full_content_retry_count'] == 1
        assert data['last_full_content_attempt'] is not None

        news.refresh_from_db()
        assert news.full_content == ''
        assert news.full_content_fetched_at is None
        assert news.full_content_fetch_status == 'failed'
        assert news.full_content_fetch_error == '全部真实原文抓取方式失败'
        assert news.full_content_retry_count == 1

    def test_fetch_full_records_network_error_without_persisting_content(self, authenticated_client, src, cat):
        news = _news(src, cat, title='Network failure article')

        with patch('api.views.fetch_article_markdown', side_effect=FetchError('connection reset by peer')):
            resp = authenticated_client.post(f'/api/news/{news.pk}/fetch-full/')

        assert resp.status_code == 502
        data = resp.json()
        assert data['full_content_fetch_status'] == 'network_error'
        assert data['full_content_fetch_error'] == 'connection reset by peer'
        assert data['full_content_retry_count'] == 1
        assert data['last_full_content_attempt'] is not None
        news.refresh_from_db()
        assert news.full_content == ''
        assert news.full_content_fetched_at is None
        assert news.full_content_fetch_status == 'network_error'
        assert news.full_content_fetch_error == 'connection reset by peer'
        assert news.full_content_retry_count == 1
