"""T05 synthetic integration: durable jobs, private results and no paid replay."""
from datetime import timedelta
import sqlite3
import uuid
from unittest.mock import patch
from types import SimpleNamespace

from django.db import IntegrityError, OperationalError, transaction, connection, close_old_connections
from django.db.migrations.executor import MigrationExecutor
from django.core.management import call_command
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (ChatGPTTranslationTask, ChatGPTArticleTranslation, ChatSession,
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
        self.news.source.language = 'en'
        self.news.source.save(update_fields=['language'])
        self.news.full_content = '# Synthetic article\n\nFull original Markdown for private translation.'
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['full_content', 'full_content_state'])
        stored = service.article_snapshot(self.news, self.owner)
        self.assertEqual(stored.scope, 'full')
        self.assertEqual(service.require_current(self.owner, stored, full=True).markdown,
                         self.news.full_content)
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
        with patch.object(service, 'build_gateway_client', return_value=gateway) as build:
            service.run_translation(task.pk, task.generation)
            gateway.admitted_keys = [call.args[0] for call in build.call_args_list]
        task.refresh_from_db()
        return gateway

    def complete_synthetic_private(self, content, request_id=None):
        request_id = request_id or str(uuid.uuid4())
        with patch.object(service, '_dispatch') as dispatch:
            response = self.start(request_id=request_id)
        self.assertEqual(response.status_code, 202, response.content)
        dispatch.assert_called_once()
        task = ChatGPTTranslationTask.objects.get(pk=response.data['task_id'])
        self.execute(task, [gateway_frame(content)])
        self.assertEqual(task.status, 'succeeded')
        return task

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
        dispatch.assert_called_once_with(task.pk, task.generation)

    def test_missing_or_coerced_consent_oversize_and_unproved_model_never_create_or_send(self):
        with patch.object(service, '_dispatch') as dispatch:
            for consent in (False, None, 'true', 1):
                self.assertEqual(self.start(billing_consent=consent).status_code, 400)
            with patch.object(service, 'T06_MAX_INPUT_CHARS', 1):
                self.assertEqual(self.start().status_code, 400)
            self.model.last_text_attempt = None
            self.model.save(update_fields=['last_text_attempt'])
            self.assertEqual(self.start().status_code, 409)
        dispatch.assert_not_called()
        self.assertFalse(ChatGPTTranslationTask.objects.exists())

    def test_missing_full_body_state_rejects_before_task_or_dispatch(self):
        self.news.full_content_state = 'missing'
        self.news.save(update_fields=['full_content_state'])
        self.assertNotEqual(service.article_snapshot(self.news, self.owner).scope, 'full')
        with patch.object(service, '_dispatch') as dispatch:
            response = self.start()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error_code'], 'execution_changed')
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

    @staticmethod
    def storage_busy():
        driver = sqlite3.OperationalError('synthetic contention')
        driver.sqlite_errorcode = sqlite3.SQLITE_LOCKED
        error = OperationalError('synthetic contention')
        error.__cause__ = driver
        return error

    def test_read_contention_reselects_and_rechecks_fences_without_dispatch(self):
        task = self.queued()
        before = ChatGPTTranslationTask.objects.values().get(pk=task.pk)
        real_authorize = service._authorize
        for url in (f'/api/me/ai/translations/{task.pk}/', self.url):
            calls = []
            def authorize(current):
                calls.append(current)
                if len(calls) == 1:
                    raise self.storage_busy()
                return real_authorize(current)
            with patch.object(service, '_authorize', side_effect=authorize), \
                    patch.object(service, '_dispatch') as dispatch, \
                    patch.object(service, 'build_gateway_client') as build, \
                    patch.object(subscription_jobs.time, 'sleep'):
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(calls), 2)
            self.assertIsNot(calls[0], calls[1])
            dispatch.assert_not_called()
            build.assert_not_called()
        self.assertEqual(ChatGPTTranslationTask.objects.values().get(pk=task.pk), before)

    def test_read_contention_budget_and_unclassified_errors_never_replay(self):
        task = self.queued()
        urls = (f'/api/me/ai/translations/{task.pk}/', self.url,
                f'/api/me/ai/translations/{task.pk}/events/')
        with patch.object(service, '_dispatch') as dispatch, \
                patch.object(service, 'build_gateway_client') as build, \
                patch.object(subscription_jobs.time, 'sleep'):
            for url in urls:
                with patch.object(service, '_query', side_effect=self.storage_busy()) as query:
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.data, {'error_code': 'task_storage_busy'})
                self.assertEqual(query.call_count, len(subscription_jobs.SUBMISSION_LOCK_DELAYS) + 1)
            with patch.object(service, '_query', side_effect=OperationalError('not a lock')) as query:
                with self.assertRaises(OperationalError):
                    service.get_task(self.owner, task.pk)
                self.assertEqual(query.call_count, 1)
            with transaction.atomic(), patch.object(service, '_query', side_effect=self.storage_busy()) as query:
                with self.assertRaises(service.TranslationError) as caught:
                    service.get_task(self.owner, task.pk)
                self.assertEqual(caught.exception.code, 'task_storage_busy')
                self.assertEqual(query.call_count, 1)
        dispatch.assert_not_called()
        build.assert_not_called()

    def test_read_retry_does_not_return_snapshot_after_credential_revocation(self):
        task = self.queued()
        real_authorize = service._authorize
        calls = []
        def authorize(current):
            calls.append(current)
            if len(calls) == 1:
                self.connection.credential_epoch += 1
                self.connection.save(update_fields=['credential_epoch'])
                raise self.storage_busy()
            return real_authorize(current)
        with patch.object(service, '_authorize', side_effect=authorize), \
                patch.object(subscription_jobs.time, 'sleep'), \
                patch.object(service, '_dispatch') as dispatch:
            response = self.client.get(f'/api/me/ai/translations/{task.pk}/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(calls), 2)
        dispatch.assert_not_called()

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

    def test_lost_on_commit_dispatch_recovers_only_on_explicit_identical_post(self):
        task = self.queued()
        with patch.object(service, '_dispatch') as dispatch:
            self.client.get(self.url)
            dispatch.assert_not_called()
            response = self.start()
        self.assertEqual(response.data['task_id'], str(task.pk))
        dispatch.assert_called_once_with(task.pk, task.generation)
        first = self.execute(task)
        second = self.execute(task)
        self.assertEqual(len(first.sent), 1)
        self.assertEqual(len(second.sent), 0)
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)

    def test_executor_deduplicates_queued_recovery_submissions(self):
        task = self.queued()
        key = ('byok:' + str(task.pk), task.generation)
        try:
            with patch.object(subscription_jobs, 'submit_background_task') as submit:
                service._dispatch(task.pk, task.generation)
                service._dispatch(task.pk, task.generation)
            submit.assert_called_once()
        finally:
            subscription_jobs._dispatching.discard(key)

    def test_concurrent_identical_posts_and_worker_claims_send_once(self):
        barrier = Barrier(2)
        def admit():
            close_old_connections()
            try:
                from django.contrib.auth import get_user_model
                owner = get_user_model().objects.get(pk=self.owner.pk)
                barrier.wait(timeout=5)
                task, created = service.start_translation(
                    owner, self.news.pk, model_config_id=str(self.model.pk),
                    request_id=self.request_id, billing_consent=True,
                )
                return str(task.pk), created
            finally:
                close_old_connections()
        with patch.object(service, '_dispatch'), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: admit(), range(2)))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sum(created for _, created in results), 1)
        task = ChatGPTTranslationTask.objects.get(pk=results[0][0])
        gateway = FakeGateway([gateway_frame('并发只派发一次')])
        with patch.object(service, 'build_gateway_client', return_value=gateway), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: service.run_translation(task.pk, task.generation), range(2)))
        task.refresh_from_db()
        self.assertEqual(len(gateway.sent), 1, {
            'status': task.status,
            'provider_started': task.provider_started,
            'error_code': task.error_code,
        })
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)

    def test_pre_send_sqlite_contention_retries_credential_read_before_one_send(self):
        from api.services import ai_worker_fencing

        task = self.queued()
        real_read = ai_worker_fencing.read_execution_credential
        calls = []

        def locked_once(snapshot):
            calls.append(snapshot)
            if len(calls) == 1:
                raise self.storage_busy()
            return real_read(snapshot)

        gateway = FakeGateway([gateway_frame('中文单次派发')])
        with patch.object(ai_worker_fencing, 'read_execution_credential', side_effect=locked_once), \
                patch.object(service, 'build_gateway_client', return_value=gateway) as build, \
                patch.object(subscription_jobs.time, 'sleep'):
            service.run_translation(task.pk, task.generation)

        task.refresh_from_db()
        self.assertEqual(len(calls), 2)
        build.assert_called_once()
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(task.status, 'succeeded')
        self.assertTrue(task.provider_started)
        self.assertEqual(task.error_code, '')
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)

    def test_pre_send_contention_retry_rechecks_credential_revocation(self):
        from api.services import ai_worker_fencing

        task = self.queued()
        real_read = ai_worker_fencing.read_execution_credential
        calls = []

        def revoke_then_lock(snapshot):
            calls.append(snapshot)
            if len(calls) == 1:
                self.connection.credential_epoch += 1
                self.connection.save(update_fields=['credential_epoch'])
                raise self.storage_busy()
            return real_read(snapshot)

        with patch.object(ai_worker_fencing, 'read_execution_credential', side_effect=revoke_then_lock), \
                patch.object(service, 'build_gateway_client') as build, \
                patch.object(subscription_jobs.time, 'sleep'):
            service.run_translation(task.pk, task.generation)

        task.refresh_from_db()
        self.assertEqual(len(calls), 2)
        build.assert_not_called()
        self.assertEqual(task.status, 'failed')
        self.assertFalse(task.provider_started)
        self.assertFalse(task.result)
        self.assertFalse(ChatGPTArticleTranslation.objects.exists())
        self.assertFalse(SharedArticleTranslation.objects.exists())

    def test_post_marker_database_lock_retries_fence_before_one_send(self):
        task = self.queued()
        real_live = service._live
        locked = []

        def lock_once_after_marker(task_id, generation, token, *, started=True):
            current = ChatGPTTranslationTask.objects.get(pk=task_id)
            if started and current.provider_started and not locked:
                locked.append(True)
                raise self.storage_busy()
            return real_live(task_id, generation, token, started=started)

        gateway = FakeGateway([gateway_frame('中文单次派发')])
        with patch.object(service, '_live', side_effect=lock_once_after_marker), \
                patch.object(service, 'build_gateway_client', return_value=gateway) as build, \
                patch.object(subscription_jobs.time, 'sleep'):
            service.run_translation(task.pk, task.generation)

        task.refresh_from_db()
        self.assertEqual(len(locked), 1)
        build.assert_called_once()
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(task.status, 'succeeded')
        self.assertTrue(task.provider_started)
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)

    def test_pre_send_database_errors_fail_closed_without_provider_send(self):
        from api.services import ai_worker_fencing

        original = self.news.full_content
        try:
            cases = (
                ('persistent_sqlite_lock', self.storage_busy, len(subscription_jobs.SUBMISSION_LOCK_DELAYS) + 1),
                ('non_lock_operational_error', lambda: OperationalError('synthetic non-lock error'), 1),
            )
            for label, make_error, expected_attempts in cases:
                with self.subTest(error=label):
                    self.news.full_content = f'# Synthetic source {label}\n\nPrivate article.'
                    self.news.save(update_fields=['full_content'])
                    self.request_id = str(uuid.uuid4())
                    task = self.queued()
                    calls = []

                    def reject_credential_read(snapshot):
                        calls.append(snapshot)
                        raise make_error()

                    with patch.object(ai_worker_fencing, 'read_execution_credential',
                                      side_effect=reject_credential_read), \
                            patch.object(service, 'build_gateway_client') as build, \
                            patch.object(subscription_jobs.time, 'sleep'):
                        service.run_translation(task.pk, task.generation)

                    task.refresh_from_db()
                    self.assertEqual(len(calls), expected_attempts)
                    build.assert_not_called()
                    self.assertEqual(task.status, 'failed')
                    self.assertFalse(task.provider_started)
                    self.assertFalse(task.result)
                    self.assertFalse(ChatGPTArticleTranslation.objects.filter(news=self.news).exists())
                    self.assertFalse(SharedArticleTranslation.objects.filter(news=self.news).exists())
        finally:
            self.news.full_content = original
            self.news.save(update_fields=['full_content'])

    def test_provider_transport_exception_is_single_send_and_terminal(self):
        self.news.full_content = '# Synthetic transport failure\n\nPrivate article.'
        self.news.save(update_fields=['full_content'])
        self.request_id = str(uuid.uuid4())
        task = self.queued()
        gateway = FakeGateway([])
        with patch.object(service, 'build_gateway_client', return_value=gateway) as build, \
                patch.object(gateway.chat.completions, 'create',
                             side_effect=OSError('synthetic provider transport failure')) as send, \
                patch.object(subscription_jobs.time, 'sleep'):
            service.run_translation(task.pk, task.generation)

        task.refresh_from_db()
        build.assert_called_once()
        send.assert_called_once()
        self.assertEqual(task.status, 'failed')
        self.assertTrue(task.provider_started)
        self.assertFalse(task.result)
        self.assertFalse(ChatGPTArticleTranslation.objects.filter(news=self.news).exists())
        self.assertFalse(SharedArticleTranslation.objects.filter(news=self.news).exists())

        # A failed task is terminal; a new worker invocation cannot replay a
        # transport attempt whose outcome may have been accepted upstream.
        service.run_translation(task.pk, task.generation)
        send.assert_called_once()
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')


    def retry(self, task, *, request_id=None, consent=True, model_id=None):
        return self.client.post(
            f'/api/me/ai/translations/{task.pk}/retry/',
            {'model_config_id': str(model_id or self.model.pk), 'billing_consent': consent,
             'target_language': 'zh'},
            format='json', HTTP_IDEMPOTENCY_KEY=request_id or str(uuid.uuid4()),
        )

    def cancel(self, task, *, generation=None):
        return self.client.post(
            f'/api/me/ai/translations/{task.pk}/cancel/',
            {'generation': task.generation if generation is None else generation},
            format='json',
        )

    def test_t07_cancel_cas_wins_before_provider_result_and_is_idempotent(self):
        task = self.queued()
        stale = self.cancel(task, generation=task.generation + 1)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(task.status, 'queued')

        responses = []
        gateway = FakeGateway([gateway_frame('不应持久化的译文')], on_send=lambda: responses.append(self.cancel(task)))
        with patch.object(service, 'build_gateway_client', return_value=gateway):
            service.run_translation(task.pk, task.generation)
        task.refresh_from_db()
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(responses[0].status_code, 200, responses[0].content)
        self.assertEqual(responses[0].data['status'], 'cancelled')
        self.assertEqual(task.status, 'cancelled')
        self.assertTrue(task.provider_started)
        self.assertFalse(task.result)
        self.assertFalse(ChatGPTArticleTranslation.objects.filter(task=task).exists())

        repeated = self.cancel(task)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['status'], 'cancelled')
        with patch.object(service, 'build_gateway_client') as build:
            service.run_translation(task.pk, task.generation)
        build.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, 'cancelled')

    def test_t07_cancel_after_finish_does_not_replace_success(self):
        task = self.queued()
        self.execute(task)
        result_before = dict(task.result)
        response = self.cancel(task)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'succeeded')
        task.refresh_from_db()
        self.assertEqual(task.result, result_before)
        self.assertTrue(ChatGPTArticleTranslation.objects.filter(task=task).exists())

    def test_t07_cancel_receipt_is_redacted_and_remains_available_after_source_change(self):
        task = self.queued()
        ChatGPTTranslationTask.objects.filter(pk=task.pk).update(
            progress='private partial text',
        )
        task.refresh_from_db()
        self.news.full_content = 'Changed source before cancellation.'
        self.news.save(update_fields=['full_content'])
        response = self.cancel(task)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['status'], 'cancelled')
        self.assertEqual(response.data['task_id'], str(task.pk))
        self.assertEqual(set(response.data), {'task_id', 'status', 'error_code'})
        self.assertNotIn('private partial text', response.content.decode())
        task.refresh_from_db()
        self.assertEqual(task.status, 'cancelled')
        self.assertEqual(task.progress, 'private partial text')
        # Reads remain denied by the source fence; the cancel receipt reveals no
        # cached private text even though it still lets the owner stop the task.
        denied = self.client.get(f'/api/me/ai/translations/{task.pk}/')
        self.assertEqual(denied.status_code, 409)

    def test_t07_explicit_retry_creates_new_attempt_and_keeps_old_result_after_failure(self):
        original = self.queued()
        self.execute(original)
        original.refresh_from_db()
        original_result = dict(original.result)
        old_row = ChatGPTArticleTranslation.objects.get(task=original)

        retry_key = str(uuid.uuid4())
        with patch.object(service, '_dispatch') as dispatch:
            accepted = self.retry(original, request_id=retry_key)
            repeated = self.retry(original, request_id=retry_key)
            conflicting = self.retry(original, request_id=str(uuid.uuid4()))
        self.assertEqual(accepted.status_code, 202, accepted.content)
        retry_id = accepted.data['task_id']
        self.assertNotEqual(retry_id, str(original.pk))
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['task_id'], retry_id)
        self.assertEqual(conflicting.status_code, 409)
        # The duplicate explicit POST may recover the same queued attempt;
        # both dispatches still pass through the worker's one-shot claim CAS.
        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual(dispatch.call_args[0], (uuid.UUID(retry_id), 1))
        current = ChatGPTTranslationTask.objects.get(pk=retry_id)
        self.assertEqual(current.execution_snapshot['retry_of'], str(original.pk))
        self.assertEqual(original.result, original_result)
        self.assertEqual(ChatGPTArticleTranslation.objects.get(pk=old_row.pk).content, original_result['content'])

        latest = self.client.get(self.url)
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.data['task']['task_id'], retry_id)
        self.assertEqual(latest.data['task']['previous_result'], original_result)
        reopened = self.client.get(f'/api/me/ai/translations/{original.pk}/')
        self.assertEqual(reopened.data['result'], original_result)

        # An ambiguous post-marker transport failure is terminal and never
        # overwrites the prior immutable result.
        with patch.object(service, 'build_gateway_client', side_effect=OSError('synthetic transport')):
            service.run_translation(current.pk, current.generation)
        current.refresh_from_db()
        self.assertEqual(current.status, 'failed')
        self.assertFalse(current.result)
        latest_after_failure = self.client.get(self.url)
        self.assertEqual(latest_after_failure.data['task']['task_id'], retry_id)
        self.assertEqual(latest_after_failure.data['task']['previous_result'], original_result)
        self.assertEqual(ChatGPTArticleTranslation.objects.get(pk=old_row.pk).content, original_result['content'])

        # A later, explicit fresh retry is a separate attempt/result; the old
        # successful row remains addressable and is still surfaced on recovery.
        second_key = str(uuid.uuid4())
        with patch.object(service, '_dispatch') as dispatch2:
            second = self.retry(current, request_id=second_key)
        self.assertEqual(second.status_code, 202, second.content)
        second_task = ChatGPTTranslationTask.objects.get(pk=second.data['task_id'])
        self.execute(second_task, frames=[gateway_frame('再次生成的新译文')])
        second_task.refresh_from_db()
        self.assertEqual(second_task.status, 'succeeded')
        self.assertNotEqual(second_task.result['result_id'], original_result['result_id'])
        self.assertEqual(ChatGPTArticleTranslation.objects.filter(
            user=self.owner, api_connection=self.connection, news=self.news,
            source_hash=original.source_hash,
        ).count(), 2)
        self.assertEqual(self.client.get(self.url).data['task']['previous_result'], original_result)
        self.assertEqual(self.client.get(f'/api/me/ai/translations/{original.pk}/').data['result'], original_result)

    def test_t07_retry_requires_fresh_consent_current_model_and_unchanged_source(self):
        original = self.queued()
        self.execute(original)
        with patch.object(service, '_dispatch') as dispatch:
            no_consent = self.retry(original, request_id=str(uuid.uuid4()), consent=False)
            unproved_model = self.retry(original, request_id=str(uuid.uuid4()), model_id=uuid.uuid4())
        self.assertEqual(no_consent.status_code, 400)
        self.assertEqual(unproved_model.status_code, 409)
        self.assertEqual(ChatGPTTranslationTask.objects.count(), 1)
        dispatch.assert_not_called()

        self.news.full_content = 'Changed synthetic full text.'
        self.news.save(update_fields=['full_content'])
        changed = self.retry(original, request_id=str(uuid.uuid4()))
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.data['error_code'], 'article_source_changed')
        self.assertEqual(ChatGPTTranslationTask.objects.count(), 1)

    def test_t07_retry_same_key_only_recovers_queued_unstarted_via_explicit_post(self):
        original = self.queued()
        self.execute(original)
        key = str(uuid.uuid4())
        with patch.object(service, '_dispatch') as initial_dispatch:
            accepted = self.retry(original, request_id=key)
        self.assertEqual(accepted.status_code, 202)
        child = ChatGPTTranslationTask.objects.get(pk=accepted.data['task_id'])
        initial_dispatch.assert_called_once_with(child.pk, child.generation)
        with patch.object(service, '_dispatch') as recovery_dispatch:
            recovered = self.retry(original, request_id=key)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.data['task_id'], str(child.pk))
        recovery_dispatch.assert_called_once_with(child.pk, child.generation)

        ChatGPTTranslationTask.objects.filter(pk=child.pk).update(
            status='running', provider_started=True, run_token=uuid.uuid4(),
            lease_expires_at=timezone.now() + timedelta(minutes=1),
        )
        with patch.object(service, '_dispatch') as started_dispatch:
            repeated = self.retry(original, request_id=key)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['task_id'], str(child.pk))
        started_dispatch.assert_not_called()

    def test_t07_retry_of_expired_started_task_is_explicit_and_get_remains_read_only(self):
        original = self.queued()
        token = uuid.uuid4()
        ChatGPTTranslationTask.objects.filter(pk=original.pk).update(
            status='running', provider_started=True, run_token=token,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        with patch.object(service, '_dispatch') as dispatch:
            observed = self.client.get(f'/api/me/ai/translations/{original.pk}/')
            latest = self.client.get(self.url)
        self.assertEqual(observed.status_code, 200)
        self.assertEqual(observed.data['status'], 'interrupted')
        self.assertEqual(latest.data['task']['status'], 'interrupted')
        original.refresh_from_db()
        self.assertEqual(original.status, 'running')
        dispatch.assert_not_called()

        with patch.object(service, '_dispatch') as dispatch_retry:
            response = self.retry(original, request_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 202, response.content)
        dispatch_retry.assert_called_once()
        original.refresh_from_db()
        self.assertEqual(original.status, 'interrupted')
        self.assertEqual(ChatGPTTranslationTask.objects.filter(news=self.news, status='queued').count(), 1)

    def test_t07_migration_links_results_and_fences_preexisting_cross_key_active_tasks(self):
        from api.ai_connection_models import UserAIConnection

        other_connection = UserAIConnection.objects.create(
            user=self.owner, provider_id=self.connection.provider_id,
            endpoint_profile=self.connection.endpoint_profile,
            display_name='T07 second synthetic key', request_hash='b' * 64,
        )
        targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        try:
            MigrationExecutor(connection).migrate([('api', '0065_byok_private_translation')])
            old = MigrationExecutor(connection).loader.project_state(
                [('api', '0065_byok_private_translation')]
            ).apps
            old_task_model = old.get_model('api', 'ChatGPTTranslationTask')
            old_result_model = old.get_model('api', 'ChatGPTArticleTranslation')
            task = old_task_model.objects.create(
                user_id=self.owner.pk, api_connection_id=self.connection.pk, news_id=self.news.pk,
                source_hash='t07-migration-source', model_slug='deepseek-flash',
                request_id=uuid.uuid4(), status='succeeded',
            )
            result = old_result_model.objects.create(
                user_id=self.owner.pk, api_connection_id=self.connection.pk, news_id=self.news.pk,
                source_hash='t07-migration-source', model_slug='deepseek-flash',
                content='历史私有译文', completed_at=timezone.now(),
            )
            old_task_model.objects.filter(pk=task.pk).update(result={'result_id': result.pk, 'content': result.content})
            now = timezone.now()
            old_running = old_task_model.objects.create(
                user_id=self.owner.pk, api_connection_id=self.connection.pk, news_id=self.news.pk,
                source_hash='t07-migration-active-source', model_slug='deepseek-flash',
                request_id=uuid.uuid4(), status='running', provider_started=True,
                run_token=uuid.uuid4(), lease_expires_at=now + timedelta(minutes=2),
                progress='保留的不完整私有进度', queued_at=now - timedelta(seconds=2),
            )
            newest_queued = old_task_model.objects.create(
                user_id=self.owner.pk, api_connection_id=other_connection.pk, news_id=self.news.pk,
                source_hash='t07-migration-active-source', model_slug='deepseek-flash',
                request_id=uuid.uuid4(), status='queued', queued_at=now,
            )
            original_running_token = old_running.run_token
            with patch.object(service, '_dispatch') as dispatch:
                MigrationExecutor(connection).migrate(targets)
            dispatch.assert_not_called()
            result_after = ChatGPTArticleTranslation.objects.get(pk=result.pk)
            self.assertEqual(result_after.task_id, task.pk)
            self.assertEqual(result_after.content, '历史私有译文')
            self.assertEqual(result_after.api_connection_id, self.connection.pk)
            old_running.refresh_from_db()
            newest_queued.refresh_from_db()
            self.assertEqual(old_running.status, 'interrupted')
            self.assertTrue(old_running.provider_started)
            self.assertIsNone(old_running.run_token)
            self.assertIsNone(old_running.lease_expires_at)
            self.assertEqual(old_running.progress, '保留的不完整私有进度')
            self.assertEqual(old_running.error_code, 'worker_interrupted')
            self.assertIn('仍可能计费', old_running.error_message)
            self.assertEqual(newest_queued.status, 'queued')
            self.assertEqual(newest_queued.api_connection_id, other_connection.pk)
            self.assertEqual(ChatGPTTranslationTask.objects.count(), 3)
            self.assertEqual(ChatGPTTranslationTask.objects.filter(
                news=self.news, source_hash='t07-migration-active-source',
            ).count(), 2)
            self.assertNotEqual(original_running_token, old_running.run_token)
            stale_commit = ChatGPTTranslationTask.objects.filter(
                pk=old_running.pk, generation=old_running.generation,
                status='running', run_token=original_running_token,
            ).update(status='succeeded', progress='过期工作进程不得写入')
            self.assertEqual(stale_commit, 0)
            old_running.refresh_from_db()
            self.assertEqual(old_running.status, 'interrupted')
            self.assertEqual(old_running.progress, '保留的不完整私有进度')
        finally:
            MigrationExecutor(connection).migrate(targets)

    def test_t07_cancel_and_finish_race_never_publishes_a_cancelled_result(self):
        task = self.queued()
        barrier = Barrier(2)
        real_finish = service._finish
        gateway = FakeGateway([gateway_frame('并发完成或取消')])
        def finish_at_barrier(*args, **kwargs):
            barrier.wait(timeout=5)
            return real_finish(*args, **kwargs)
        with patch.object(service, '_finish', side_effect=finish_at_barrier), \
                patch.object(service, 'build_gateway_client', return_value=gateway), \
                ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.run_translation, task.pk, task.generation)
            barrier.wait(timeout=5)
            cancel_response = self.cancel(task)
            if cancel_response.status_code == 200:
                self.assertEqual(set(cancel_response.data), {'task_id', 'status', 'error_code'})
                self.assertEqual(cancel_response.data['task_id'], str(task.pk))
                self.assertIn(cancel_response.data['status'], {'cancelled', 'succeeded'})
                expected_code = 'translation_cancelled' if cancel_response.data['status'] == 'cancelled' else ''
                self.assertEqual(cancel_response.data['error_code'], expected_code)
            elif cancel_response.status_code == 409:
                self.assertEqual(cancel_response.data, {'error_code': 'translation_request_conflict'})
            elif cancel_response.status_code == 503:
                # Storage/auth contention means cancellation is NOT_CONFIRMED.
                # Never count this as a successful cancel or replay the POST.
                self.assertEqual(set(cancel_response.data), {'error_code'})
                self.assertIn(cancel_response.data['error_code'],
                              {'task_storage_busy', 'credential_unavailable'})
            else:
                self.fail(f'unexpected cancellation response: {cancel_response.status_code} {cancel_response.data!r}')
            future.result(timeout=10)
        task.refresh_from_db()
        if task.status == 'cancelled':
            self.assertFalse(task.result)
            self.assertFalse(ChatGPTArticleTranslation.objects.filter(task=task).exists())
            if cancel_response.status_code == 200:
                self.assertEqual(cancel_response.data['status'], 'cancelled')
        else:
            self.assertEqual(task.status, 'succeeded')
            self.assertTrue(task.result)
            result = ChatGPTArticleTranslation.objects.get(task=task)
            self.assertEqual(task.result['result_id'], result.pk)
            self.assertEqual(result.content, '并发完成或取消')
            if cancel_response.status_code == 200:
                self.assertEqual(cancel_response.data['status'], 'succeeded')
        observed = self.client.get(f'/api/me/ai/translations/{task.pk}/')
        self.assertEqual(observed.status_code, 200, observed.content)
        self.assertEqual(observed.data['task_id'], str(task.pk))
        self.assertEqual(observed.data['status'], task.status)
        if task.status == 'cancelled':
            self.assertIsNone(observed.data['result'])
            self.assertFalse(ChatGPTArticleTranslation.objects.filter(task=task).exists())
        else:
            self.assertEqual(observed.data['result']['result_id'], task.result['result_id'])
            self.assertEqual(observed.data['result']['content'], '并发完成或取消')
        self.assertEqual(len(gateway.sent), 1)

    def test_t07_cancel_wins_racing_finish_prevents_result_commit(self):
        task = self.queued()
        finish_entered = Event()
        release_finish = Event()
        real_finish = service._finish
        gateway = FakeGateway([gateway_frame('取消胜出的私有译文')])

        def pause_before_finish_commit(*args, **kwargs):
            # The worker has received a complete synthetic response, but has not
            # entered its terminal DB transaction. Let cancel win the CAS first.
            finish_entered.set()
            if not release_finish.wait(timeout=5):
                raise TimeoutError('finish test gate timed out')
            return real_finish(*args, **kwargs)

        with patch.object(service, '_finish', side_effect=pause_before_finish_commit), \
                patch.object(service, 'build_gateway_client', return_value=gateway), \
                ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.run_translation, task.pk, task.generation)
            try:
                self.assertTrue(finish_entered.wait(timeout=5))
                cancel_response = self.cancel(task)
                self.assertEqual(cancel_response.status_code, 200, cancel_response.content)
                self.assertEqual(set(cancel_response.data), {'task_id', 'status', 'error_code'})
                self.assertEqual(cancel_response.data, {
                    'task_id': str(task.pk), 'status': 'cancelled',
                    'error_code': 'translation_cancelled',
                })
            finally:
                release_finish.set()
            future.result(timeout=10)

        task.refresh_from_db()
        self.assertEqual(task.status, 'cancelled')
        self.assertFalse(task.result)
        self.assertFalse(ChatGPTArticleTranslation.objects.filter(task=task).exists())
        self.assertFalse(SharedArticleTranslation.objects.exists())
        observed = self.client.get(f'/api/me/ai/translations/{task.pk}/')
        self.assertEqual(observed.status_code, 200, observed.content)
        self.assertEqual(observed.data['status'], 'cancelled')
        self.assertIsNone(observed.data['result'])
        self.assertEqual(len(gateway.sent), 1)

    def test_t07_finish_winner_racing_cancel_retains_private_result(self):
        task = self.queued()
        gateway = FakeGateway([gateway_frame('完成胜出的私有译文')])
        cancel_entered = Event()
        release_cancel = Event()
        real_cancel = service.cancel_translation

        def pause_cancel_before_cas(*args, **kwargs):
            cancel_entered.set()
            if not release_cancel.wait(timeout=5):
                raise TimeoutError('cancel test gate timed out')
            return real_cancel(*args, **kwargs)

        with patch.object(service, 'cancel_translation', side_effect=pause_cancel_before_cas), \
                patch.object(service, 'build_gateway_client', return_value=gateway), \
                ThreadPoolExecutor(max_workers=1) as pool:
            cancel_future = pool.submit(self.cancel, task)
            self.assertTrue(cancel_entered.wait(timeout=5))
            try:
                service.run_translation(task.pk, task.generation)
            finally:
                release_cancel.set()
            response = cancel_future.result(timeout=10)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.data), {'task_id', 'status', 'error_code'})
        self.assertEqual(response.data['status'], 'succeeded')
        task.refresh_from_db()
        self.assertEqual(task.status, 'succeeded')
        self.assertTrue(task.result)
        result = ChatGPTArticleTranslation.objects.get(task=task)
        self.assertEqual(result.content, '完成胜出的私有译文')
        self.assertEqual(task.result['result_id'], result.pk)
        self.assertEqual(len(gateway.sent), 1)

    def test_t07_parallel_same_key_retry_and_worker_claim_send_once(self):
        original = self.queued()
        self.execute(original)
        barrier = Barrier(2)
        def retry_same_key():
            close_old_connections()
            try:
                from django.contrib.auth import get_user_model
                owner = get_user_model().objects.get(pk=self.owner.pk)
                barrier.wait(timeout=5)
                task, created = service.retry_translation(
                    owner, original.pk, model_config_id=str(self.model.pk),
                    request_id=self.retry_request_id, billing_consent=True,
                )
                return str(task.pk), created
            finally:
                close_old_connections()
        self.retry_request_id = str(uuid.uuid4())
        with patch.object(service, '_dispatch'), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: retry_same_key(), range(2)))
        self.assertEqual(outcomes[0][0], outcomes[1][0])
        self.assertEqual(sum(created for _, created in outcomes), 1)
        self.assertEqual(ChatGPTTranslationTask.objects.count(), 2)
        retry = ChatGPTTranslationTask.objects.get(pk=outcomes[0][0])
        gateway = FakeGateway([gateway_frame('并发重试只保存一次')])
        with patch.object(service, 'build_gateway_client', return_value=gateway), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: service.run_translation(retry.pk, retry.generation), range(2)))
        retry.refresh_from_db()
        self.assertEqual(retry.status, 'succeeded')
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(ChatGPTArticleTranslation.objects.filter(task=retry).count(), 1)

    def test_t07_parallel_different_retry_keys_create_only_one_active_attempt(self):
        original = self.queued()
        self.execute(original)
        barrier = Barrier(2)
        keys = [str(uuid.uuid4()), str(uuid.uuid4())]
        def retry_with_key(request_id):
            close_old_connections()
            try:
                from django.contrib.auth import get_user_model
                owner = get_user_model().objects.get(pk=self.owner.pk)
                barrier.wait(timeout=5)
                return service.retry_translation(
                    owner, original.pk, model_config_id=str(self.model.pk),
                    request_id=request_id, billing_consent=True,
                )
            except service.TranslationError as exc:
                return exc.code
            finally:
                close_old_connections()
        with patch.object(service, '_dispatch'), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(retry_with_key, keys))
        created = [item for item in outcomes if isinstance(item, tuple) and item[1] is True]
        errors = [item for item in outcomes if isinstance(item, str)]
        self.assertEqual(len(created), 1, outcomes)
        self.assertEqual(errors, ['translation_request_conflict'])
        self.assertEqual(ChatGPTTranslationTask.objects.filter(
            user=self.owner, news=self.news, source_hash=original.source_hash,
            status__in=['queued', 'running'],
        ).count(), 1)

    def test_model_state_matches_migration(self):
        call_command('makemigrations', 'api', check=True, dry_run=True, verbosity=0)

    def test_forward_migration_preserves_existing_subscription_task_and_result(self):
        targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([('api', '0064_article_chat_turn')])
            old = executor.loader.project_state([('api', '0064_article_chat_turn')]).apps
            subscription = old.get_model('api', 'ChatGPTSubscriptionConnection').objects.create(
                user_id=self.owner.pk, subject_hash='migration-subject', issuer='synthetic',
                issued_client_id='migration-client', registration_key_hash='migration-registration',
                generation=9, selected_model='old-model',
            )
            task = old.get_model('api', 'ChatGPTTranslationTask').objects.create(
                user_id=self.owner.pk, connection_id=subscription.pk, news_id=self.news.pk,
                source_hash='migration-source', model_slug='old-model', connection_generation=9,
                status='succeeded', progress='保留旧译文', result={'scope': 'private', 'content': '保留旧译文'},
            )
            result = old.get_model('api', 'ChatGPTArticleTranslation').objects.create(
                user_id=self.owner.pk, connection_id=subscription.pk, news_id=self.news.pk,
                source_hash='migration-source', model_slug='old-model', content='保留旧译文',
                completed_at=timezone.now(),
            )
            before_task = old.get_model('api', 'ChatGPTTranslationTask').objects.values().get(pk=task.pk)
            before_result = old.get_model('api', 'ChatGPTArticleTranslation').objects.values().get(pk=result.pk)
            MigrationExecutor(connection).migrate(targets)
            after_task = ChatGPTTranslationTask.objects.values().get(pk=task.pk)
            after_result = ChatGPTArticleTranslation.objects.values().get(pk=result.pk)
            self.assertEqual({k: after_task[k] for k in before_task}, before_task)
            self.assertEqual({k: after_result[k] for k in before_result}, before_result)
            self.assertIsNone(after_task['api_connection_id'])
            self.assertIsNone(after_result['api_connection_id'])
        finally:
            MigrationExecutor(connection).migrate(targets)

    def test_two_owners_translate_same_article_with_own_keys_and_private_results(self):
        from api.ai_connection_models import UserAIConnection
        from api.ai_model_models import UserAIModelConfig
        from api.tests.test_ai_article_chat_t04 import CONNECTIONS, KEY
        task_a = self.queued()
        gateway_a = self.execute(task_a)
        original_owner, original_client = self.owner, self.client
        self.owner = self.other
        self.client = APIClient()
        self.client.force_login(self.other)
        try:
            response = self.client.post(CONNECTIONS, {
                'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
                'display_name': 'Other private key', 'api_key': KEY + '-other',
                'request_id': str(uuid.uuid4()),
            }, format='json')
            self.assertEqual(response.status_code, 201)
            connection_b = UserAIConnection.objects.get(pk=response.data['id'])
            response = self.client.post(f'{CONNECTIONS}{connection_b.pk}/models/',
                                       {'model_id': 'deepseek-flash'}, format='json')
            self.assertEqual(response.status_code, 201)
            self.model = UserAIModelConfig.objects.get(pk=response.data['id'])
            self._verify_text(self.model)
            self.request_id = str(uuid.uuid4())
            task_b = self.queued()
            gateway_b = self.execute(task_b)
            self.assertEqual(task_b.status, 'succeeded')
            self.assertNotEqual(task_a.result['result_id'], task_b.result['result_id'])
            self.assertEqual(task_a.user_id, original_owner.pk)
            self.assertEqual(task_b.user_id, self.other.pk)
            self.assertEqual(task_a.api_connection_id, self.connection.pk)
            self.assertEqual(task_b.api_connection_id, connection_b.pk)
            records = ChatGPTArticleTranslation.objects.order_by('user_id')
            self.assertEqual(records.count(), 2)
            self.assertEqual(set(records.values_list('api_connection_id', flat=True)),
                             {self.connection.pk, connection_b.pk})
            self.assertEqual(len(gateway_a.sent), 1)
            self.assertEqual(len(gateway_b.sent), 1)
            self.assertTrue(gateway_a.admitted_keys == [KEY])
            self.assertTrue(gateway_b.admitted_keys == [KEY + '-other'])
            self.assertTrue(gateway_a.admitted_keys != gateway_b.admitted_keys)
            self.assertEqual(self.client.get(f'/api/me/ai/translations/{task_a.pk}/').status_code, 404)
            self.assertEqual(original_client.get(f'/api/me/ai/translations/{task_b.pk}/').status_code, 404)
            self.assertFalse(SharedArticleTranslation.objects.exists())
        finally:
            self.owner, self.client = original_owner, original_client


    def test_t06_multibyte_block_chunking_is_deterministic_and_bounded(self):
        source = '😀' * 4000 + '\n\n' + '😃' * 4000
        chunks = service._split_t06_markdown(source)
        self.assertEqual(chunks, service._split_t06_markdown(source))
        self.assertEqual(''.join(chunks), source)
        self.assertEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), service.T06_CHUNK_INPUT_CHARS)
            self.assertLessEqual(len(chunk.encode('utf-8')), service.T06_CHUNK_INPUT_BYTES)

    def test_t06_chunking_preserves_markdown_blocks_and_private_merge_order(self):
        self.news.full_content = (
            '## Heading\n\n[Read](https://example.test/a)\n\n| left | right |\n| --- | --- |\n\n'
            '```py\nprint(1)\n```\n\n' + 'A' * 5000 + '\n\n' + 'B' * 5000
        )
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['full_content', 'full_content_state'])
        task = self.queued()
        chunks = service._task_chunks(task.execution_snapshot)
        self.assertEqual(len(chunks), 2)
        prepared = [service._split_trailing_separator(chunk) for chunk in chunks]
        self.assertTrue(any(separator for _, separator in prepared))
        # Synthetic translated prose omits source paragraph separators; the merge restores them.
        translated_bodies = [
            '## 标题\n\n[Read](https://example.test/a)\n\n'
            '| 左 | 右 |\n| --- | --- |\n\n```py\nprint(1)\n```\n\n第一段中文',
            '第二段中文',
        ]
        gateways = [FakeGateway([gateway_frame(body)]) for body in translated_bodies]
        with patch.object(service, 'build_gateway_client', side_effect=gateways) as build:
            service.run_translation(task.pk, task.generation)
        task.refresh_from_db()
        expected = ('## 标题\n\n[Read](https://example.test/a)\n\n'
                    '| 左 | 右 |\n| --- | --- |\n\n```py\nprint(1)\n```\n\n'
                    '第一段中文\n\n第二段中文')
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(build.call_count, len(chunks))
        self.assertEqual([len(gateway.sent) for gateway in gateways], [1] * len(chunks))
        self.assertEqual(task.result['content'], expected)
        self.assertEqual(task.progress, expected)
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)
        self.assertFalse(SharedArticleTranslation.objects.exists())
        result_id = task.result['result_id']
        with patch.object(service, '_dispatch') as dispatch:
            detail = self.client.get(f'/api/me/ai/translations/{task.pk}/')
            latest = self.client.get(self.url)
        dispatch.assert_not_called()
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(detail.data['result']['result_id'], result_id)
        self.assertEqual(latest.data['task']['result']['result_id'], result_id)
        self.assertEqual(build.call_count, len(chunks))

    def test_t06_queued_source_mutation_fails_closed_before_dispatch(self):
        task = self.queued()
        self.news.full_content += '\n\nchanged while queued'
        self.news.save(update_fields=['full_content'])
        with patch.object(service, 'build_gateway_client') as build:
            service.run_translation(task.pk, task.generation)
        build.assert_not_called()
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertEqual(task.progress, '')
        self.assertFalse(task.result)
        self.assertFalse(ChatGPTArticleTranslation.objects.exists())
        self.assertFalse(SharedArticleTranslation.objects.exists())

    def test_t06_later_chunk_rechecks_source_model_and_credential_fences(self):
        for mutation in ('source', 'credential', 'model'):
            with self.subTest(mutation=mutation):
                source_markdown = 'A' * 5000 + '\n\n' + 'B' * 5000 + f'\n\ncase {mutation}'
                self.news.full_content = source_markdown
                self.news.full_content_state = 'legacy'
                self.news.save(update_fields=['full_content', 'full_content_state'])
                self.request_id = str(uuid.uuid4())
                task = self.queued()
                first = FakeGateway([gateway_frame('第一段中文')])
                original_epoch = self.connection.credential_epoch
                original_revision = self.model.config_revision
                real_mark_dispatch = service._mark_dispatch

                def mutate_before_dispatch(task_id, generation, token, chunk_index):
                    if chunk_index == 1:
                        if mutation == 'source':
                            self.news.full_content += '\nchanged after first chunk'
                            self.news.save(update_fields=['full_content'])
                        elif mutation == 'credential':
                            self.connection.credential_epoch += 1
                            self.connection.save(update_fields=['credential_epoch'])
                        else:
                            self.model.config_revision += 1
                            self.model.save(update_fields=['config_revision'])
                    return real_mark_dispatch(task_id, generation, token, chunk_index)

                try:
                    with patch.object(service, '_mark_dispatch', side_effect=mutate_before_dispatch):
                        with patch.object(service, 'build_gateway_client', return_value=first) as build:
                            service.run_translation(task.pk, task.generation)
                    task.refresh_from_db()
                    self.assertEqual(task.status, 'failed')
                    self.assertEqual(task.progress, '第一段中文\n\n')
                    self.assertFalse(task.result)
                    self.assertEqual(build.call_count, 1)
                    self.assertEqual(len(first.sent), 1)
                    self.assertFalse(ChatGPTArticleTranslation.objects.exists())
                    self.assertFalse(SharedArticleTranslation.objects.exists())
                finally:
                    if mutation == 'source':
                        self.news.full_content = source_markdown
                        self.news.save(update_fields=['full_content'])
                    elif mutation == 'credential':
                        self.connection.refresh_from_db()
                        self.connection.credential_epoch = original_epoch
                        self.connection.save(update_fields=['credential_epoch'])
                    elif mutation == 'model':
                        self.model.refresh_from_db()
                        self.model.config_revision = original_revision
                        self.model.save(update_fields=['config_revision'])

    def test_t06_middle_chunk_failures_are_progress_only_and_never_replayed(self):
        cases = (
            ('eof', gateway_frame('partial second', finish=None)),
            ('length', gateway_frame('partial second', finish='length')),
            ('empty', gateway_frame('', finish='stop')),
        )
        for index, (failure, frame) in enumerate(cases):
            with self.subTest(failure=failure):
                self.news.full_content = 'A' * 5000 + '\n\n' + 'B' * 5000 + f'\n\ncase {failure}'
                self.news.full_content_state = 'legacy'
                self.news.save(update_fields=['full_content', 'full_content_state'])
                self.request_id = str(uuid.uuid4())
                task = self.queued()
                first = FakeGateway([gateway_frame('translated first')])
                second = FakeGateway([frame])
                with patch.object(service, 'build_gateway_client', side_effect=[first, second]) as build:
                    service.run_translation(task.pk, task.generation)
                    service.run_translation(task.pk, task.generation)
                task.refresh_from_db()
                self.assertEqual(task.status, 'failed')
                self.assertEqual(task.progress, 'translated first\n\n')
                self.assertFalse(task.result)
                self.assertEqual(build.call_count, 2)
                self.assertEqual(len(first.sent), 1)
                self.assertEqual(len(second.sent), 1)
                self.assertFalse(ChatGPTArticleTranslation.objects.exists())
                self.assertFalse(SharedArticleTranslation.objects.exists())

    def test_t06_oversized_indivisible_block_and_profile_mismatch_reject_before_dispatch(self):
        self.news.full_content = 'A' * 9000 + '\n\n' + 'B' * 100
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['full_content', 'full_content_state'])
        with patch.object(service, '_dispatch') as dispatch:
            oversized = self.start()
        self.assertEqual(oversized.status_code, 400, oversized.content)
        dispatch.assert_not_called()
        self.assertFalse(ChatGPTTranslationTask.objects.exists())

        self.news.full_content = 'A' * 5000 + '\n\n' + 'B' * 5000
        self.news.save(update_fields=['full_content'])
        with patch.object(service, 'T06_ENDPOINT_PROFILE_VERSION', 2), patch.object(service, '_dispatch') as dispatch:
            mismatch = self.start(request_id=str(uuid.uuid4()))
        self.assertEqual(mismatch.status_code, 409, mismatch.content)
        dispatch.assert_not_called()
        self.assertFalse(ChatGPTTranslationTask.objects.exists())

    def test_t06_rejects_quoted_or_indented_fences_before_dispatch(self):
        unsupported = (
            '> ~~~py\n> print(1)\n> ~~~',
            '>  ~~~py\n>  print(1)\n>  ~~~',
            '>   ~~~py\n>   print(1)\n>   ~~~',
            '> > ~~~md\n> > nested\n> > ~~~',
            '- ~~~py\n  print(1)\n  ~~~',
            '1. ```py\n   print(1)\n   ```',
            '> - ~~~py\n>   print(1)\n>   ~~~',
            '    ~~~py\n    print(1)\n    ~~~',
            '    - ~~~py\n      print(1)\n      ~~~',
        )
        for index, fence in enumerate(unsupported):
            with self.subTest(index=index):
                self.news.full_content = 'A' * 5000 + '\n\n' + fence + '\n\n' + 'B' * 5000
                self.news.full_content_state = 'legacy'
                self.news.save(update_fields=['full_content', 'full_content_state'])
                with patch.object(service, '_dispatch') as dispatch:
                    response = self.start(request_id=str(uuid.uuid4()))
                self.assertEqual(response.status_code, 400, response.content)
                dispatch.assert_not_called()
                self.assertFalse(ChatGPTTranslationTask.objects.exists())
                self.assertFalse(ChatGPTArticleTranslation.objects.exists())
                self.assertFalse(SharedArticleTranslation.objects.exists())

    def test_t06_final_fence_allows_provider_closing_line_ending(self):
        self.news.full_content = 'A' * 5000 + '\n\n' + 'B' * 4000 + '\n\n' + '```py\nprint(1)\n```'
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['full_content', 'full_content_state'])
        task = self.queued()
        chunks = service._task_chunks(task.execution_snapshot)
        self.assertGreater(len(chunks), 1)
        prepared = [service._split_trailing_separator(chunk) for chunk in chunks]
        self.assertEqual(prepared[-1][1], '')
        gateways = []
        for index, (body, _) in enumerate(prepared):
            output = body + ('\n' if index == len(prepared) - 1 else '')
            gateways.append(FakeGateway([gateway_frame(output)]))
        with patch.object(service, 'build_gateway_client', side_effect=gateways):
            service.run_translation(task.pk, task.generation)
        task.refresh_from_db()
        self.assertEqual(task.status, 'succeeded')
        self.assertTrue(task.result['content'].endswith('```\n'))
        self.assertIn('print(1)', task.result['content'])

    def test_t06_unknown_context_and_guard_drift_reject_before_dispatch(self):
        self.news.full_content = 'A' * 5000 + '\n\n' + 'B' * 5000
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['full_content', 'full_content_state'])
        cases = (
            {'T06_CONTEXT_WINDOW_TOKENS': None},
            {'T06_CONTEXT_WINDOW_TOKENS': 999_999},
            {'T06_REQUEST_SIZE_GUARD_BYTES': 100},
            {'T06_OUTPUT_TOKENS_PER_CHUNK': service.T06_PROVIDER_MAX_OUTPUT_TOKENS + 1},
        )
        for changes in cases:
            with self.subTest(changes=changes), patch.multiple(service, **changes), patch.object(service, '_dispatch') as dispatch:
                response = self.start(request_id=str(uuid.uuid4()))
            self.assertEqual(response.status_code, 409, response.content)
            dispatch.assert_not_called()
            self.assertFalse(ChatGPTTranslationTask.objects.exists())


    def test_t08_owner_detail_chat_and_tts_read_same_private_result_without_dispatch(self):
        task = self.complete_synthetic_private('合成私有译文：只属于当前用户。')
        result_id = task.result['result_id']
        from api.services import article_content, tts_service
        stored = service.article_snapshot(self.news, self.owner)
        with patch.object(service, '_dispatch') as dispatch, patch.object(service, 'build_gateway_client') as build:
            detail = self.client.get(f'/api/news/{self.news.pk}/')
            self.assertEqual(detail.status_code, 200, detail.content)
            matching = [item for item in detail.data['full_content_zh_private_history']
                        if item['result_id'] == result_id]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]['content'], task.result['content'])
            self.assertEqual(detail.data['full_content_zh_result_id'], result_id)
            text, metadata = article_content.pick_chat_context(
                self.news, self.owner, translation_result_id=result_id,
                stored=stored, with_metadata=True,
            )
            self.assertEqual(text, task.result['content'])
            self.assertEqual(metadata['result_id'], result_id)
            resolved = tts_service.resolve_tts_content(
                self.news, self.owner, 'zh', 'full', translation_result_id=result_id,
            )
            self.assertEqual(resolved.content, task.result['content'])
            self.assertIn(f':result:{result_id}:task:{task.pk}', resolved.namespace)

            chat_call = {}
            def fake_complete(**kwargs):
                chat_call.update(kwargs)
                yield {'type': 'delta', 'content': 'synthetic chat response'}
                yield {'type': 'complete', 'model_source': 'synthetic'}
            with patch('api.services.ai_article_chat.complete_article_chat', side_effect=fake_complete):
                chat_response = self.client.post(f'/api/news/{self.news.pk}/chat/', {
                    'question': '请解释个人译文', 'translation_result_id': result_id,
                    'model_config_id': str(self.model.pk), 'billing_consent': True,
                    'turn_id': str(uuid.uuid4()),
                }, format='json')
                self.assertEqual(chat_response.status_code, 200)
                chat_wire = b''.join(chat_response.streaming_content)
            self.assertIn(b'synthetic chat response', chat_wire)
            import json
            evidence = json.loads(chat_call['messages'][1]['content'].split('\n', 1)[1])
            self.assertEqual(evidence['text'], task.result['content'])
            self.assertEqual(evidence['translation']['result_id'], result_id)
        dispatch.assert_not_called()
        build.assert_not_called()

        other = APIClient()
        other.force_login(self.other)
        other_detail = other.get(f'/api/news/{self.news.pk}/')
        self.assertEqual(other_detail.status_code, 200, other_detail.content)
        self.assertEqual(other_detail.data['full_content_zh_private_history'], [])
        response = other.get(
            f'/api/news/{self.news.pk}/tts/?language=zh&scope=full&translation_result_id={result_id}',
        )
        self.assertEqual(response.status_code, 404, response.content)
        with self.assertRaises(tts_service.TTSContentUnavailable):
            tts_service.resolve_tts_content(
                self.news, self.other, 'zh', 'full', translation_result_id=result_id,
            )

    def test_t08_current_subscription_result_remains_a_private_fallback_without_byok_dispatch(self):
        from api.services import tts_service
        stored = service.article_snapshot(self.news, self.owner)
        subscription = ChatGPTSubscriptionConnection.objects.create(
            user=self.owner, subject_hash='t08-subject', issuer='synthetic',
            issued_client_id='t08-client', registration_key_hash='t08-registration',
            generation=1, selected_model='subscription-model', is_active=True,
        )
        subscription_result = ChatGPTArticleTranslation.objects.create(
            user=self.owner, connection=subscription, api_connection=None, news=self.news,
            source_hash=stored.canonical_hash, model_slug='subscription-model',
            content='当前订阅译文。', completed_at=timezone.now(),
        )
        with patch.object(service, '_dispatch') as dispatch, patch.object(service, 'build_gateway_client') as build:
            detail = self.client.get(f'/api/news/{self.news.pk}/')
            self.assertEqual(detail.status_code, 200, detail.content)
            self.assertEqual(detail.data['full_content_zh'], subscription_result.content)
            self.assertEqual(detail.data['full_content_zh_scope'], 'private')
            self.assertEqual(detail.data['full_content_zh_source'], 'chatgpt')
            tts_result = tts_service.resolve_tts_content(self.news, self.owner, 'zh', 'full')
            self.assertEqual(tts_result.content, subscription_result.content)
        dispatch.assert_not_called()
        build.assert_not_called()

    def test_t08_two_users_same_article_keep_private_text_and_audio_cache_isolated(self):
        owner_task = self.complete_synthetic_private('A 用户专属译文。')
        owner_result_id = owner_task.result['result_id']

        from api.ai_connection_models import UserAIConnection
        from api.ai_model_models import AIModelProbeAttempt, UserAIModelConfig
        from api.services.ai_model_registry import get_trusted_preset
        other = APIClient()
        other.force_login(self.other)
        connection_response = other.post('/api/me/ai/connections/', {
            'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
            'display_name': 'Other synthetic connection', 'api_key': fixtures.KEY + '-other',
            'request_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(connection_response.status_code, 201, connection_response.content)
        other_connection = UserAIConnection.objects.get(pk=connection_response.data['id'])
        model_response = other.post(
            f'/api/me/ai/connections/{other_connection.pk}/models/',
            {'model_id': 'deepseek-flash'}, format='json',
        )
        self.assertEqual(model_response.status_code, 201, model_response.content)
        other_model = UserAIModelConfig.objects.get(pk=model_response.data['id'])
        preset = get_trusted_preset(other_connection, other_model.model_id)
        self.assertIsNotNone(preset)
        attempt_id = uuid.uuid4()
        AIModelProbeAttempt.objects.create(
            id=attempt_id, request_id=uuid.uuid4(), user=self.other,
            connection=other_connection, model_config=other_model,
            model_id=other_model.model_id, model_revision=other_model.config_revision,
            probe_kind='text', status='succeeded',
            credential_epoch=other_connection.credential_epoch,
            credential_version=other_connection.credential_version,
            endpoint_profile=other_connection.endpoint_profile,
            endpoint_profile_version=other_connection.endpoint_profile_version,
            proxy_alias=preset['proxy_alias'],
        )
        other_model.last_text_attempt = attempt_id
        other_model.capability_results = {'text': {
            'attempt_id': str(attempt_id), 'status': 'supported',
            'config_revision': other_model.config_revision,
            'credential_epoch': other_connection.credential_epoch,
            'credential_version': other_connection.credential_version,
            'endpoint_profile': other_connection.endpoint_profile,
            'endpoint_profile_version': other_connection.endpoint_profile_version,
        }}
        other_model.save(update_fields=['last_text_attempt', 'capability_results'])

        other_request_id = str(uuid.uuid4())
        with patch.object(service, '_dispatch') as dispatch:
            admitted = other.post(f'/api/news/{self.news.pk}/byok-translation/', {
                'model_config_id': str(other_model.pk), 'billing_consent': True,
                'target_language': 'zh',
            }, format='json', HTTP_IDEMPOTENCY_KEY=other_request_id)
        self.assertEqual(admitted.status_code, 202, admitted.content)
        dispatch.assert_called_once()
        other_task = ChatGPTTranslationTask.objects.get(pk=admitted.data['task_id'])
        self.execute(other_task, [gateway_frame('B 用户专属译文。')])
        other_result_id = other_task.result['result_id']

        owner_detail = self.client.get(f'/api/news/{self.news.pk}/')
        other_detail = other.get(f'/api/news/{self.news.pk}/')
        self.assertEqual(owner_detail.data['full_content_zh_private_history'][0]['result_id'], owner_result_id)
        self.assertEqual(owner_detail.data['full_content_zh_private_history'][0]['content'], 'A 用户专属译文。')
        self.assertEqual(other_detail.data['full_content_zh_private_history'][0]['result_id'], other_result_id)
        self.assertEqual(other_detail.data['full_content_zh_private_history'][0]['content'], 'B 用户专属译文。')

        from api.services import tts_service
        owner_tts = tts_service.resolve_tts_content(
            self.news, self.owner, 'zh', 'full', translation_result_id=owner_result_id,
        )
        other_tts = tts_service.resolve_tts_content(
            self.news, self.other, 'zh', 'full', translation_result_id=other_result_id,
        )
        self.assertNotEqual(owner_tts.namespace, other_tts.namespace)
        same_speech_text = 'identical synthetic audio transcript'
        owner_variant = tts_service.build_cache_variant(owner_tts, 'full', 'yunyang', same_speech_text)
        other_variant = tts_service.build_cache_variant(other_tts, 'full', 'yunyang', same_speech_text)
        self.assertNotEqual(owner_variant, other_variant)
        with self.assertRaises(tts_service.TTSContentUnavailable):
            tts_service.resolve_tts_content(
                self.news, self.owner, 'zh', 'full', translation_result_id=other_result_id,
            )

    def test_t08_stale_saved_result_remains_explicit_and_current_fallback_is_not_overridden(self):
        old = self.complete_synthetic_private('旧版本的个人译文。')
        old_id = old.result['result_id']
        old_title = self.news.title
        self.news.title = 'Updated synthetic title'
        self.news.full_content = '# Updated synthetic article\n\nA newer source body.'
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['title', 'full_content', 'full_content_state'])
        from api.services import article_content, tts_service
        from api.services.shared_translations import cache_key
        from api.models import SharedArticleTranslation
        current = service.article_snapshot(self.news, self.owner)
        SharedArticleTranslation.objects.create(
            **cache_key(self.news.pk, current.canonical_hash),
            content='当前版本共享译文。', provider='synthetic', model_slug='synthetic-model',
            completed_at=timezone.now(),
        )
        detail_with_shared = self.client.get(f'/api/news/{self.news.pk}/')
        self.assertEqual(detail_with_shared.status_code, 200, detail_with_shared.content)
        self.assertEqual(detail_with_shared.data['full_content_zh'], '当前版本共享译文。')
        self.assertEqual(detail_with_shared.data['full_content_zh_scope'], 'shared')
        self.assertIn(old_id, [item['result_id'] for item in detail_with_shared.data['full_content_zh_private_history']])
        default_tts = tts_service.resolve_tts_content(self.news, self.owner, 'zh', 'full')
        self.assertEqual(default_tts.content, '当前版本共享译文。')

        new = self.complete_synthetic_private('当前版本的个人译文。', request_id=str(uuid.uuid4()))
        detail = self.client.get(f'/api/news/{self.news.pk}/')
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.data['full_content_zh'], '当前版本的个人译文。')
        history = {item['result_id']: item for item in detail.data['full_content_zh_private_history']}
        self.assertIn(old_id, history)
        self.assertFalse(history[old_id]['current_match'])
        self.assertEqual(history[old_id]['source_title'], old_title)
        self.assertTrue(history[new.result['result_id']]['current_match'])
        text, metadata = article_content.pick_chat_context(
            self.news, self.owner, translation_result_id=old_id, stored=current, with_metadata=True,
        )
        self.assertEqual(text, old.result['content'])
        self.assertFalse(metadata['current_match'])
        self.assertEqual(metadata['source_title'], old_title)

        chat_call = {}
        def fake_complete(**kwargs):
            chat_call.update(kwargs)
            yield {'type': 'delta', 'content': 'synthetic stale chat response'}
            yield {'type': 'complete', 'model_source': 'synthetic'}
        with patch('api.services.ai_article_chat.complete_article_chat', side_effect=fake_complete):
            chat_response = self.client.post(f'/api/news/{self.news.pk}/chat/', {
                'question': '请说明历史版本', 'translation_result_id': old_id,
                'model_config_id': str(self.model.pk), 'billing_consent': True,
                'turn_id': str(uuid.uuid4()),
            }, format='json')
            self.assertEqual(chat_response.status_code, 200)
            b''.join(chat_response.streaming_content)
        import json
        evidence = json.loads(chat_call['messages'][1]['content'].split('\n', 1)[1])
        self.assertEqual(evidence['text'], old.result['content'])
        self.assertEqual(evidence['title'], old_title)
        self.assertEqual(evidence['article_url'], '')
        self.assertFalse(evidence['translation']['current_match'])
        self.assertEqual(
            chat_call['article_context']['translation_context']['result_id'], old_id,
        )
        self.assertEqual(
            chat_call['article_context']['translation_context']['source_title'], old_title,
        )

        # Persisted factual turns are visible/replayed only with their exact
        # selected result; changing to current or original cannot relabel them.
        from api.services.stored_readers import snapshot_metadata
        from api.services.chat_history import append_assistant_message
        _, current_context = article_content.pick_chat_context(
            self.news, self.owner, stored=current, with_metadata=True,
        )
        old_article_context = snapshot_metadata(current, metadata)
        current_article_context = snapshot_metadata(current, current_context)
        session = ChatSession.objects.get(user=self.owner, news=self.news)
        append_assistant_message(
            user_id=self.owner.pk, news_id=self.news.pk, session_id=session.pk,
            generation=session.generation, content='历史结果对应的助手回答。',
            status='complete', article_context=old_article_context,
        )
        append_assistant_message(
            user_id=self.owner.pk, news_id=self.news.pk, session_id=session.pk,
            generation=session.generation, content='当前结果对应的助手回答。',
            status='complete', article_context=current_article_context,
        )
        history_url = f'/api/news/{self.news.pk}/chat/'
        old_history = self.client.get(
            history_url, {'translation_mode': 'result', 'translation_result_id': old_id},
        )
        current_history = self.client.get(
            history_url, {'translation_mode': 'result', 'translation_result_id': new.result['result_id']},
        )
        original_history = self.client.get(history_url, {'translation_mode': 'original'})
        self.assertIn('历史结果对应的助手回答。', [m['content'] for m in old_history.data['messages']])
        self.assertNotIn('当前结果对应的助手回答。', [m['content'] for m in old_history.data['messages']])
        self.assertIn('当前结果对应的助手回答。', [m['content'] for m in current_history.data['messages']])
        self.assertNotIn('历史结果对应的助手回答。', [m['content'] for m in current_history.data['messages']])
        self.assertNotIn('历史结果对应的助手回答。', [m['content'] for m in original_history.data['messages']])
        self.assertNotIn('当前结果对应的助手回答。', [m['content'] for m in original_history.data['messages']])
        # Real pre-T08 records have no article_context. Keep them only for an
        # explicit original-mode read; never attach them to translated evidence.
        from api.services.chat_history import append_user_message
        append_user_message(
            user_id=self.owner.pk, news_id=self.news.pk, content='兼容保留的旧版原文问题。',
        )
        append_assistant_message(
            user_id=self.owner.pk, news_id=self.news.pk, session_id=session.pk,
            generation=session.generation, content='兼容保留的旧版原文回答。',
            status='complete',
        )
        old_history = self.client.get(
            history_url, {'translation_mode': 'result', 'translation_result_id': old_id},
        )
        current_history = self.client.get(
            history_url, {'translation_mode': 'result', 'translation_result_id': new.result['result_id']},
        )
        original_history = self.client.get(history_url, {'translation_mode': 'original'})
        self.assertNotIn('兼容保留的旧版原文问题。', [m['content'] for m in old_history.data['messages']])
        self.assertNotIn('兼容保留的旧版原文问题。', [m['content'] for m in current_history.data['messages']])
        self.assertIn('兼容保留的旧版原文问题。', [m['content'] for m in original_history.data['messages']])
        self.assertNotIn('兼容保留的旧版原文回答。', [m['content'] for m in old_history.data['messages']])
        self.assertNotIn('兼容保留的旧版原文回答。', [m['content'] for m in current_history.data['messages']])
        self.assertIn('兼容保留的旧版原文回答。', [m['content'] for m in original_history.data['messages']])

        invalid_mode = self.client.get(history_url, {'translation_mode': 'unknown'})
        self.assertEqual(invalid_mode.status_code, 400, invalid_mode.content)
        mode_conflict = self.client.get(
            history_url, {'translation_mode': 'original', 'translation_result_id': old_id},
        )
        self.assertEqual(mode_conflict.status_code, 400, mode_conflict.content)

        old_tts = tts_service.resolve_tts_content(
            self.news, self.owner, 'zh', 'full', translation_result_id=old_id,
        )
        new_tts = tts_service.resolve_tts_content(
            self.news, self.owner, 'zh', 'full', translation_result_id=new.result['result_id'],
        )
        self.assertEqual(old_tts.content, old.result['content'])
        self.assertEqual(old_tts.title, old_title)
        self.assertNotEqual(old_tts.namespace, new_tts.namespace)
        self.assertEqual(tts_service.resolve_tts_content(
            self.news, self.owner, 'zh', 'full',
        ).content, new.result['content'])

    def test_t08_title_only_change_keeps_saved_result_stale_and_prevents_current_fallback(self):
        task = self.complete_synthetic_private('同一正文的历史个人译文。')
        original_hash = task.source_hash
        self.news.title = 'Updated title only'
        self.news.save(update_fields=['title'])
        current = service.article_snapshot(self.news, self.owner)
        self.assertEqual(current.canonical_hash, original_hash)

        detail = self.client.get(f'/api/news/{self.news.pk}/')
        self.assertEqual(detail.status_code, 200, detail.content)
        history = {item['result_id']: item for item in detail.data['full_content_zh_private_history']}
        self.assertFalse(history[task.result['result_id']]['current_match'])
        self.assertEqual(history[task.result['result_id']]['source_title'], task.execution_snapshot['article']['title'])
        self.assertNotEqual(detail.data['full_content_zh'], task.result['content'])
        from api.services.article_content import pick_chat_context
        translated_text, metadata = pick_chat_context(self.news, self.owner, stored=current, with_metadata=True)
        self.assertEqual(translated_text, current.markdown)
        self.assertEqual(metadata['source'], 'original')

    def test_t08_revision_only_change_does_not_mark_body_hash_only_result_current(self):
        task = self.complete_synthetic_private('同一正文修订号变化时的历史译文。')
        original_hash = task.source_hash
        self.news.full_content_revision += 1
        self.news.save(update_fields=['full_content_revision'])
        current = service.article_snapshot(self.news, self.owner)
        self.assertEqual(current.canonical_hash, original_hash)

        detail = self.client.get(f'/api/news/{self.news.pk}/')
        self.assertEqual(detail.status_code, 200, detail.content)
        history = {item['result_id']: item for item in detail.data['full_content_zh_private_history']}
        self.assertFalse(history[task.result['result_id']]['current_match'])
        self.assertEqual(history[task.result['result_id']]['source_revision'],
                         task.execution_snapshot['article']['revision'])
        self.assertNotEqual(detail.data['full_content_zh'], task.result['content'])

    def test_t08_soft_deleted_key_keeps_own_history_readable_and_invalid_chat_selection_fails_closed(self):
        task = self.complete_synthetic_private('软删除后仍可读取的历史译文。')
        result_id = task.result['result_id']
        from api.services import article_content, tts_service
        from api.services.stored_readers import PrivateTranslationNotFound

        # An unknown explicit selection is a hard error, never a current/shared fallback.
        invalid_chat = self.client.post(f'/api/news/{self.news.pk}/chat/', {
            'question': '请解释这段译文', 'translation_result_id': result_id + 999,
            'model_config_id': str(self.model.pk), 'billing_consent': True,
            'turn_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(invalid_chat.status_code, 404, invalid_chat.content)
        invalid_history = self.client.get(
            f'/api/news/{self.news.pk}/chat/',
            {'translation_mode': 'result', 'translation_result_id': result_id + 999},
        )
        self.assertEqual(invalid_history.status_code, 404, invalid_history.content)
        invalid_mode = self.client.post(f'/api/news/{self.news.pk}/chat/', {
            'question': '请解释这段译文', 'translation_mode': 'unknown',
            'model_config_id': str(self.model.pk), 'billing_consent': True,
            'turn_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(invalid_mode.status_code, 400, invalid_mode.content)
        mode_conflict = self.client.post(f'/api/news/{self.news.pk}/chat/', {
            'question': '请解释这段译文', 'translation_mode': 'original',
            'translation_result_id': result_id, 'model_config_id': str(self.model.pk),
            'billing_consent': True, 'turn_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(mode_conflict.status_code, 400, mode_conflict.content)
        # JSON booleans, empty collections, and zero are not valid result IDs.
        # They must fail before any selected model/provider path is entered.
        with patch.object(service, '_dispatch') as dispatch, \
                patch('api.services.ai_article_chat.complete_article_chat') as complete:
            for invalid_result_id in (0, False, [], {}):
                response = self.client.post(f'/api/news/{self.news.pk}/chat/', {
                    'question': '请解释这段译文', 'translation_mode': 'result',
                    'translation_result_id': invalid_result_id,
                    'model_config_id': str(self.model.pk), 'billing_consent': True,
                    'turn_id': str(uuid.uuid4()),
                }, format='json')
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.data.get('error_code'), 'invalid_translation_selection')
        dispatch.assert_not_called()
        complete.assert_not_called()

        from api.services.article_content import pick_chat_context
        original_context, original_metadata = pick_chat_context(
            self.news, self.owner, translation_mode='original', with_metadata=True,
        )
        self.assertEqual(original_context, service.article_snapshot(self.news, self.owner).markdown)
        self.assertEqual(original_metadata['source'], 'original')

        self.connection.is_deleted = True
        self.connection.is_enabled = False
        self.connection.deleted_at = timezone.now()
        self.connection.credential_ciphertext = ''
        self.connection.credential_epoch += 1
        self.connection.revision += 1
        self.connection.save(update_fields=[
            'is_deleted', 'is_enabled', 'deleted_at', 'credential_ciphertext',
            'credential_epoch', 'revision',
        ])
        with patch.object(service, '_dispatch') as dispatch, patch.object(service, 'build_gateway_client') as build:
            detail = self.client.get(f'/api/news/{self.news.pk}/')
            self.assertEqual(detail.status_code, 200, detail.content)
            self.assertIn(result_id, [item['result_id'] for item in detail.data['full_content_zh_private_history']])
            self.assertEqual(article_content.pick_chat_context(
                self.news, self.owner, translation_result_id=result_id,
            ), task.result['content'])
            self.assertEqual(tts_service.resolve_tts_content(
                self.news, self.owner, 'zh', 'full', translation_result_id=result_id,
            ).content, task.result['content'])
            with self.assertRaises(PrivateTranslationNotFound):
                article_content.pick_chat_context(
                    self.news, self.owner, translation_result_id=result_id + 999,
                )
        dispatch.assert_not_called()
        build.assert_not_called()

