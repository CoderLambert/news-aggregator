"""
Tests for the NewsFetchFullView API endpoint.
Tests cached article reads and durable full-content enqueue responses.
"""
import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone


class NewsFetchFullViewTest(TestCase):
    """Test the full article fetching endpoint."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username='full-content-reader')
        self.client.force_login(self.user)
        # Create test data
        from api.models import News, Source, Category
        self.source = Source.objects.update_or_create(name='GitHub Trending', defaults={'url': 'https://github.com/trending', 'language': 'en', 'source_type': 'aggregator'})[0]
        self.category = Category.objects.create(
            name='Python',
            slug='python',
        )
        self.news = News.objects.create(
            title='owner/test-repo',
            content='A test repository',
            url='https://github.com/owner/test-repo',
            source=self.source,
            category=self.category,
            publish_time=timezone.now(),
        )

    def test_fetch_full_content_requires_post(self):
        """GET request should not work for fetch-full endpoint."""
        response = self.client.get(f'/api/news/{self.news.id}/fetch-full/')
        # Should not allow GET
        self.assertIn(response.status_code, [405, 404])

    def test_fetch_full_content_requires_session_auth_and_csrf(self):
        anonymous = Client()
        response = anonymous.post(f'/api/news/{self.news.id}/fetch-full/')
        self.assertIn(response.status_code, [401, 403])
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(f'/api/news/{self.news.id}/fetch-full/')
        self.assertEqual(response.status_code, 403)

    def test_fetch_full_content_with_valid_url(self):
        """A healthy worker accepts one intent without fetching from the API."""
        with (
            patch('api.services.article_content.worker_health', return_value=True),
            patch('api.views.fetch_article_markdown') as fetch,
        ):
            response = self.client.post(
                f'/api/news/{self.news.id}/fetch-full/',
                content_type='application/json'
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['full_content_fetch_status'], 'queued')
        self.assertTrue(response['Location'].endswith(f'/api/news/{self.news.id}/'))
        self.assertGreaterEqual(int(response['Retry-After']), 2)
        self.news.refresh_from_db()
        self.assertEqual(self.news.full_content, '')
        fetch.assert_not_called()

    def test_fetch_full_content_disabled_worker_does_not_enqueue(self):
        with patch('api.services.article_content.worker_health', return_value=False):
            response = self.client.post(f'/api/news/{self.news.id}/fetch-full/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error_code'], 'full_content_worker_unavailable')
        self.news.refresh_from_db()
        self.assertEqual(self.news.full_content_fetch_status, 'pending')

    def test_fetch_full_content_caches_result(self):
        """Second request should return cached result."""
        # Set full_content manually to simulate cached state
        self.news.full_content = "# Test Content\n\nThis is cached content."
        self.news.full_content_state = 'legacy'
        self.news.save()
        
        response = self.client.post(
            f'/api/news/{self.news.id}/fetch-full/',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('cached content', data.get('full_content', ''))

    def test_fetch_full_content_missing_url(self):
        """Should handle missing URL gracefully."""
        self.news.url = ''
        self.news.save()
        
        response = self.client.post(
            f'/api/news/{self.news.id}/fetch-full/',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 422)


class NewsTranslateFullViewTest(TestCase):
    """Test the translation endpoint."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username='translation-reader')
        self.client.force_login(self.user)
        from api.models import News, Source, Category
        self.source = Source.objects.update_or_create(name='GitHub Trending', defaults={'url': 'https://github.com/trending', 'language': 'en', 'source_type': 'aggregator'})[0]
        self.category = Category.objects.create(
            name='Python',
            slug='python',
        )
        self.news = News.objects.create(
            title='owner/test-repo',
            content='A test repository',
            full_content='# Test\n\nSome content to translate.',
            full_content_state='legacy',
            url='https://github.com/owner/test-repo',
            source=self.source,
            category=self.category,
            publish_time=timezone.now(),
        )

    def test_translate_requires_post(self):
        """GET request should not work for translate endpoint."""
        response = self.client.get(f'/api/news/{self.news.id}/translate/')
        self.assertEqual(response.status_code, 405)

    def test_translate_without_full_content(self):
        """Should error if no full_content available."""
        self.news.full_content = ''
        self.news.save()
        
        response = self.client.post(
            f'/api/news/{self.news.id}/translate/',
            data=json.dumps({'force': True}),
            content_type='application/json'
        )
        # Should return error about missing content
        self.assertEqual(response.status_code, 200)  # SSE always returns 200
        # Check response contains error message (may be JSON escaped)
        content = b''.join(response.streaming_content).decode('utf-8')
        # The error message is JSON escaped, so check for the decoded content
        import json as json_mod
        data = json_mod.loads(content.split('data: ')[1].strip())
        self.assertIn('获取完整原文', data.get('error', ''))
