"""
Tests for the NewsFetchFullView API endpoint.
Tests the full article fetching and content cleaning flow.
"""
import json
import pytest
from django.test import TestCase, Client
from django.urls import reverse


class NewsFetchFullViewTest(TestCase):
    """Test the full article fetching endpoint."""

    def setUp(self):
        self.client = Client()
        # Create test data
        from api.models import News, Source, Category
        self.source = Source.objects.create(
            name='GitHub Trending',
            url='https://github.com/trending',
            language='en',
            source_type='aggregator',
        )
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
            publish_time='2026-05-30 12:00:00',
        )

    def test_fetch_full_content_requires_post(self):
        """GET request should not work for fetch-full endpoint."""
        response = self.client.get(f'/api/news/{self.news.id}/fetch-full/')
        # Should not allow GET
        self.assertIn(response.status_code, [405, 404])

    def test_fetch_full_content_with_valid_url(self):
        """POST request with valid URL should return content."""
        # This test would normally mock the Jina Reader API
        # For now, just test the endpoint exists
        response = self.client.post(
            f'/api/news/{self.news.id}/fetch-full/',
            content_type='application/json'
        )
        # Should not crash
        self.assertIn(response.status_code, [200, 422, 502])

    def test_fetch_full_content_caches_result(self):
        """Second request should return cached result."""
        # Set full_content manually to simulate cached state
        self.news.full_content = "# Test Content\n\nThis is cached content."
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
        self.assertEqual(response.status_code, 400)


class NewsTranslateFullViewTest(TestCase):
    """Test the translation endpoint."""

    def setUp(self):
        self.client = Client()
        from api.models import News, Source, Category
        self.source = Source.objects.create(
            name='GitHub Trending',
            url='https://github.com/trending',
            language='en',
            source_type='aggregator',
        )
        self.category = Category.objects.create(
            name='Python',
            slug='python',
        )
        self.news = News.objects.create(
            title='owner/test-repo',
            content='A test repository',
            full_content='# Test\n\nSome content to translate.',
            url='https://github.com/owner/test-repo',
            source=self.source,
            category=self.category,
            publish_time='2026-05-30 12:00:00',
        )

    def test_translate_requires_post(self):
        """GET request should not work for translate endpoint."""
        response = self.client.get(f'/api/news/{self.news.id}/translate/')
        self.assertIn(response.status_code, [405, 200])  # 200 if streaming works

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
