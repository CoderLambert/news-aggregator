from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from api.models import News, Category, Source, Favorite
from django.utils import timezone


class FavoriteModelTest(TestCase):
    """Favorite model CRUD tests."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='test123')
        self.category = Category.objects.create(name='Test', slug='test')
        self.source = Source.objects.create(name='Test Source', url='https://test.com')
        self.news = News.objects.create(
            title='Test News',
            content='Content',
            publish_time=timezone.now(),
            source=self.source,
            category=self.category,
            url='https://test.com/news/1',
        )

    def test_create_like(self):
        fav = Favorite.objects.create(user=self.user, news=self.news, type='like')
        self.assertEqual(Favorite.objects.count(), 1)
        self.assertEqual(fav.type, 'like')

    def test_create_bookmark(self):
        fav = Favorite.objects.create(user=self.user, news=self.news, type='bookmark')
        self.assertEqual(fav.type, 'bookmark')

    def test_unique_constraint_user_news_type(self):
        Favorite.objects.create(user=self.user, news=self.news, type='like')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Favorite.objects.create(user=self.user, news=self.news, type='like')

    def test_same_news_different_types(self):
        Favorite.objects.create(user=self.user, news=self.news, type='like')
        Favorite.objects.create(user=self.user, news=self.news, type='bookmark')
        self.assertEqual(Favorite.objects.filter(user=self.user, news=self.news).count(), 2)

    def test_str_representation(self):
        fav = Favorite.objects.create(user=self.user, news=self.news, type='like')
        self.assertIn('like', str(fav))


class FavoriteAPITest(TestCase):
    """API endpoint tests for favorites."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='test123')
        self.category = Category.objects.create(name='Test', slug='test')
        self.source = Source.objects.create(name='Test Source', url='https://test.com')
        self.news1 = News.objects.create(
            title='News 1', content='Content 1',
            publish_time=timezone.now(), source=self.source,
            category=self.category, url='https://test.com/news/1',
        )
        self.news2 = News.objects.create(
            title='News 2', content='Content 2',
            publish_time=timezone.now(), source=self.source,
            category=self.category, url='https://test.com/news/2',
        )

    def _login(self):
        self.client.login(username='testuser', password='test123')

    def test_unauthenticated_cannot_favorite(self):
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_cannot_list_favorites(self):
        resp = self.client.get('/api/favorites/')
        self.assertEqual(resp.status_code, 403)

    def test_create_like(self):
        self._login()
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['type'], 'like')
        self.assertEqual(resp.data['news']['id'], self.news1.pk)

    def test_create_bookmark(self):
        self._login()
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'bookmark'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['type'], 'bookmark')

    def test_create_invalid_type(self):
        self._login()
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'invalid'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_create_nonexistent_news(self):
        self._login()
        resp = self.client.post('/api/favorites/', {'news_id': 99999, 'type': 'like'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_like_returns_existing(self):
        self._login()
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get('removed', False))

    def test_delete_favorite(self):
        self._login()
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        fav = Favorite.objects.get(user=self.user, news=self.news1, type='like')
        resp = self.client.delete(f'/api/favorites/{fav.pk}/')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_delete_nonexistent(self):
        self._login()
        resp = self.client.delete('/api/favorites/99999/')
        self.assertEqual(resp.status_code, 404)

    def test_list_favorites(self):
        self._login()
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.client.post('/api/favorites/', {'news_id': self.news2.pk, 'type': 'bookmark'}, format='json')
        resp = self.client.get('/api/favorites/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 2)

    def test_list_favorites_filter_by_type(self):
        self._login()
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.client.post('/api/favorites/', {'news_id': self.news2.pk, 'type': 'bookmark'}, format='json')
        resp = self.client.get('/api/favorites/', {'type': 'bookmark'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['type'], 'bookmark')

    def test_list_favorites_only_own(self):
        other = User.objects.create_user(username='other', password='other123')
        Favorite.objects.create(user=other, news=self.news1, type='like')
        self._login()
        resp = self.client.get('/api/favorites/')
        self.assertEqual(len(resp.data['results']), 0)

    def test_check_status(self):
        self._login()
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        resp = self.client.get(f'/api/favorites/check/?news_id={self.news1.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['is_liked'])
        self.assertFalse(resp.data['is_bookmarked'])

    def test_check_status_no_favorites(self):
        self._login()
        resp = self.client.get(f'/api/favorites/check/?news_id={self.news1.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['is_liked'])
        self.assertFalse(resp.data['is_bookmarked'])

    def test_toggle_like(self):
        self._login()
        # First call creates
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.assertEqual(resp.status_code, 201)
        # Second call removes
        resp = self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get('removed', False))
        self.assertEqual(Favorite.objects.filter(user=self.user, news=self.news1, type='like').count(), 0)

    def test_count_includes_in_response(self):
        self._login()
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'like'}, format='json')
        self.client.post('/api/favorites/', {'news_id': self.news1.pk, 'type': 'bookmark'}, format='json')
        resp = self.client.get(f'/api/favorites/check/?news_id={self.news1.pk}')
        self.assertEqual(resp.data['like_count'], 1)
        self.assertEqual(resp.data['bookmark_count'], 1)
