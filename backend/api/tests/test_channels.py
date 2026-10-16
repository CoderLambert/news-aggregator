from api.tests.rss.legacy_fixtures import legacy_news, public_legacy
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import Category, Source, News, BlockedNews, ChannelSubscription, ChannelGroup, NewsPreference
from api.services.channel_catalog import sync_channel_catalog


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
class ChannelsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('channel-reader', password='test-pass-123')
        self.other = User.objects.create_user('other-reader')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.source, _ = Source.objects.get_or_create(name='OpenAI Blog', defaults={'url': 'https://openai.com/news'})
        self.second, _ = Source.objects.get_or_create(name='DeepMind', defaults={'url': 'https://deepmind.google'})
        self.outside, _ = Source.objects.get_or_create(name='WebKit', defaults={'url': 'https://webkit.org'})
        self.category = Category.objects.create(name='科技', slug='channel-tech')
        self.other_category = Category.objects.create(name='其他', slug='channel-other')
        self.first = self.story(self.source, 'First')
        self.second_story = self.story(self.second, 'Second')
        self.outside_story = self.story(self.outside, 'Outside')

    def story(self, source, title, **kwargs):
        return legacy_news(source=source, category=kwargs.pop('category', self.category), title=title,
            content='shared query', title_zh='共享搜索', url=f'https://example.com/channel/{title}', publish_time=timezone.now(), **kwargs)

    def subscribe(self, source_ids, action='subscribe', **extra):
        return self.client.post('/api/me/channel-subscriptions/', {'source_ids': source_ids, 'action': action, **extra}, format='json')

    def group(self, name='AI'):
        response = self.client.post('/api/me/channel-groups/', {'name': name}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def assign(self, group, source_ids):
        response = self.client.patch(f'/api/me/channel-groups/{group}/', {'source_ids': source_ids}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_batch_idempotent_multi_group_and_unsubscribe_cascades(self):
        self.assertEqual(self.subscribe([self.source.id, self.second.id]).status_code, 200)
        self.subscribe([self.source.id, self.source.id])
        self.assertEqual(ChannelSubscription.objects.filter(user=self.user).count(), 2)
        a, b = self.group(), self.group('前端与 AI')
        self.assign(a, [self.source.id, self.second.id])
        self.assign(b, [self.source.id])
        self.assign(a, [self.source.id, self.second.id])
        self.assertEqual(self.client.get('/api/news/', {'scope': 'group', 'group_id': a}).data['count'], 2)
        self.assertEqual(self.client.get('/api/news/', {'scope': 'group', 'group_id': b}).data['count'], 1)
        self.assertEqual(self.client.get('/api/news/', {'scope': 'ungrouped'}).data['count'], 0)
        self.subscribe([self.source.id], action='unsubscribe')
        self.assertEqual(ChannelGroup.objects.get(pk=b).subscriptions.count(), 0)
        self.assertEqual(ChannelGroup.objects.get(pk=a).subscriptions.count(), 1)
        self.subscribe([self.second.id], action='unsubscribe')
        self.assertEqual(self.client.get('/api/news/', {'scope': 'subscribed'}).data['count'], 0)

    def test_multi_source_type_filter_is_union_and_invalid_values_rejected(self):
        Source.objects.filter(pk=self.source.pk).update(source_type='news')
        Source.objects.filter(pk=self.second.pk).update(source_type='discussion')
        Source.objects.filter(pk=self.outside.pk).update(source_type='aggregator')
        for selection, count in [('news', 1), ('news,discussion', 2), ('news,discussion,aggregator', 3)]:
            response = self.client.get('/api/news/', {'search': 'shared', 'mode': 'keyword', 'source_types': selection})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['count'], count)
        for invalid in ('news,invalid', 'news,news', 'discussion,aggregator,news,invalid'):
            response = self.client.get('/api/news/', {'search': 'shared', 'source_types': invalid})
            self.assertEqual(response.status_code, 400)
        # Backward compatibility: historical single-value filter remains functional.
        self.assertEqual(self.client.get('/api/news/', {'source__source_type': 'discussion'}).data['count'], 1)


    def test_opt_in_full_body_search_preserves_default_search_and_user_privacy(self):
        from django.contrib.auth.models import Permission
        self.first.full_content = 'An old body with unique-lantern-token, otherwise absent.'
        self.first.full_content_state = 'complete'
        self.first.save(update_fields=['full_content', 'full_content_state'])
        self.second_story.full_content = 'Some other article about the same rare code.'
        self.second_story.full_content_state = 'complete'
        self.second_story.save(update_fields=['full_content', 'full_content_state'])
        self.user.user_permissions.add(Permission.objects.get(codename='view_article_body'))
        query = {'search': 'unique-lantern-token', 'mode': 'keyword'}
        default = self.client.get('/api/news/', query)
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default.data['count'], 0)
        actual = self.client.get('/api/news/', {**query, 'search_in': 'full'})
        self.assertEqual(actual.status_code, 200, actual.data)
        self.assertEqual([row['id'] for row in actual.data['results']], [self.first.pk])
        self.assertNotIn('full_content', actual.data['results'][0])
        BlockedNews.objects.create(user=self.user, news=self.first)
        blocked = self.client.get('/api/news/', {**query, 'search_in': 'full'})
        self.assertEqual(blocked.data['count'], 0)
        # Legacy existing only-full filter remains distinct from searching body text.
        legacy = self.client.get('/api/news/', {**query, 'full_content': 'true'})
        self.assertEqual(legacy.data['count'], 0)

    def test_full_body_search_rejects_unbounded_and_anonymous_work(self):
        query = {'search': 'full body', 'mode': 'keyword', 'search_in': 'full'}
        anonymous = APIClient()
        self.assertEqual(anonymous.get('/api/news/', query).status_code, 403)
        for changes in (
            {'mode': 'semantic'}, {'mode': 'hybrid'}, {'search': 'A' * 97},
            {'search': ''}, {'page_size': '50'}, {'page': '11'},
            {'search_in': 'unknown'},
        ):
            response = self.client.get('/api/news/', {**query, **changes})
            self.assertEqual(response.status_code, 400, (changes, response.data))

    def test_full_body_search_enforces_per_user_persistent_budget(self):
        from unittest.mock import patch
        from api.services.account_security import _reserve_buckets
        query = {'search': 'body keyword', 'mode': 'keyword', 'search_in': 'full'}
        self.client.get('/api/news/', query)
        # Exercise the actual quota with a deterministic 8 attempts per user.
        for attempt in range(7):
            response = self.client.get('/api/news/', query)
            self.assertEqual(response.status_code, 200, (attempt, response.data))
        limited = self.client.get('/api/news/', query)
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited['Retry-After']), 0)

    def test_membership_removal_and_group_deletion_keep_subscription(self):
        self.subscribe([self.source.id])
        a, b = self.group(), self.group('Second group')
        self.assign(a, [self.source.id]); self.assign(b, [self.source.id])
        self.client.patch(f'/api/me/channel-groups/{a}/', {'remove_source_ids': [self.source.id]}, format='json')
        self.assertEqual(ChannelGroup.objects.get(pk=b).subscriptions.count(), 1)
        self.client.patch('/api/me/news-preferences/', {'scope': 'group', 'group_id': b}, format='json')
        self.assertEqual(self.client.delete(f'/api/me/channel-groups/{b}/').status_code, 204)
        self.assertEqual(self.client.get('/api/me/news-preferences/').data, {'scope': 'subscribed', 'group_id': None})
        self.assertEqual(ChannelSubscription.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.client.get('/api/news/', {'scope': 'ungrouped'}).data['count'], 1)

    def test_names_validate_trimmed_length_and_unique_per_user(self):
        a = self.group(' AI ')
        self.assertEqual(ChannelGroup.objects.get(pk=a).name, 'AI')
        for name in ('AI', '', '   ', 'x' * 41, None, 123):
            self.assertEqual(self.client.post('/api/me/channel-groups/', {'name': name}, format='json').status_code, 400)
        self.group('x' * 40)
        self.client.force_authenticate(self.other)
        self.group('AI')

    def test_ownership_404_on_every_group_route_and_scope(self):
        a = self.group()
        self.client.force_authenticate(self.other)
        for method, path, payload in [
            ('get', f'/api/me/channel-groups/{a}/', {}),
            ('patch', f'/api/me/channel-groups/{a}/', {'name': 'Stolen'}),
            ('delete', f'/api/me/channel-groups/{a}/', {}),
            ('patch', '/api/me/news-preferences/', {'scope': 'group', 'group_id': a}),
            ('post', '/api/me/channel-subscriptions/', {'action': 'set_groups', 'source_ids': [], 'group_ids': [a]}),
        ]:
            self.assertEqual(getattr(self.client, method)(path, payload, format='json').status_code, 404)
        for mode in ('keyword', 'semantic', 'hybrid'):
            self.assertEqual(self.client.get('/api/news/', {'scope': 'group', 'group_id': a, 'search': 'query', 'mode': mode}).status_code, 404)
        self.assertEqual(self.client.get('/api/me/channel-groups/').data, [])
        self.assertEqual(self.client.get('/api/me/channel-subscriptions/').data, [])
        self.assertEqual(self.client.get('/api/me/news-preferences/').data['scope'], 'all')

    def test_preference_sync_between_sessions_and_no_get_writes(self):
        self.assertFalse(NewsPreference.objects.filter(user=self.user).exists())
        self.client.get('/api/me/news-preferences/')
        self.assertFalse(NewsPreference.objects.filter(user=self.user).exists())
        self.client.patch('/api/me/news-preferences/', {'scope': 'ungrouped'}, format='json')
        second_device = APIClient(); second_device.force_authenticate(self.user)
        self.assertEqual(second_device.get('/api/me/news-preferences/').data['scope'], 'ungrouped')

    def test_directory_includes_zero_article_channels_and_retired_status_without_writes(self):
        sync_channel_catalog()
        retired = public_legacy(Source.objects.create(name='Reuters', url='https://reuters.com'))
        before = Source.objects.count()
        self.client.force_authenticate(None)
        response = self.client.get('/api/sources/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Source.objects.count(), before)
        self.assertTrue(any(s['news_count'] == 0 and s['subscription_status'] == 'active' for s in response.data))
        self.assertEqual(next(s for s in response.data if s['id'] == retired.id)['subscription_status'], 'inactive')
        self.client.force_authenticate(self.user)
        self.assertEqual(self.subscribe([retired.id]).status_code, 400)
        ChannelSubscription.objects.create(user=self.user, source=retired)
        historical = self.story(retired, 'Historical')
        self.assertIn(historical.id, [n['id'] for n in self.client.get('/api/news/', {'scope': 'subscribed'}).data['results']])
        self.assertEqual(self.subscribe([retired.id]).status_code, 200)

    def test_invalid_batches_atomic_and_foreign_members_rejected(self):
        self.assertEqual(self.subscribe([self.source.id, 999999]).status_code, 404)
        self.assertEqual(ChannelSubscription.objects.filter(user=self.user).count(), 0)
        a = self.group()
        for path, method in [('/api/me/channel-groups/', 'post'), ('/api/me/channel-subscriptions/', 'post'), ('/api/me/news-preferences/', 'patch')]:
            self.assertEqual(getattr(self.client, method)(path, [], format='json').status_code, 400)
        for payload in ({'source_ids': [self.source.id]}, {'add_source_ids': [self.source.id]}, {'source_ids': '1'}, {'source_ids': [True]}):
            self.assertEqual(self.client.patch(f'/api/me/channel-groups/{a}/', payload, format='json').status_code, 400)
        for payload in ({'source_ids': '1'}, {'source_ids': [True]}, {'source_ids': [0]}, {'source_ids': [-1]}, {'source_ids': [1.1]}):
            self.assertEqual(self.client.post('/api/me/channel-subscriptions/', payload, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/me/news-preferences/', {'scope': 'invalid'}, format='json').status_code, 400)

    def test_anonymous_csrf_and_read_only_gates(self):
        anonymous = APIClient()
        for path in ('channel-subscriptions', 'channel-groups', 'news-preferences'):
            self.assertEqual(anonymous.get(f'/api/me/{path}/').status_code, 403)
        self.assertEqual(anonymous.get('/api/news/', {'scope': 'subscribed'}).status_code, 403)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post('/api/me/channel-groups/', {'name': 'CSRF'}, format='json').status_code, 403)
        with override_settings(PUBLIC_SITE_MODE='read_only'):
            self.assertEqual(self.client.get('/api/me/channel-groups/').status_code, 403)
            self.assertEqual(self.client.get('/api/news/', {'scope': 'subscribed'}).status_code, 403)
            self.assertEqual(anonymous.get('/api/sources/').status_code, 200)
            self.assertEqual(anonymous.get('/api/news/').status_code, 200)

    @patch('api.services.embedding.EmbeddingService.is_loaded', return_value=True)
    @patch('api.services.search_index_control.index_version_is_current', return_value=True)
    @patch('api.services.vector_store.VectorStoreService')
    def test_all_search_modes_share_scope_blocking_dedup_and_filters(self, vector, index, embedding):
        self.subscribe([self.source.id, self.second.id])
        group = self.group(); self.assign(group, [self.source.id, self.second.id])
        blocked = self.story(self.source, 'Blocked')
        duplicate = self.story(self.source, 'Duplicate', related_to=self.first)
        wrong_category = self.story(self.source, 'Other-category', category=self.other_category)
        BlockedNews.objects.create(user=self.user, news=blocked)
        candidates = [self.outside_story, blocked, duplicate, wrong_category, self.first, self.second_story, self.first]
        vector.return_value.count.return_value = 100
        vector.return_value.search.return_value = [(n.id, 0.9) for n in candidates]
        for mode in ('keyword', 'semantic', 'hybrid'):
            for scope in ('subscribed', 'group'):
                response = self.client.get('/api/news/', {'scope': scope, 'group_id': group, 'search': 'shared query', 'mode': mode,
                    'category': self.category.id, 'source': self.source.id, 'page_size': 1})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['count'], 1, (scope, mode, response.data))
                self.assertEqual([n['id'] for n in response.data['results']], [self.first.id])
        self.assign(group, [])
        for mode in ('keyword', 'semantic', 'hybrid'):
            self.assertEqual(self.client.get('/api/news/', {'scope': 'group', 'group_id': group, 'search': 'shared query', 'mode': mode}).data['count'], 0)
        self.assertEqual(self.client.get('/api/news/', {'scope': 'subscribed', 'search': '共享搜索', 'mode': 'hybrid'}).data['count'], 3)

    @patch('api.services.search_index_control.index_version_is_current', return_value=False)
    def test_semantic_fallback_keeps_scope_and_legacy_no_scope_works(self, index):
        self.subscribe([self.source.id])
        for mode in ('semantic', 'hybrid'):
            response = self.client.get('/api/news/', {'scope': 'subscribed', 'search': 'shared query', 'mode': mode})
            self.assertEqual(response.data['count'], 1)
            self.assertEqual(response.data['search_warning'], 'semantic_index_unavailable')
        self.assertEqual(self.client.get('/api/news/').data['count'], 3)
        self.assertEqual(self.client.get('/api/news/', {'scope': 'bad', 'search': 'q', 'mode': 'semantic'}).status_code, 400)
