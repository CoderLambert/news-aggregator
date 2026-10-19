"""T04 explicit owner-selected personal news Q&A: no real provider requests."""
import sqlite3
from threading import Barrier, Thread
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import OperationalError, close_old_connections
from django.db.models import F
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.ai_model_models import AIModelProbeAttempt, UserAIModelConfig
from api.ai_preference_models import UserAITaskPreference
from api.models import ArticleChatTurn, Category, ChatSession, News, Source
from api.services.ai_gateway import (
    AIGatewayError, ARTICLE_CHAT_SUPPORTED_ALIAS, _GatewayCompletions,
)
from api.services.ai_model_registry import get_trusted_preset, supports_article_chat
from api.tests.rss.reader_fixtures import public_legacy_article


CONNECTIONS = '/api/me/ai/connections/'
KEY = 'sk-t04-synthetic-provider-not-real-999999'


def gateway_frame(text, *, finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=text), finish_reason=finish,
    )])


class FakeGateway:
    def __init__(self, response, on_send=None):
        self.response = response
        self.sent = []
        self.closed = False
        def send(**kwargs):
            self.sent.append(kwargs)
            if on_send:
                on_send()
            return self.response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=send))

    def close(self):
        self.closed = True


@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True, AI_BYOK_ENABLED=True,
                   PROVIDER_CREDENTIAL_ENCRYPTION_KEY='t04-synthetic-local-credential-material')
class PersonalArticleChatTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('t04-owner', password='only-synthetic-test')
        self.other = User.objects.create_user('t04-other', password='only-synthetic-test')
        self.client = APIClient()
        self.client.force_login(self.owner)
        source = Source.objects.create(name='T04 synthetic publisher', url='https://publisher.example/')
        category = Category.objects.create(name='T04 category', slug='t04-category')
        self.news = public_legacy_article(News.objects.create(
            title='Synthetic story', url='https://publisher.example/story',
            source=source, category=category, content='Readable summary',
            publish_time=timezone.now(),
        ))
        self.url = f'/api/news/{self.news.pk}/chat/'
        response = self.client.post(CONNECTIONS, {
            'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
            'display_name': 'My DeepSeek', 'api_key': KEY,
            'request_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.connection = UserAIConnection.objects.get(pk=response.data['id'])
        response = self.client.post(
            f'{CONNECTIONS}{self.connection.pk}/models/',
            {'model_id': 'deepseek-flash'}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.model = UserAIModelConfig.objects.get(pk=response.data['id'])
        self._verify_text(self.model)

    def _verify_text(self, model):
        model.refresh_from_db()
        conn = model.connection
        preset = get_trusted_preset(conn, model.model_id)
        self.assertIsNotNone(preset)
        attempt_id = uuid.uuid4()
        AIModelProbeAttempt.objects.create(
            id=attempt_id, request_id=uuid.uuid4(),
            user=self.owner, connection=conn, model_config=model,
            model_id=model.model_id, model_revision=model.config_revision,
            probe_kind='text', status='succeeded',
            credential_epoch=conn.credential_epoch,
            credential_version=conn.credential_version,
            endpoint_profile=conn.endpoint_profile,
            endpoint_profile_version=conn.endpoint_profile_version,
            proxy_alias=preset['proxy_alias'],
        )
        model.last_text_attempt = attempt_id
        model.capability_results = {
            'text': {
                'attempt_id': str(attempt_id), 'status': 'supported',
                'config_revision': model.config_revision,
                'credential_epoch': conn.credential_epoch,
                'credential_version': conn.credential_version,
                'endpoint_profile': conn.endpoint_profile,
                'endpoint_profile_version': conn.endpoint_profile_version,
            },
        }
        model.save(update_fields=['last_text_attempt', 'capability_results'])

    def _chat(self, *, model=None, question='What happened?', **extra):
        body = {'question': question, **extra}
        if model is not None:
            body['model_config_id'] = str(model.pk)
            body.setdefault('billing_consent', True)
            body.setdefault('turn_id', str(uuid.uuid4()))
        return self.client.post(self.url, body, format='json')

    def _cancel(self, turn_id, client=None):
        return (client or self.client).post(
            f'/api/news/{self.news.pk}/chat/{turn_id}/cancel/', {}, format='json',
        )

    def _wire(self, response):
        return b''.join(response.streaming_content).decode('utf-8')

    def test_gateway_stream_adapter_allows_only_the_exact_t04_alias(self):
        class CompletionSpy:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return object()

        completions = CompletionSpy()
        adapter = _GatewayCompletions(completions, KEY)
        adapter.create(
            model=ARTICLE_CHAT_SUPPORTED_ALIAS, stream=True, messages=[],
        )
        self.assertEqual(len(completions.calls), 1)
        self.assertEqual(completions.calls[0]['model'], 'deepseek/deepseek-flash')
        self.assertEqual(completions.calls[0]['extra_body'], {'api_key': KEY})

        with self.assertRaises(AIGatewayError):
            adapter.create(model='deepseek/deepseek-chat', stream=True, messages=[])
        self.assertEqual(len(completions.calls), 1)

        # The old trusted preset remains available to T02 non-stream probes.
        adapter.create(model='deepseek/deepseek-chat', stream=False, messages=[])
        self.assertEqual(len(completions.calls), 2)
        self.assertFalse(completions.calls[1]['stream'])

    def test_legacy_chat_alias_stays_stored_but_is_never_t04_eligible(self):
        response = self.client.post(
            f'{CONNECTIONS}{self.connection.pk}/models/',
            {'model_id': 'deepseek-chat'}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        legacy = UserAIModelConfig.objects.get(pk=response.data['id'])
        self._verify_text(legacy)
        legacy.refresh_from_db()
        self.assertEqual(legacy.capability_results['text']['status'], 'supported')
        self.assertEqual(
            AIModelProbeAttempt.objects.get(pk=legacy.last_text_attempt).proxy_alias,
            'deepseek/deepseek-chat',
        )
        self.assertFalse(supports_article_chat(legacy.connection, legacy.model_id))
        gateway = FakeGateway([gateway_frame('must not reach provider')])
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway) as build:
            response = self._chat(model=legacy)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error_code'], 'model_unavailable')
        build.assert_not_called()

    def test_explicit_model_completion_persists_private_source_once_and_never_alters_preferences(self):
        gateway = FakeGateway([gateway_frame('Verified synthetic answer.')])
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway) as build, \
             patch('api.services.chatgpt_subscription.active_connection_for_user',
                   side_effect=AssertionError('subscription path must not execute')):
            response = self._chat(model=self.model)
            self.assertEqual(response.status_code, 200)
            wire = self._wire(response)
        self.assertIn('Verified synthetic answer.', wire)
        self.assertIn('"status": "complete"', wire)
        self.assertIn('"type": "chat_model"', wire)
        self.assertTrue(gateway.closed)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(gateway.sent[0]['model'], 'deepseek/deepseek-flash')
        self.assertEqual(gateway.sent[0]['reasoning_effort'], 'none')
        self.assertTrue(gateway.sent[0]['stream'])
        self.assertEqual(gateway.sent[0]['max_tokens'], 2048)
        self.assertEqual(UserAITaskPreference.objects.count(), 0)
        messages = self.client.get(self.url).data['messages']
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[-1]['status'], 'complete')
        self.assertEqual(messages[-1]['content'], 'Verified synthetic answer.')
        self.assertEqual(messages[-1]['model_source'], {'provider': 'deepseek', 'model': 'deepseek-flash'})
        other_client = APIClient()
        other_client.force_login(self.other)
        self.assertEqual(other_client.get(self.url).data['messages'], [])

    def test_unknown_cross_owner_model_rejected_before_history_and_network(self):
        other_client = APIClient()
        other_client.force_login(self.other)
        with patch('api.services.ai_article_chat.build_gateway_client') as gateway:
            denied = other_client.post(self.url, {
                'question': 'Can I use someone else’s model?',
                'model_config_id': str(self.model.pk), 'billing_consent': True,
                'turn_id': str(uuid.uuid4()),
            }, format='json')
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.data['error_code'], 'model_not_found')
        self.assertEqual(ChatSession.objects.count(), 0)
        gateway.assert_not_called()

    def test_unverified_stale_or_bad_model_and_web_search_are_not_sent(self):
        with patch('api.services.ai_article_chat.build_gateway_client') as gateway:
            self.assertEqual(self._chat(model=self.model, web_search=True).status_code, 409)
            invalid = self.client.post(self.url, {
                'question': 'Hello', 'model_config_id': 'not-a-uuid', 'billing_consent': True,
                'turn_id': str(uuid.uuid4()),
            }, format='json')
            self.assertEqual(invalid.status_code, 400)
            self.model.capability_results = {}
            self.model.save(update_fields=['capability_results'])
            self.assertEqual(self._chat(model=self.model).status_code, 409)
        gateway.assert_not_called()
        self.assertFalse(ChatSession.objects.exists())

    def test_missing_or_malformed_billing_consent_rejected_before_model_resolution_and_network(self):
        from api.services.ai_article_chat import prepare_article_chat

        for consent in ('missing', None, False, 1, 0, 'true', {}, []):
            with self.subTest(consent=consent):
                payload = {'question': 'No unconfirmed provider charge',
                           'model_config_id': str(self.model.pk)}
                if consent != 'missing':
                    payload['billing_consent'] = consent
                with patch('api.services.ai_article_chat.prepare_article_chat', wraps=prepare_article_chat) as prepare, \
                     patch('api.services.ai_article_chat.build_gateway_client') as gateway:
                    response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.data['error_code'], 'billing_consent_required')
                prepare.assert_not_called()
                gateway.assert_not_called()
                self.assertFalse(ChatSession.objects.exists())

    def test_cancel_before_post_rejects_attempt_without_history_or_gateway(self):
        turn = uuid.uuid4()
        self.assertEqual(self._cancel(turn).data['status'], 'cancelled')
        self.assertEqual(self._cancel(turn).data['status'], 'cancelled')
        with patch('api.services.ai_article_chat.build_gateway_client') as build:
            response = self._chat(model=self.model, turn_id=str(turn))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error_code'], 'chat_turn_cancelled')
        self.assertFalse(ChatSession.objects.exists())
        build.assert_not_called()

    def test_cancel_after_question_before_dispatch_prevents_network(self):
        turn = uuid.uuid4()
        from api.services.chat_history import append_user_message as original_append
        def cancel_after_save(**kwargs):
            snapshot = original_append(**kwargs)
            reply = self._cancel(turn)
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.data['status'], 'cancelled')
            return snapshot
        with patch('api.services.chat_history.append_user_message', side_effect=cancel_after_save), \
             patch('api.services.ai_article_chat.build_gateway_client') as build:
            wire = self._wire(self._chat(model=self.model, turn_id=str(turn)))
        self.assertIn('"status": "failed"', wire)
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).status, 'cancelled')
        self.assertEqual(len(ChatSession.objects.get().messages), 1)
        build.assert_not_called()

    def test_cancel_during_provider_call_fences_terminal_history_commit(self):
        turn = uuid.uuid4()
        def cancel_after_dispatch():
            reply = self._cancel(turn)
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.data['status'], 'cancelled')
        gateway = FakeGateway([gateway_frame('Paid but uncommitted answer')], on_send=cancel_after_dispatch)
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
            wire = self._wire(self._chat(model=self.model, turn_id=str(turn)))
        self.assertIn('"status": "failed"', wire)
        self.assertNotIn('Paid but uncommitted answer', wire)
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).status, 'cancelled')
        self.assertEqual(len(ChatSession.objects.get().messages), 1)
        self.assertTrue(gateway.closed)

    def test_cancel_after_complete_reports_truth_and_duplicate_never_resends(self):
        turn = uuid.uuid4()
        gateway = FakeGateway([gateway_frame('Completed synthetic answer')])
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
            wire = self._wire(self._chat(model=self.model, turn_id=str(turn)))
        self.assertIn('Completed synthetic answer', wire)
        self.assertEqual(self._cancel(turn).data['status'], 'already_completed')
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).status, 'complete')
        self.assertEqual(ChatSession.objects.get().messages[-1]['status'], 'complete')
        with patch('api.services.ai_article_chat.build_gateway_client') as build:
            denied = self._chat(model=self.model, turn_id=str(turn))
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.data['error_code'], 'duplicate_chat_turn')
        build.assert_not_called()

    def test_owner_and_article_scope_of_cancel_receipts(self):
        turn = uuid.uuid4()
        other_client = APIClient()
        other_client.force_login(self.other)
        self.assertEqual(self._cancel(turn).data['status'], 'cancelled')
        denied = self._cancel(turn, other_client)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).user_id, self.owner.pk)

    def test_clear_from_another_tab_cancels_active_turn_and_old_generation_cannot_restore_answer(self):
        from api.services.ai_article_turns import (
            ArticleChatTurnError, mark_complete, mark_dispatched, reserve_turn_with_question,
        )
        from api.services.chat_history import ChatConflict, append_assistant_message

        turn = uuid.uuid4()
        snapshot = reserve_turn_with_question(
            user_id=self.owner.pk, news_id=self.news.pk,
            turn_id=turn, question='Question being cleared',
        )
        mark_dispatched(user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn)

        # A separate authenticated client represents another tab. Clearing is
        # owner/article-wide and fences already registered in-flight turns.
        other_tab = APIClient()
        other_tab.force_login(self.owner)
        response = other_tab.delete(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['status'], 'cleared')
        row = ArticleChatTurn.objects.get(pk=turn)
        self.assertEqual(row.status, 'cancelled')
        session = ChatSession.objects.get(user=self.owner, news=self.news)
        self.assertEqual(session.messages, [])
        self.assertEqual(session.generation, snapshot.generation + 1)

        with self.assertRaises(ArticleChatTurnError) as cancelled:
            mark_complete(user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn)
        self.assertEqual(cancelled.exception.code, 'chat_turn_cancelled')
        with self.assertRaises(ChatConflict):
            append_assistant_message(
                user_id=self.owner.pk, news_id=self.news.pk,
                session_id=snapshot.session_id, generation=snapshot.generation,
                content='Late answer must not resurrect cleared history',
            )
        session.refresh_from_db()
        self.assertEqual(session.messages, [])

    def test_clear_cancels_registered_turn_even_if_no_history_session_exists(self):
        turn = uuid.uuid4()
        ArticleChatTurn.objects.create(
            id=turn, user=self.owner, news=self.news, status='pending',
        )
        self.assertFalse(ChatSession.objects.exists())

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).status, 'cancelled')
        self.assertFalse(ChatSession.objects.exists())

    def test_missing_invalid_or_not_v4_turn_id_cannot_start_billable_turn(self):
        for value in (None, 'invalid', '00000000-0000-0000-0000-000000000001'):
            body = {'question': 'No valid turn id', 'model_config_id': str(self.model.pk),
                    'billing_consent': True}
            if value is not None:
                body['turn_id'] = value
            denied = self.client.post(self.url, body, format='json')
            self.assertEqual(denied.status_code, 400, denied.content)
            self.assertEqual(denied.data['error_code'], 'invalid_chat_turn')
        self.assertFalse(ChatSession.objects.exists())
        self.assertFalse(ArticleChatTurn.objects.exists())

    def test_ambiguous_provider_failure_is_not_retried(self):
        gateway = FakeGateway([])
        provider_attempts = []

        def ambiguous_failure(**kwargs):
            provider_attempts.append(kwargs)
            raise TimeoutError('synthetic ambiguous provider outcome')

        gateway.chat.completions.create = ambiguous_failure
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway) as build:
            wire = self._wire(self._chat(model=self.model))

        self.assertEqual(build.call_count, 1)
        self.assertEqual(len(provider_attempts), 1)
        self.assertTrue(gateway.closed)
        self.assertIn('"status": "failed"', wire)
        self.assertEqual(len(ChatSession.objects.get(user=self.owner, news=self.news).messages), 1)

    def test_incomplete_unknown_and_empty_terminal_may_show_partial_but_never_complete_or_save(self):
        for result, visible, hidden in (
            ([gateway_frame('Partial text', finish=None)], 'Partial text', None),
            ([gateway_frame('Truncated text', finish='length')], None, 'Truncated text'),
            (
                [
                    gateway_frame('Visible partial', finish=None),
                    gateway_frame('Truncated tail', finish='length'),
                ],
                'Visible partial',
                'Truncated tail',
            ),
            ([gateway_frame('  ')], None, None),
        ):
            ChatSession.objects.all().delete()
            gateway = FakeGateway(result)
            with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway) as build:
                response = self._chat(model=self.model)
                wire = self._wire(response)
            self.assertIn('"status": "failed"', wire)
            self.assertNotIn('"status": "complete"', wire)
            self.assertNotIn('"type": "chat_model"', wire)
            if visible:
                self.assertIn(visible, wire)
            if hidden:
                self.assertNotIn(hidden, wire)
            self.assertEqual(build.call_count, 1)
            self.assertEqual(len(gateway.sent), 1)
            messages = ChatSession.objects.get(user=self.owner, news=self.news).messages
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]['role'], 'user')
            self.assertTrue(gateway.closed)

    def test_late_key_revocation_article_change_and_acl_revocation_cannot_save_answer(self):
        def revoke():
            UserAIConnection.objects.filter(pk=self.connection.pk).update(
                is_enabled=False, credential_epoch=F('credential_epoch') + 1,
            )
        gateway = FakeGateway([gateway_frame('Should never be saved')], on_send=revoke)
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
            wire = self._wire(self._chat(model=self.model))
        self.assertIn('"status": "failed"', wire)
        self.assertNotIn('Should never be saved', wire)
        self.assertEqual(len(ChatSession.objects.get().messages), 1)
        self.connection.refresh_from_db()
        self.connection.is_enabled = True
        self.connection.credential_epoch += 1
        self.connection.save(update_fields=['is_enabled', 'credential_epoch'])
        self._verify_text(self.model)
        ChatSession.objects.all().delete()

        def alter_article():
            News.objects.filter(pk=self.news.pk).update(title='Different article title')
        gateway = FakeGateway([gateway_frame('Also cannot be saved')], on_send=alter_article)
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
            wire = self._wire(self._chat(model=self.model))
        self.assertIn('"status": "failed"', wire)
        self.assertNotIn('Also cannot be saved', wire)
        self.assertEqual(len(ChatSession.objects.get().messages), 1)

        from api.rss.models import SourcePublication
        ChatSession.objects.all().delete()

        def revoke_article_body():
            SourcePublication.objects.filter(source=self.news.source).update(
                reading_policy='summary_only', policy_version=F('policy_version') + 1,
            )
        gateway = FakeGateway([gateway_frame('Revoked article body must not be saved')],
                              on_send=revoke_article_body)
        with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
            wire = self._wire(self._chat(model=self.model))
        self.assertIn('"status": "failed"', wire)
        self.assertNotIn('Revoked article body must not be saved', wire)
        self.assertEqual(len(ChatSession.objects.get().messages), 1)
        self.assertEqual(ChatSession.objects.get().messages[0]['role'], 'user')

class ArticleChatTurnDatabaseRaceTests(TransactionTestCase):
    """Use separate Django connections to exercise real turn CAS interleavings."""

    reset_sequences = True

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('t04-race-owner', password='synthetic-only')
        source = Source.objects.create(name='T04 race publisher', url='https://publisher.example/')
        category = Category.objects.create(name='T04 race category', slug='t04-race-category')
        self.news = public_legacy_article(News.objects.create(
            title='Synthetic race story', url='https://publisher.example/race',
            source=source, category=category, content='Synthetic body',
            publish_time=timezone.now(),
        ))

    def _parallel(self, operations):
        barrier = Barrier(len(operations))
        results = [None] * len(operations)

        def worker(index, operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results[index] = operation()
            except BaseException as error:
                results[index] = error
            finally:
                close_old_connections()

        threads = [
            Thread(target=worker, args=(index, operation), daemon=True)
            for index, operation in enumerate(operations)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads), 'database race worker timed out')
        return results

    def test_duplicate_inflight_uuid_on_separate_connections_appends_once(self):
        from api.services.ai_article_turns import ArticleChatTurnError, reserve_turn_with_question

        turn = uuid.uuid4()

        def reserve(question):
            return reserve_turn_with_question(
                user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn, question=question,
            )

        results = self._parallel([
            lambda: reserve('Concurrent one'),
            lambda: reserve('Concurrent two'),
        ])
        successes = [result for result in results if not isinstance(result, BaseException)]
        failures = [result for result in results if isinstance(result, BaseException)]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assertIsInstance(failures[0], ArticleChatTurnError)
        self.assertEqual(failures[0].code, 'duplicate_chat_turn')
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).status, 'pending')
        session = ChatSession.objects.get(user=self.owner, news=self.news)
        self.assertEqual(len(session.messages), 1)

    def test_reservation_retries_wrapped_sqlite_busy_but_not_other_db_errors(self):
        import api.services.ai_article_turns as turns
        from api.services.ai_article_turns import ArticleChatTurnError

        turn = uuid.uuid4()
        original_create = turns._create_turn
        attempts = []

        def fail_once_with_wrapped_busy(**kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                driver = sqlite3.OperationalError('synthetic wrapped lock')
                driver.sqlite_errorcode = sqlite3.SQLITE_LOCKED | (1 << 8)
                wrapped = OperationalError('wrapped Django database error')
                wrapped.__cause__ = driver
                raise wrapped
            return original_create(**kwargs)

        with patch.object(turns, '_create_turn', side_effect=fail_once_with_wrapped_busy), \
             patch.object(turns.time, 'sleep') as sleep:
            turns.reserve_turn(user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn)

        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(0.005)
        self.assertEqual(ArticleChatTurn.objects.get(pk=turn).status, 'pending')

        other_turn = uuid.uuid4()
        non_busy_attempts = []

        def fail_once_with_non_busy(**_kwargs):
            non_busy_attempts.append(1)
            driver = sqlite3.OperationalError('synthetic non-lock failure')
            driver.sqlite_errorcode = sqlite3.SQLITE_IOERR
            wrapped = OperationalError('wrapped Django database error')
            wrapped.__cause__ = driver
            raise wrapped

        with patch.object(turns, '_create_turn', side_effect=fail_once_with_non_busy), \
             patch.object(turns.time, 'sleep') as sleep:
            with self.assertRaises(ArticleChatTurnError) as unavailable:
                turns.reserve_turn(
                    user_id=self.owner.pk, news_id=self.news.pk, turn_id=other_turn,
                )

        self.assertEqual(unavailable.exception.code, 'chat_turn_unavailable')
        self.assertEqual(len(non_busy_attempts), 1)
        sleep.assert_not_called()
        self.assertFalse(ArticleChatTurn.objects.filter(pk=other_turn).exists())

    def test_independent_connection_clear_races_terminal_assistant_commit(self):
        from api.services.ai_article_turns import (
            ArticleChatTurnError, mark_complete, mark_dispatched, reserve_turn_with_question,
        )
        from api.services.chat_history import (
            ChatConflict, append_assistant_message, clear_chat_history,
        )

        turn = uuid.uuid4()
        snapshot = reserve_turn_with_question(
            user_id=self.owner.pk, news_id=self.news.pk,
            turn_id=turn, question='Question being cleared',
        )
        mark_dispatched(user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn)

        def clear():
            return ('clear', clear_chat_history(
                user_id=self.owner.pk, news_id=self.news.pk,
            ))

        def commit_terminal():
            from django.db import transaction
            try:
                with transaction.atomic():
                    mark_complete(user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn)
                    append_assistant_message(
                        user_id=self.owner.pk, news_id=self.news.pk,
                        session_id=snapshot.session_id, generation=snapshot.generation,
                        content='Answer racing clear', status='complete',
                    )
                return ('commit', 'complete')
            except ArticleChatTurnError as error:
                return ('commit', error.code)
            except ChatConflict:
                return ('commit', 'chat_conflict')

        clear_result, commit_result = self._parallel([clear, commit_terminal])
        self.assertFalse(isinstance(clear_result, BaseException), clear_result)
        self.assertFalse(isinstance(commit_result, BaseException), commit_result)
        self.assertEqual(clear_result, ('clear', True))

        row = ArticleChatTurn.objects.get(pk=turn)
        session = ChatSession.objects.get(user=self.owner, news=self.news)
        self.assertEqual(session.generation, snapshot.generation + 1)
        self.assertEqual(session.messages, [])
        if row.status == 'cancelled':
            self.assertEqual(commit_result, ('commit', 'chat_turn_cancelled'))
        else:
            self.assertEqual(row.status, 'complete')
            self.assertEqual(commit_result, ('commit', 'complete'))

        with self.assertRaises(ChatConflict):
            append_assistant_message(
                user_id=self.owner.pk, news_id=self.news.pk,
                session_id=snapshot.session_id, generation=snapshot.generation,
                content='Stale post-clear completion must not reappear', status='complete',
            )
        session.refresh_from_db()
        self.assertEqual(session.messages, [])

    def test_independent_connection_cancel_race_never_lies_about_commit(self):
        from api.services.ai_article_turns import (
            ArticleChatTurnError, cancel_turn, mark_complete,
        )

        turn = uuid.uuid4()
        ArticleChatTurn.objects.create(
            id=turn, user=self.owner, news=self.news, status='dispatched',
        )

        def cancel():
            return ('cancel', cancel_turn(
                user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn,
            ))

        def complete():
            from django.db import transaction
            try:
                with transaction.atomic():
                    mark_complete(user_id=self.owner.pk, news_id=self.news.pk, turn_id=turn)
                return ('complete', 'complete')
            except ArticleChatTurnError as error:
                return ('complete', error.code)

        results = self._parallel([cancel, complete])
        self.assertFalse(any(isinstance(result, BaseException) for result in results), results)
        cancel_result, complete_result = results
        row = ArticleChatTurn.objects.get(pk=turn)
        if cancel_result == ('cancel', 'cancelled'):
            self.assertEqual(row.status, 'cancelled')
            self.assertEqual(complete_result, ('complete', 'chat_turn_cancelled'))
        else:
            self.assertEqual(cancel_result, ('cancel', 'already_completed'))
            self.assertEqual(row.status, 'complete')
            self.assertEqual(complete_result, ('complete', 'complete'))
