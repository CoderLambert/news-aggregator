"""T31 candidate retirement: old admissions cannot create publisher work."""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone

from api.models import Category, News, Source
from api.tests.rss.reader_fixtures import public_legacy_article


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_old_full_content_post_is_gone_without_enqueuing_or_network():
    source, _ = Source.objects.update_or_create(name='WebKit', defaults={'url': 'https://webkit.org'})
    category = Category.objects.create(name='T31 candidate', slug='t31-candidate')
    news = public_legacy_article(News.objects.create(
        source=source, category=category, title='Retained historical article', content='Retained summary',
        url='https://webkit.org/blog/123/candidate/', publish_time=timezone.now(),
    ))
    user = get_user_model().objects.create_user('t31-reader')
    client = Client()
    client.force_login(user)
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')):
        response = client.post(f'/api/news/{news.pk}/fetch-full/')
    assert response.status_code == 410, response.content
    news.refresh_from_db()
    assert news.content == 'Retained summary'
    assert news.full_content_fetch_status == 'pending'
    assert news.full_content_next_attempt_at is None
    assert news.full_content_requested_by_id is None


@pytest.mark.django_db
@pytest.mark.parametrize('path', [
    '/api/admin/crawler/dashboard/',
    '/api/admin/crawler/sources/example/probe/',
    '/api/admin/article-fetch/dashboard/',
    '/api/provider-comparisons/',
    '/api/provider-comparisons/1/retest/',
])
def test_retired_admin_urls_keep_permission_and_session_csrf(path):
    ordinary = get_user_model().objects.create_user('t31-ordinary')
    admin = get_user_model().objects.create_superuser('t31-admin', password='synthetic-password')
    client = Client(enforce_csrf_checks=True)
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')):
        assert client.get(path).status_code == 403
        client.force_login(ordinary)
        assert client.get(path).status_code == 403
        client.force_login(admin)
        assert client.get(path).status_code == 410
        assert client.post(path).status_code == 403
        client.get('/api/auth/csrf/')
        token = client.cookies['csrftoken'].value
        assert client.post(path, HTTP_X_CSRFTOKEN=token).status_code == 410


def test_url_bootstrap_and_management_discovery_do_not_load_collectors():
    from django.core.management import get_commands
    from django.urls import get_resolver
    import sys
    get_resolver().url_patterns
    retired_modules = (
        'news_crawler', 'api.services.article_fetcher', 'api.services.full_content_worker',
        'api.services.full_content_status', 'api.services.news_ingestion', 'api.crawler_views',
    )
    assert not [name for name in sys.modules if any(
        name == prefix or name.startswith(prefix + '.') for prefix in retired_modules)]
    commands = get_commands()
    assert {'rss_runtime', 'rss_sync_worker', 'embedding_worker', 'channel_worker'} <= commands.keys()
    assert not {'crawl', 'crawl_worker', 'auto_fetch_full_content', 'fetch_full_content',
                'fetch_article_url', 'compare_providers'} & commands.keys()
