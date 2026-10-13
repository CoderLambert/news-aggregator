from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from api.models import Source, ChannelSubscription
from api.smart_channel_models import ChannelGroupingProposal, ChannelGroupingConfig
from api.services.channel_ai import retry_delay, execute_job, process_incremental_subscriptions


class RetryHeaderTests(SimpleTestCase):
    def error(self, status, header=''):
        return SimpleNamespace(status_code=status, response=SimpleNamespace(status_code=status, headers={'retry-after': header}))

    def test_obeys_numeric_retry_after_and_minimum_backoff(self):
        self.assertEqual(retry_delay(self.error(429, '120')), 120)
        self.assertEqual(retry_delay(self.error(503, '2')), 60)

    def test_invalid_or_huge_headers_do_not_create_unbounded_retries(self):
        for header in ['NaN', 'inf', '-inf', '10000000000000']:
            self.assertIsNone(retry_delay(self.error(429, header)))
        self.assertEqual(retry_delay(self.error(503, 'invalid-date')), 60)

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
        with patch('api.services.channel_ai.personal_clients_for_user', side_effect=AssertionError('cancelled job called provider')) as client:
            execute_job(job)
        client.assert_not_called()

    def test_old_subscriptions_do_not_starve_new_subscription_processing(self):
        old = ChannelSubscription.objects.create(user=self.user, source=self.source)
        ChannelSubscription.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
        ChannelGroupingConfig.objects.create(user=self.user, mode='suggest', bindings={})
        second, _ = Source.objects.get_or_create(name='OpenAI Blog', defaults={'url': 'https://openai.com/news'})
        new = ChannelSubscription.objects.create(user=self.user, source=second)
        with patch('api.services.channel_ai.process_subscription') as process:
            self.assertEqual(process_incremental_subscriptions(limit=1), 1)
            process.assert_called_once_with(new.pk)
