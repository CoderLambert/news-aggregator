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
from threading import Barrier
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
            with patch.object(service, 'MAX_INPUT_CHARS', 1):
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
        self.assertEqual(len(gateway.sent), 1)
        task.refresh_from_db()
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)

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
        self.assertGreater(len(chunks), 1)
        prepared = [service._split_trailing_separator(chunk) for chunk in chunks]
        self.assertTrue(any(separator for _, separator in prepared))
        # The synthetic model trims trailing paragraph separators; merge must restore them.
        gateways = [FakeGateway([gateway_frame(body)]) for body, _ in prepared]
        with patch.object(service, 'build_gateway_client', side_effect=gateways) as build:
            service.run_translation(task.pk, task.generation)
        task.refresh_from_db()
        self.assertEqual(task.status, 'succeeded')
        self.assertEqual(build.call_count, len(chunks))
        self.assertEqual([len(gateway.sent) for gateway in gateways], [1] * len(chunks))
        self.assertEqual(task.result['content'], self.news.full_content)
        self.assertEqual(task.progress, self.news.full_content)
        self.assertEqual(ChatGPTArticleTranslation.objects.count(), 1)
        self.assertFalse(SharedArticleTranslation.objects.exists())

    def test_t06_interrupted_middle_chunk_is_progress_only_and_never_replayed(self):
        self.news.full_content = 'A' * 5000 + '\n\n' + 'B' * 5000
        self.news.full_content_state = 'legacy'
        self.news.save(update_fields=['full_content', 'full_content_state'])
        task = self.queued()
        first = FakeGateway([gateway_frame('translated first')])
        second = FakeGateway([gateway_frame('partial second', finish=None)])
        with patch.object(service, 'build_gateway_client', side_effect=[first, second]) as build:
            service.run_translation(task.pk, task.generation)
            service.run_translation(task.pk, task.generation)
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertTrue(task.progress)
        self.assertIsNone(task.result)
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
