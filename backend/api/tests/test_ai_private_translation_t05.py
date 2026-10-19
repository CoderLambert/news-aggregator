"""T05 synthetic integration: durable jobs, private results and no paid replay."""
from datetime import timedelta
import sqlite3
import uuid
from unittest.mock import patch
from types import SimpleNamespace

from django.db import IntegrityError, OperationalError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (ChatGPTTranslationTask, ChatGPTArticleTranslation,
                        ChatGPTSubscriptionConnection, SharedArticleTranslation)
from api.services import ai_private_translation as service
from api.services import chatgpt_subscription_jobs as subscription_jobs
from api.tests import test_ai_article_chat_t04 as fixtures
from api.tests.test_ai_article_chat_t04 import FakeGateway, gateway_frame


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True, AI_BYOK_ENABLED=True,
                   PROVIDER_CREDENTIAL_ENCRYPTION_KEY='t04-synthetic-local-credential-material')
class PrivateTranslationTests(TransactionTestCase):
    _verify_text = fixtures.PersonalArticleChatTests._verify_text

    def setUp(self):
        fixtures.PersonalArticleChatTests.setUp(self)
        self.url = f'/api/news/{self.news.pk}/byok-translation/'
        self.request_id = str(uuid.uuid4())

    def start(self, **values):
        request_id = values.pop('request_id', self.request_id)
        return self.client.post(self.url, {
            'model_config_id': str(self.model.pk), 'billing_consent': True,
            'target_language': 'zh', **values,
        }, format='json', HTTP_IDEMPOTENCY_KEY=request_id)

    def queued(self):
        with patch.object(service, '_dispatch') as dispatch:
            response = self.start()
        self.assertEqual(response.status_code, 202, response.content)
        dispatch.assert_called_once()
        return ChatGPTTranslationTask.objects.get(pk=response.data['task_id'])

    def execute(self, task, frames=None, on_send=None):
        gateway = FakeGateway(frames if frames is not None else [gateway_frame('完整中文译文。')], on_send)
        with patch.object(service, 'build_gateway_client', return_value=gateway):
            service.run_translation(task.pk, task.generation)
        task.refresh_from_db()
        return gateway

    def test_complete_commit_and_get_reopen_same_private_result_without_dispatch(self):
        task = self.queued()
        gateway = self.execute(task)
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(gateway.sent[0]['model'], 'deepseek/deepseek-flash')
        self.assertNotIn('response_format', gateway.sent[0])
        self.assertTrue(gateway.closed)
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)
        self.assertEqual(SharedArticleTranslation.objects.count(), 0)
        result_id = task.result['result_id']
        with patch.object(service, '_dispatch') as dispatch:
            first = self.client.get(f'/api/me/ai/translations/{task.pk}/')
            latest = self.client.get(self.url)
            again = self.start()
        dispatch.assert_not_called()
        self.assertEqual(first.data['result']['result_id'], result_id)
        self.assertEqual(latest.data['task']['task_id'], str(task.pk))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['task_id'], str(task.pk))
        self.assertEqual(ChatGPTTranslationTask.objects.count(), 1)

    def test_same_key_changed_model_or_source_conflicts_and_other_key_cannot_duplicate_source(self):
        task = self.queued()
        with patch.object(service, '_dispatch') as dispatch:
            same = self.start()
            different_key = self.start(request_id=str(uuid.uuid4()))
            self.news.title += ' changed'
            self.news.save(update_fields=['title'])
            changed = self.start()
        self.assertEqual(same.data['task_id'], str(task.pk))
        self.assertEqual(different_key.status_code, 409)
        self.assertEqual(changed.status_code, 409)
        dispatch.assert_not_called()

    def test_missing_or_coerced_consent_oversize_and_unproved_model_never_create_or_send(self):
        with patch.object(service, '_dispatch') as dispatch:
            for consent in (False, None, 'true', 1):
                self.assertEqual(self.start(billing_consent=consent).status_code, 400)
            with patch.object(service, 'MAX_INPUT_CHARS', 1):
                self.assertEqual(self.start().status_code, 400)
            self.model.last_text_attempt = None
            self.model.save(update_fields=['last_text_attempt'])
            self.assertEqual(self.start().status_code, 409)
        dispatch.assert_not_called()
        self.assertFalse(ChatGPTTranslationTask.objects.exists())

    def test_sse_close_and_get_do_not_dispatch_or_cancel_durable_worker(self):
        task = self.queued()
        with patch.object(service, '_dispatch') as dispatch, patch.object(subscription_jobs, '_dispatch_task') as old:
            response = self.client.get(f'/api/me/ai/translations/{task.pk}/events/')
            iterator = iter(response.streaming_content)
            self.assertIn(b'queued', next(iterator))
            response.close()
            self.client.get(f'/api/me/ai/translations/{task.pk}/')
            self.client.get(self.url)
        dispatch.assert_not_called()
        old.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, 'queued')
        self.execute(task)
        self.assertEqual(task.status, 'succeeded')

    def test_expired_started_job_read_is_interrupted_without_mutation_or_rebill(self):
        task = self.queued()
        task.status = 'running'
        task.provider_started = True
        task.run_token = uuid.uuid4()
        task.lease_expires_at = timezone.now() - timedelta(seconds=1)
        task.save()
        with patch.object(service, '_dispatch') as dispatch:
            response = self.client.get(f'/api/me/ai/translations/{task.pk}/')
            self.start()
        self.assertEqual(response.data['status'], 'interrupted')
        dispatch.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, 'running')
        self.assertTrue(task.provider_started)

    def test_owner_isolation_and_subscription_cancellation_cannot_touch_byok(self):
        task = self.queued()
        other = APIClient()
        other.force_login(self.other)
        self.assertEqual(other.get(f'/api/me/ai/translations/{task.pk}/').status_code, 404)
        self.assertEqual(other.get(self.url).data, {'task': None})
        self.assertIsNone(subscription_jobs.get_task(task.pk, user_id=self.owner.pk))
        cancelled, changed = subscription_jobs.cancel_task(task.pk, user_id=self.owner.pk, generation=1)
        self.assertIsNone(cancelled)
        self.assertFalse(changed)
        task.refresh_from_db()
        self.assertEqual(task.status, 'queued')
        self.assertIsNone(subscription_jobs.get_job(self.owner.pk, None, self.news.pk, task.source_hash))

    def test_partial_length_tool_refusal_empty_malformed_and_post_stop_never_complete(self):
        cases = [
            [gateway_frame('partial', finish=None)],
            [gateway_frame('partial', finish='length')],
            [gateway_frame('')],
            [SimpleNamespace(choices='bad')],
            [gateway_frame('done'), gateway_frame('late', finish=None)],
            [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='text', tool_calls=[{}]),
                                                      finish_reason='stop')])],
            [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='text', refusal='no'),
                                                      finish_reason='stop')])],
            [gateway_frame('x' * (service.MAX_OUTPUT_CHARS + 1))],
        ]
        for frames in cases:
            with self.subTest(frames=repr(frames)[:80]):
                task = self.queued()
                gateway = self.execute(task, frames)
                self.assertEqual(task.status, 'failed')
                self.assertFalse(task.result)
                self.assertFalse(ChatGPTArticleTranslation.objects.exists())
                self.assertEqual(len(gateway.sent), 1)
                # Disposable test rows only, so each failure case gets fresh admission.
                task.delete()
                self.request_id = str(uuid.uuid4())

    def test_revocation_at_send_and_policy_change_after_delta_fence_result(self):
        task = self.queued()
        self.connection.credential_epoch += 1
        self.connection.save(update_fields=['credential_epoch'])
        with patch.object(service, 'build_gateway_client') as build:
            service.run_translation(task.pk, task.generation)
        build.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertFalse(ChatGPTArticleTranslation.objects.exists())

    def test_policy_version_only_change_after_terminal_prevents_commit(self):
        task = self.queued()
        def frames():
            yield gateway_frame('中文', finish=None)
            publication = self.news.source.publication
            publication.policy_version += 1
            publication.save(update_fields=['policy_version'])
            yield gateway_frame(None)
        self.execute(task, frames())
        self.assertEqual(task.status, 'failed')
        self.assertFalse(ChatGPTArticleTranslation.objects.exists())

    def test_commit_rollback_never_publishes_complete_or_replays_provider(self):
        task = self.queued()
        real_create = ChatGPTArticleTranslation.objects.create
        def fail_after_insert(**kwargs):
            real_create(**kwargs)
            raise RuntimeError('synthetic DB failure')
        with patch.object(ChatGPTArticleTranslation.objects, 'create', side_effect=fail_after_insert):
            gateway = self.execute(task)
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(task.status, 'failed')
        self.assertFalse(ChatGPTArticleTranslation.objects.exists())
        self.assertFalse(task.result)

    def test_busy_result_commit_rolls_back_then_retries_db_only(self):
        task = self.queued()
        real_create = ChatGPTArticleTranslation.objects.create
        calls = []
        def busy_once(**kwargs):
            record = real_create(**kwargs)
            calls.append(record.pk)
            if len(calls) == 1:
                driver = sqlite3.OperationalError('synthetic contention')
                driver.sqlite_errorcode = sqlite3.SQLITE_LOCKED
                raise OperationalError('synthetic contention') from driver
            return record
        with patch.object(ChatGPTArticleTranslation.objects, 'create', side_effect=busy_once):
            gateway = self.execute(task)
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)

    def test_database_xor_and_subscription_rows_preserved(self):
        subscription = ChatGPTSubscriptionConnection.objects.create(
            user=self.owner, subject_hash='subject', issuer='synthetic', issued_client_id='client',
            registration_key_hash='registration', generation=7, selected_model='subscription-model',
        )
        old = ChatGPTTranslationTask.objects.create(
            user=self.owner, connection=subscription, news=self.news, source_hash='old-source',
            model_slug='subscription-model', connection_generation=7, progress='old partial',
        )
        self.assertIsNone(old.api_connection_id)
        old.refresh_from_db()
        self.assertEqual(old.connection_generation, 7)
        self.assertEqual(old.progress, 'old partial')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChatGPTTranslationTask.objects.create(user=self.owner, news=self.news,
                source_hash='invalid', model_slug='model')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ChatGPTArticleTranslation.objects.create(user=self.owner, news=self.news,
                connection=subscription, api_connection=self.connection, source_hash='invalid',
                model_slug='model', content='invalid', completed_at=timezone.now())

    def test_csrf_and_mode_gates_prevent_admission(self):
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(self.url, {
            'model_config_id': str(self.model.pk), 'billing_consent': True, 'target_language': 'zh',
        }, format='json', HTTP_IDEMPOTENCY_KEY=self.request_id).status_code, 403)
        with override_settings(PUBLIC_AI_ENABLED=False):
            self.assertEqual(self.start().status_code, 403)
        with override_settings(AI_BYOK_ENABLED=False):
            self.assertEqual(self.start().status_code, 403)
        self.assertFalse(ChatGPTTranslationTask.objects.exists())
