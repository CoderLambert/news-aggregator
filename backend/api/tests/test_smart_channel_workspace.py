import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import Source, Category, News, ChannelGroup, ChannelSubscription, ChannelGroupMember, BlockedNews
from api.smart_channel_models import SourceTopicProfile, ChannelGroupingConfig, ChannelGroupingOverride, ChannelGroupingProposal, ReadingDay, SubscriptionGroupingState
from api.services.channel_grouping import make_proposal, process_subscription, mark_manual
from api.services.channel_topics import profile_data, digest
from api.services.channel_ai import parse_classification, claim_next, execute_job, process_incremental_subscriptions


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
class SmartChannelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('smart-reader', password='Test-reader-123')
        self.other = User.objects.create_user('other-smart-reader')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.source, _ = Source.objects.get_or_create(name='React Blog', defaults={'url': 'https://react.dev', 'language': 'en'})
        self.source2, _ = Source.objects.get_or_create(name='OpenAI Blog', defaults={'url': 'https://openai.com/news', 'language': 'en'})
        self.subscription = ChannelSubscription.objects.create(user=self.user, source=self.source)
        self.category = Category.objects.create(name='Workspace test', slug='workspace-test')
        self.news = News.objects.create(title='A public title', content='Public summary', source=self.source,
            category=self.category, url='https://example.org/workspace-story', publish_time=timezone.now())

    def propose(self, **kwargs):
        return self.client.post('/api/me/smart-channels/proposals/', {'source_ids': [self.source.pk], 'topic_keys': ['frontend'], **kwargs}, format='json')

    def apply(self, proposal_id, **kwargs):
        return self.client.post(f'/api/me/smart-channels/proposals/{proposal_id}/apply/',
            {'groups': [{'topic_key': 'frontend', 'name': 'Web development', 'source_ids': [self.source.pk]}], **kwargs}, format='json')

    def test_models_and_migrations_agree(self):
        call_command('makemigrations', 'api', check=True, dry_run=True, verbosity=0)

    def test_catalog_read_does_not_write_profiles_or_call_a_model(self):
        with patch('api.services.channel_ai.personal_clients_for_user', side_effect=AssertionError('must not call')):
            response = self.client.get('/api/smart-channels/catalog/')
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data['sources'] if r['id'] == self.source.pk)
        self.assertEqual(row['topics'], ['frontend'])
        self.assertEqual(row['news_count'], 1)
        self.assertEqual(SourceTopicProfile.objects.count(), 0)

    def test_unknown_source_has_no_fabricated_topics(self):
        source = Source.objects.create(name='A new source', url='https://example.org')
        response = self.client.get(f'/api/smart-channels/sources/{source.pk}/')
        self.assertEqual(response.data['topics'], [])
        self.assertTrue(response.data['needs_review'])

    def test_preview_does_not_mutate_groups_or_subscriptions(self):
        response = self.propose()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['result'][0]['topic_keys'], ['frontend'])
        self.assertEqual(ChannelGroup.objects.count(), 0)
        self.assertEqual(ChannelSubscription.objects.filter(user=self.user).count(), 1)

    def test_apply_is_additive_and_idempotent(self):
        proposal = self.propose().data['id']
        first = self.apply(proposal)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['applied_count'], 1)
        self.assertEqual(self.apply(proposal).status_code, 200)
        self.assertEqual(ChannelGroupMember.objects.count(), 1)
        self.assertEqual(ChannelGroup.objects.count(), 1)

    def test_duplicate_request_id_requires_identical_inputs(self):
        request_id = str(uuid.uuid4())
        first = self.propose(request_id=request_id)
        second = self.propose(request_id=request_id)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(self.propose(request_id=request_id, topic_keys=['ai']).status_code, 409)

    def test_preview_rejects_unsubscribed_source_and_other_user_group(self):
        self.assertEqual(self.propose(source_ids=[self.source2.pk]).status_code, 404)
        group = ChannelGroup.objects.create(user=self.other, name='Private')
        proposal = self.propose().data['id']
        response = self.apply(proposal, groups=[{'topic_key': 'frontend', 'group_id': group.pk, 'source_ids': [self.source.pk]}])
        self.assertEqual(response.status_code, 404)
        self.assertFalse(group.subscriptions.exists())

    def test_private_proposal_cannot_be_read_by_another_account(self):
        proposal = self.propose().data['id']
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/me/smart-channels/proposals/{proposal}/').status_code, 404)
        self.assertEqual(self.apply(proposal).status_code, 404)

    def test_changed_group_rejects_stale_preview(self):
        proposal = self.propose().data['id']
        ChannelGroup.objects.create(user=self.user, name='Another group')
        self.assertEqual(self.apply(proposal).status_code, 409)
        self.assertEqual(ChannelGroupMember.objects.count(), 0)

    def test_manual_metadata_edit_invalidates_old_preview(self):
        proposal = self.propose().data['id']
        SourceTopicProfile.objects.create(source=self.source, origin='manual', topics=['technology'], about='Changed editorial scope')
        self.assertEqual(self.apply(proposal).status_code, 409)
        self.assertFalse(ChannelGroupMember.objects.exists())

    def test_expired_and_cancelled_proposals_cannot_apply(self):
        proposal = self.propose().data['id']
        ChannelGroupingProposal.objects.filter(pk=proposal).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.apply(proposal).status_code, 409)
        proposal2 = self.propose().data['id']
        self.assertEqual(self.client.post(f'/api/me/smart-channels/proposals/{proposal2}/cancel/', {}, format='json').status_code, 200)
        self.assertEqual(self.apply(proposal2).status_code, 409)

    def test_existing_same_name_requires_explicit_existing_group(self):
        group = ChannelGroup.objects.create(user=self.user, name='Web development')
        proposal = self.propose().data['id']
        self.assertEqual(self.apply(proposal).status_code, 409)
        self.assertEqual(self.apply(proposal, groups=[{'topic_key': 'frontend', 'group_id': group.pk, 'source_ids': [self.source.pk]}]).status_code, 200)

    def test_undo_preserves_subscriptions_and_empty_group(self):
        proposal = self.propose().data['id']
        self.apply(proposal)
        endpoint = f'/api/me/smart-channels/proposals/{proposal}/undo/'
        self.assertEqual(self.client.post(endpoint, {}, format='json').status_code, 200)
        self.assertEqual(self.client.post(endpoint, {}, format='json').status_code, 200)
        self.assertEqual(ChannelGroupMember.objects.count(), 0)
        self.assertEqual(ChannelGroup.objects.count(), 1)
        self.assertEqual(ChannelSubscription.objects.count(), 1)

    def test_undo_does_not_remove_later_manual_decision(self):
        proposal = self.propose().data['id']
        self.apply(proposal)
        group = ChannelGroup.objects.get(user=self.user)
        mark_manual(self.user, self.source.pk, set(), {group.pk})
        self.client.post(f'/api/me/smart-channels/proposals/{proposal}/undo/', {}, format='json')
        self.assertEqual(ChannelGroupMember.objects.count(), 1)

    def test_manual_remove_through_existing_api_is_remembered(self):
        group = ChannelGroup.objects.create(user=self.user, name='Frontend')
        group.subscriptions.add(self.subscription)
        response = self.client.patch(f'/api/me/channel-groups/{group.pk}/', {'remove_source_ids': [self.source.pk]}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ChannelGroupingOverride.objects.get(user=self.user, source=self.source, group=group).suppressed)

    def test_auto_mode_only_assigns_new_subscriptions_to_bound_groups(self):
        group = ChannelGroup.objects.create(user=self.user, name='My AI')
        ChannelGroupingConfig.objects.create(user=self.user, mode='auto', bindings={'ai': group.pk})
        response = self.client.post('/api/me/channel-subscriptions/', {'action': 'subscribe', 'source_ids': [self.source2.pk]}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(group.subscriptions.values_list('source_id', flat=True)), [self.source2.pk])
        self.assertEqual(ChannelSubscription.objects.filter(user=self.user).count(), 2)

    def test_suggestion_mode_does_not_auto_apply(self):
        group = ChannelGroup.objects.create(user=self.user, name='My AI')
        ChannelGroupingConfig.objects.create(user=self.user, mode='suggest', bindings={'ai': group.pk})
        new = ChannelSubscription.objects.create(user=self.user, source=self.source2)
        process_subscription(new.pk)
        process_subscription(new.pk)
        self.assertFalse(group.subscriptions.exists())
        self.assertEqual(ChannelGroupingProposal.objects.filter(user=self.user).count(), 1)

    def test_unchanged_pending_does_not_starve_new_subscription(self):
        group = ChannelGroup.objects.create(user=self.user, name='My Frontend')
        cfg = ChannelGroupingConfig.objects.create(user=self.user, mode='suggest', bindings={'frontend': group.pk},
            active_since=timezone.now() - timedelta(days=1))
        sources = Source.objects.bulk_create([
            Source(name=f'No-topic {i}', url=f'https://example.org/{i}') for i in range(105)
        ])
        subscriptions = ChannelSubscription.objects.bulk_create([
            ChannelSubscription(user=self.user, source=s) for s in sources
        ])
        states = []
        for subscription in subscriptions:
            profile = profile_data(subscription.source)
            signature = digest([profile['evidence_hash'], profile['topics'], profile['origin'], cfg.revision])
            states.append(SubscriptionGroupingState(subscription=subscription, status='pending', profile_hash=signature))
        SubscriptionGroupingState.objects.bulk_create(states)
        newcomer = ChannelSubscription.objects.create(user=self.user, source=self.source2)
        with patch('api.services.channel_ai.process_subscription') as processor:
            self.assertEqual(process_incremental_subscriptions(limit=1), 1)
        processor.assert_called_once_with(newcomer.pk)

    def test_ai_requires_explicit_consent_and_credentials(self):
        self.assertEqual(self.propose(engine='ai').status_code, 400)
        self.assertEqual(self.propose(engine='ai', consent=True).status_code, 400)

    def test_ai_job_is_queued_and_validated_before_any_group_write(self):
        with patch('api.services.channel_grouping.credential_fingerprint', return_value='test-fingerprint'):
            proposal = make_proposal(self.user, {'source_ids': [self.source.pk], 'topic_keys': ['frontend'], 'engine': 'ai', 'consent': True})
        self.assertEqual(proposal.status, 'queued')
        job = claim_next()
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=json.dumps({'channels': [{'source_id': self.source.pk, 'topic_keys': ['frontend'], 'reason': '浏览器和框架技术'}]})))])
        with patch('api.services.channel_ai.credential_fingerprint', return_value='test-fingerprint'), patch('api.services.channel_ai.personal_clients_for_user', return_value=[(client, 'test-model')]):
            execute_job(job)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'ready')
        self.assertEqual(proposal.result[0]['origin'], 'ai')
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertFalse(ChannelGroupMember.objects.exists())

    def test_lease_recovery_has_bounded_attempts(self):
        with patch('api.services.channel_grouping.credential_fingerprint', return_value='test'):
            proposal = make_proposal(self.user, {'source_ids': [self.source.pk], 'engine': 'ai', 'consent': True})
        first = claim_next()
        ChannelGroupingProposal.objects.filter(pk=first.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        second = claim_next()
        self.assertEqual(second.attempts, 2)
        ChannelGroupingProposal.objects.filter(pk=second.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(claim_next())
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'failed')

    def test_invalid_ai_ids_or_topics_are_rejected(self):
        evidence = [{'source_id': self.source.pk, 'name': self.source.name}]
        for source_id, topics in [(999999, ['frontend']), (self.source.pk, ['invented']), (True, ['frontend'])]:
            with self.assertRaises(ValueError):
                parse_classification(json.dumps({'channels': [{'source_id': source_id, 'topic_keys': topics, 'reason': 'test'}]}), evidence, ['frontend'])
        with self.assertRaises(ValueError):
            parse_classification('not json', evidence, ['frontend'])

    def test_reading_stats_are_real_deduplicated_and_private(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/me/reading-stats/', {'news_id': self.news.pk}, format='json').status_code, 200)
        data = self.client.get('/api/me/reading-stats/').data
        self.assertEqual(data['today'], 1)
        self.assertEqual(data['total'], 1)
        self.assertEqual(ReadingDay.objects.count(), 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/me/reading-stats/').data['total'], 0)

    def test_no_popularity_data_uses_latest_not_fake_hotness(self):
        self.assertEqual(self.client.get('/api/smart-channels/dashboard/').data['kind'], 'latest')
        self.client.post('/api/me/reading-stats/', {'news_id': self.news.pk}, format='json')
        self.assertEqual(self.client.get('/api/smart-channels/dashboard/').data['kind'], 'popular')

    def test_blocked_news_cannot_be_recorded_or_returned_as_trending(self):
        BlockedNews.objects.create(user=self.user, news=self.news)
        self.assertEqual(self.client.post('/api/me/reading-stats/', {'news_id': self.news.pk}, format='json').status_code, 404)
        stories = self.client.get('/api/smart-channels/dashboard/').data['stories']
        self.assertFalse(any(s['id'] == self.news.pk for s in stories))

    def test_feed_resolution_is_catalog_only_and_has_no_network_side_effect(self):
        response = self.client.post('/api/smart-channels/resolve/', {'url': 'https://react.dev/rss.xml'}, format='json')
        self.assertTrue(response.data['supported'])
        count = Source.objects.count()
        response = self.client.post('/api/smart-channels/resolve/', {'url': 'https://unregistered.example.org/feed'}, format='json')
        self.assertFalse(response.data['supported'])
        self.assertEqual(Source.objects.count(), count)

    def test_private_or_credential_urls_are_rejected(self):
        for url in ['http://127.0.0.1/feed', 'http://localhost/feed', 'https://secret:password@example.org/rss', 'file:///etc/passwd']:
            self.assertEqual(self.client.post('/api/smart-channels/resolve/', {'url': url}, format='json').status_code, 400)

    def test_nonadmin_cannot_enable_site_key_or_edit_metadata(self):
        self.assertEqual(self.client.patch('/api/admin/smart-channels/', {'enabled': True, 'consent': True}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(f'/api/smart-channels/sources/{self.source.pk}/', {'topics': ['ai']}, format='json').status_code, 403)

    @override_settings(PUBLIC_SITE_MODE='read_only')
    def test_read_only_blocks_personal_writes_but_keeps_public_workspace_reads(self):
        self.assertEqual(self.propose().status_code, 403)
        self.assertEqual(self.client.post('/api/me/reading-stats/', {'news_id': self.news.pk}, format='json').status_code, 403)
        for path in ['/api/smart-channels/catalog/', '/api/smart-channels/dashboard/', f'/api/smart-channels/sources/{self.source.pk}/']:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_session_mutations_require_csrf_before_method_dispatch(self):
        browser = APIClient(enforce_csrf_checks=True)
        browser.force_login(self.user)
        # DRF authenticates the session and enforces CSRF before deciding 405.
        self.assertEqual(browser.post('/api/me/smart-channels/settings/', {'mode': 'auto'}, format='json').status_code, 403)
        self.assertEqual(browser.patch('/api/me/smart-channels/settings/', {'mode': 'auto'}, format='json').status_code, 403)

    def test_expected_viewer_header_rejects_a_changed_session(self):
        browser = APIClient()
        browser.force_login(self.other)
        response = browser.patch('/api/me/smart-channels/settings/', {'mode': 'auto'}, format='json', HTTP_X_WORKSPACE_VIEWER=str(self.user.pk))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ChannelGroupingConfig.objects.filter(user=self.other).exists())
