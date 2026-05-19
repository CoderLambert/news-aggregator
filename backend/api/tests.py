"""
Run: cd backend && python manage.py test api.tests -v2
Tests: multi-select category/source filters, time precision, search, pagination
"""

import uuid
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta
from api.models import Category, Source, News


class TestDataFactory:
    """Creates isolated test data with unique slugs/names/URLs."""

    def __init__(self, prefix=None):
        self.prefix = prefix or uuid.uuid4().hex[:8]

    def create_category(self, name):
        return Category.objects.create(name=f'{self.prefix}_{name}', slug=f'{self.prefix}-{name.lower()}')

    def create_source(self, name, source_type='news'):
        return Source.objects.create(
            name=f'{self.prefix}_{name}', source_type=source_type,
            url=f'https://{self.prefix}-{name.lower()}.example.com',
        )

    def create_news(self, title, category, source, publish_time=None, related_to=None):
        return News.objects.create(
            title=f'{self.prefix}_{title}',
            content=f'content for {title}',
            category=category,
            source=source,
            url=f'https://example.com/{self.prefix}/{title.lower().replace(" ", "-")}',
            publish_time=publish_time or timezone.now(),
            related_to=related_to,
        )

    def _titles(self, data):
        return [r['title'] for r in data['results']]


class MultiSelectCategoryFilterTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('cat')
        self.f = f
        self.cat_python = f.create_category('Python')
        self.cat_ai = f.create_category('AI')
        self.cat_go = f.create_category('Go')
        self.src_github = f.create_source('GitHub', 'aggregator')
        self.src_hn = f.create_source('HN', 'discussion')
        now = timezone.now()
        f.create_news('Python tutorial', self.cat_python, self.src_github, now)
        f.create_news('AI revolution', self.cat_ai, self.src_hn, now - timedelta(hours=2))
        f.create_news('Go concurrency', self.cat_go, self.src_github, now - timedelta(hours=5))
        f.create_news('Python AI project', self.cat_ai, self.src_github, now - timedelta(minutes=30))
        f.create_news('Go web framework', self.cat_go, self.src_hn, now - timedelta(days=1))

    def test_single_category(self):
        r = self.client.get(f'/api/news/?category={self.cat_python.id}&page_size=10')
        self.assertEqual(r.status_code, 200)
        titles = self.f._titles(r.json())
        self.assertIn(f'{self.f.prefix}_Python tutorial', titles)
        self.assertNotIn(f'{self.f.prefix}_AI revolution', titles)
        self.assertNotIn(f'{self.f.prefix}_Go concurrency', titles)

    def test_multi_category(self):
        ids = f'{self.cat_python.id},{self.cat_ai.id}'
        r = self.client.get(f'/api/news/?category={ids}&page_size=10')
        self.assertEqual(r.status_code, 200)
        titles = self.f._titles(r.json())
        self.assertIn(f'{self.f.prefix}_Python tutorial', titles)
        self.assertIn(f'{self.f.prefix}_AI revolution', titles)
        self.assertIn(f'{self.f.prefix}_Python AI project', titles)
        self.assertNotIn(f'{self.f.prefix}_Go concurrency', titles)
        self.assertNotIn(f'{self.f.prefix}_Go web framework', titles)

    def test_multi_category_and_multi_source(self):
        cat_ids = f'{self.cat_ai.id},{self.cat_go.id}'
        src_ids = f'{self.src_github.id}'
        r = self.client.get(f'/api/news/?category={cat_ids}&source={src_ids}&page_size=10')
        self.assertEqual(r.status_code, 200)
        titles = self.f._titles(r.json())
        self.assertIn(f'{self.f.prefix}_Python AI project', titles)
        self.assertIn(f'{self.f.prefix}_Go concurrency', titles)
        self.assertNotIn(f'{self.f.prefix}_AI revolution', titles)
        self.assertNotIn(f'{self.f.prefix}_Go web framework', titles)

    def test_no_match(self):
        r = self.client.get('/api/news/?category=99999&source=99999&page_size=10')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['count'], 0)


class MultiSelectSourceFilterTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('src')
        self.f = f
        cat = f.create_category('TestCat')
        self.src_github = f.create_source('GitHub', 'aggregator')
        self.src_hn = f.create_source('HN', 'discussion')
        now = timezone.now()
        f.create_news('From GitHub', cat, self.src_github, now)
        f.create_news('From HN', cat, self.src_hn, now - timedelta(hours=1))
        f.create_news('Also GitHub', cat, self.src_github, now - timedelta(hours=2))

    def test_single_source(self):
        r = self.client.get(f'/api/news/?source={self.src_github.id}&page_size=10')
        self.assertEqual(r.status_code, 200)
        titles = self.f._titles(r.json())
        self.assertEqual(len(titles), 2)

    def test_multi_source(self):
        ids = f'{self.src_github.id},{self.src_hn.id}'
        r = self.client.get(f'/api/news/?source={ids}&page_size=10')
        self.assertEqual(r.status_code, 200)
        titles = self.f._titles(r.json())
        self.assertEqual(len(titles), 3)

    def test_empty_filter(self):
        r = self.client.get('/api/news/?page_size=100')
        self.assertEqual(r.status_code, 200)
        # Only this test class's own data
        self.assertGreaterEqual(r.json()['count'], 3)


class TimePrecisionTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('time')
        cat = f.create_category('Test')
        src = f.create_source('TestSrc')
        now = timezone.now()
        f.create_news('Time test', cat, src, now)

    def test_publish_time_includes_minutes(self):
        r = self.client.get('/api/news/?page_size=1')
        d = r.json()
        pt = d['results'][0]['publish_time']
        # ISO 8601: "2026-05-19T20:00:12.047704+08:00"
        self.assertIn('T', pt)
        time_part = pt.split('T')[1]
        hh_mm = time_part.split(':')
        self.assertGreaterEqual(len(hh_mm), 2)


class SearchTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('search')
        self.f = f
        cat = f.create_category('Search')
        src = f.create_source('TestSrc')
        now = timezone.now()
        f.create_news('Django REST framework tutorial', cat, src, now)
        f.create_news('FastAPI vs Flask comparison', cat, src, now)
        f.create_news('Python async programming', cat, src, now)

    def test_keyword_search(self):
        r = self.client.get(f'/api/news/?search={self.f.prefix}+Python&mode=keyword&page_size=10')
        self.assertEqual(r.status_code, 200)
        titles = self.f._titles(r.json())
        self.assertIn(f'{self.f.prefix}_Python async programming', titles)

    def test_semantic_search_no_vector_fallback(self):
        r = self.client.get('/api/news/?search=test&mode=semantic&page_size=10')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIsInstance(d['results'], list)

    def test_hybrid_search_no_vector_fallback(self):
        r = self.client.get('/api/news/?search=test&mode=hybrid&page_size=10')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIsInstance(d['results'], list)


class PaginationTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('pag')
        self.f = f
        cat = f.create_category('Pag')
        src = f.create_source('TestSrc')
        now = timezone.now()
        for i in range(25):
            f.create_news(f'Article {i}', cat, src, now - timedelta(minutes=i))

    def test_page_size(self):
        r = self.client.get('/api/news/?page_size=2')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(len(d['results']), 2)
        self.assertIsNotNone(d['next'])

    def test_total_count(self):
        r = self.client.get('/api/news/?page_size=100')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['count'], 25)


class DuplicateFilterTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('dup')
        self.f = f
        cat = f.create_category('Dup')
        src = f.create_source('TestSrc')
        now = timezone.now()
        main = f.create_news('Main article', cat, src, now)
        f.create_news('Duplicate article', cat, src, now, related_to=main)

    def test_default_excludes_dupes(self):
        r = self.client.get('/api/news/?page_size=100')
        self.assertEqual(r.json()['count'], 1)

    def test_include_dupes(self):
        r = self.client.get('/api/news/?include_dupes=true&page_size=100')
        self.assertEqual(r.json()['count'], 2)


class CategorySourceListTest(TestCase):
    def setUp(self):
        self.client = Client()
        f = TestDataFactory('list')
        f.create_category('ListCat')
        f.create_source('ListSrc')

    def test_category_list(self):
        r = self.client.get('/api/categories/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertGreater(len(d), 0)

    def test_source_list(self):
        r = self.client.get('/api/sources/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertGreater(len(d), 0)
