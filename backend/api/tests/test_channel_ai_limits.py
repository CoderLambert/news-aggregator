from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from api.models import Source, ChannelSubscription, ChannelGroup
from api.smart_channel_models import ChannelGroupingProposal, ChannelGroupingConfig
from api.services.channel_ai import retry_delay, execute_job, process_incremental_subscriptions


class RetryHeaderTests(SimpleTestCase):
    def error(self, status, header=''):
        return SimpleNamespace(status_code=status, response=SimpleNamespace(status_code=status, headers={'retry-after': header}))

    def test_obeys_numeric_retry_after_and_minimum_backoff(self):
        self.assertEqual(retry_delay(self.error(429, '120')), 120)
        self.assertIsNone(retry_delay(self.error(503, '2')))
        self.assertEqual(retry_delay(self.error(429, '2')), 60)

    def test_invalid_or_huge_headers_do_not_create_unbounded_retries(self):
        for header in ['NaN', 'inf', '-inf', '10000000000000']:
            self.assertIsNone(retry_delay(self.error(429, header)))
        self.assertIsNone(retry_delay(self.error(503, 'invalid-date')))

    def test_nontransient_errors_do_not_retry(self):
        self.assertIsNone(retry_delay(self.error(400)))
        self.assertIsNone(retry_delay(self.error(401)))
        self.assertIsNone(retry_delay(self.error(403)))


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
class DurableGroupingLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('grouping-lease-reader')
        self.source, _ = Source.objects.get_or_create(name='React Blog', defaults={'url': 'https://react.dev'})

    def test_cancelled_claim_never_calls_a_provider(self):
        job = ChannelGroupingProposal.objects.create(user=self.user, engine='ai', status='cancelled',
            input_snapshot='', source_ids=[self.source.pk], expires_at=timezone.now() + timedelta(hours=1))
        with patch('api.services.channel_ai.build_gateway_client', side_effect=AssertionError('cancelled job called provider')) as client:
            execute_job(job)
        client.assert_not_called()

    def test_dispatched_or_legacy_unknown_lease_never_requeues(self):
        from api.services.channel_ai import claim_next
        for frozen, dispatched in [({'schema_version': 1}, timezone.now()), ({}, None)]:
            job = ChannelGroupingProposal.objects.create(user=self.user, engine='ai', status='running',
                input_snapshot='', execution_snapshot=frozen, dispatch_started_at=dispatched,
                lease_token='old', lease_until=timezone.now() - timedelta(seconds=1), attempts=1,
                expires_at=timezone.now() + timedelta(hours=1))
            self.assertIsNone(claim_next())
            job.refresh_from_db()
            self.assertEqual(job.status, 'failed')
            self.assertEqual(job.error_code, 'worker_interrupted')

    def test_old_subscriptions_do_not_starve_new_subscription_processing(self):
        old = ChannelSubscription.objects.create(user=self.user, source=self.source)
        ChannelSubscription.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        group = ChannelGroup.objects.create(user=self.user, name='New source group')
        ChannelGroupingConfig.objects.create(user=self.user, mode='suggest', bindings={'ai': group.pk})
        second, _ = Source.objects.get_or_create(name='OpenAI Blog', defaults={'url': 'https://openai.com/news'})
        new = ChannelSubscription.objects.create(user=self.user, source=second)
        with patch('api.services.channel_ai.process_subscription') as process:
            self.assertEqual(process_incremental_subscriptions(limit=1), 1)
            process.assert_called_once_with(new.pk)


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True, AI_BYOK_ENABLED=True)
class ModelSnapshotTests(SimpleTestCase):
    def test_owner_scope_and_exact_model_snapshot_are_required(self):
        from dataclasses import asdict
        from api.services.ai_credentials import ConnectionSnapshot
        from api.services.ai_task_preferences import TaskModelSnapshot
        from api.services.channel_model import verify_model, ClassificationAuthorizationChanged
        connection = ConnectionSnapshot(1, '11111111-1111-4111-8111-111111111111', 1, 1, 'deepseek', 'global', 1)
        model = TaskModelSnapshot(1, 'default', 'explicit', 1,
            '22222222-2222-4222-8222-222222222222', 1, 'deepseek-chat', 'deepseek/deepseek-flash',
            connection, '33333333-3333-4333-8333-333333333333', None)
        payload = {'schema_version': 1, 'scope': 'personal', 'consent': True, 'model': asdict(model)}
        with patch('api.services.channel_model.check_at_claim'), patch('api.services.channel_model.require_task_model_snapshot'):
            self.assertEqual(verify_model(payload, owner_id=1, scope='personal'), model)
            for owner, scope in [(2, 'personal'), (1, 'site')]:
                with self.assertRaises(ClassificationAuthorizationChanged):
                    verify_model(payload, owner_id=owner, scope=scope)
            with self.assertRaises(ClassificationAuthorizationChanged):
                verify_model({**payload, 'consent': False}, owner_id=1, scope='personal')
