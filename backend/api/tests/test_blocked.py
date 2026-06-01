from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from api.models import News, Category, Source, BlockedNews
from django.utils import timezone


class BlockedNewsModelTest(TestCase):
    """BlockedNews model tests."""

    def setUp(self):
        self.user = User.objects.create_user(username='blocker', password='test123')
        self.other_user = User.objects.create_user(username='other', password='test123')
        self.category = Category.objects.create(name='Tech', slug='tech')
        self.source = Source.objects.create(name='Src', url='https://src.com')
        self.news1 = News.objects.create(
            title='Blocked News', content='c1',
            publish_time=timezone.now(), source=self.source, category=self.category,
            url='https://src.com/1',
        )
        self.news2 = News.objects.create(
            title='Visible News', content='c2',
            publish_time=timezone.now(), source=self.source, category=self.category,
            url='https://src.com/2',
        )

    def test_create_block(self):
        block = BlockedNews.objects.create(user=self.user, news=self.news1)
        self.assertEqual(BlockedNews.objects.count(), 1)
        self.assertEqual(str(block), f'{self.user.username} blocked {self.news1.title[:30]}')

    def test_unique_constraint(self):
        BlockedNews.objects.create(user=self.user, news=self.news1)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            BlockedNews.objects.create(user=self.user, news=self.news1)

    def test_different_users_can_block_same_news(self):
        BlockedNews.objects.create(user=self.user, news=self.news1)
        BlockedNews.objects.create(user=self.other_user, news=self.news1)
        self.assertEqual(BlockedNews.objects.count(), 2)

    def test_cascade_delete_user(self):
        BlockedNews.objects.create(user=self.user, news=self.news1)
        self.user.delete()
        self.assertEqual(BlockedNews.objects.count(), 0)

    def test_cascade_delete_news(self):
        BlockedNews.objects.create(user=self.user, news=self.news1)
        self.news1.delete()
        self.assertEqual(BlockedNews.objects.count(), 0)


class BlockedNewsAPITest(TestCase):
    """BlockedNews API endpoint tests."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='blocker', password='test123')
        self.category = Category.objects.create(name='Tech', slug='tech')
        self.source = Source.objects.create(name='Src', url='https://src.com')
        self.news1 = News.objects.create(
            title='Blocked News', content='c1',
            publish_time=timezone.now(), source=self.source, category=self.category,
            url='https://src.com/1',
        )
        self.news2 = News.objects.create(
            title='Visible News', content='c2',
            publish_time=timezone.now(), source=self.source, category=self.category,
            url='https://src.com/2',
        )

    # ---- Block (POST) ----

    def test_block_requires_auth(self):
        res = self.client.post('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        self.assertEqual(res.status_code, 403)

    def test_block_news(self):
        self.client.force_authenticate(self.user)
        res = self.client.post('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data['created'])
        self.assertTrue(BlockedNews.objects.filter(user=self.user, news=self.news1).exists())

    def test_block_idempotent(self):
        self.client.force_authenticate(self.user)
        res1 = self.client.post('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        self.assertEqual(res1.status_code, 201)
        res2 = self.client.post('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.data['created'])
        self.assertEqual(BlockedNews.objects.count(), 1)

    def test_block_nonexistent_news(self):
        self.client.force_authenticate(self.user)
        res = self.client.post('/api/blocked/', {'news_id': 99999}, format='json')
        self.assertEqual(res.status_code, 400)

    # ---- Unblock (DELETE) ----

    def test_unblock_news(self):
        self.client.force_authenticate(self.user)
        self.client.post('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        res = self.client.delete('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['removed'])
        self.assertFalse(BlockedNews.objects.filter(user=self.user, news=self.news1).exists())

    def test_unblock_not_blocked(self):
        self.client.force_authenticate(self.user)
        res = self.client.delete('/api/blocked/', {'news_id': self.news1.pk}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['removed'])

    # ---- List (GET) ----

    def test_list_blocked(self):
        self.client.force_authenticate(self.user)
        BlockedNews.objects.create(user=self.user, news=self.news1)
        BlockedNews.objects.create(user=self.user, news=self.news2)
        res = self.client.get('/api/blocked/')
        self.assertEqual(res.status_code, 200)
        results = res.data.get('results', res.data)
        self.assertEqual(len(results), 2)

    def test_list_only_own_blocks(self):
        other = User.objects.create_user(username='other', password='test123')
        BlockedNews.objects.create(user=self.user, news=self.news1)
        BlockedNews.objects.create(user=other, news=self.news2)
        self.client.force_authenticate(self.user)
        res = self.client.get('/api/blocked/')
        results = res.data.get('results', res.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['news']['id'], self.news1.pk)

    # ---- Check (GET) ----

    def test_check_blocked_status(self):
        self.client.force_authenticate(self.user)
        BlockedNews.objects.create(user=self.user, news=self.news1)
        res = self.client.get('/api/blocked/check/', {'news_id': self.news1.pk})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['is_blocked'])

    def test_check_not_blocked(self):
        self.client.force_authenticate(self.user)
        res = self.client.get('/api/blocked/check/', {'news_id': self.news1.pk})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['is_blocked'])

    # ---- News list excludes blocked ----

    def test_news_list_excludes_blocked(self):
        BlockedNews.objects.create(user=self.user, news=self.news1)
        self.client.force_authenticate(self.user)
        res = self.client.get('/api/news/')
        ids = [n['id'] for n in res.data['results']]
        self.assertNotIn(self.news1.pk, ids)
        self.assertIn(self.news2.pk, ids)

    def test_news_list_unauthenticated_shows_all(self):
        BlockedNews.objects.create(user=self.user, news=self.news1)
        res = self.client.get('/api/news/')
        ids = [n['id'] for n in res.data['results']]
        self.assertIn(self.news1.pk, ids)
