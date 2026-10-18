"""T04 explicit owner-selected personal news Q&A: no real provider requests."""
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db.models import F
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.ai_connection_models import UserAIConnection
from api.ai_model_models import AIModelProbeAttempt, UserAIModelConfig
from api.ai_preference_models import UserAITaskPreference
from api.models import ArticleChatTurn, Category, ChatSession, News, Source
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
            {'model_id': 'deepseek-chat'}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.model = UserAIModelConfig.objects.get(pk=response.data['id'])
        self._verify_text(self.model)

    def _verify_text(self, model):
        model.refresh_from_db()
        conn = model.connection
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
            proxy_alias='deepseek/deepseek-chat',
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
        self.assertEqual(gateway.sent[0]['model'], 'deepseek/deepseek-chat')
        self.assertTrue(gateway.sent[0]['stream'])
        self.assertEqual(gateway.sent[0]['max_tokens'], 2048)
        self.assertEqual(UserAITaskPreference.objects.count(), 0)
        messages = self.client.get(self.url).data['messages']
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[-1]['status'], 'complete')
        self.assertEqual(messages[-1]['content'], 'Verified synthetic answer.')
        self.assertEqual(messages[-1]['model_source'], {'provider': 'deepseek', 'model': 'deepseek-chat'})
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
        with patch('api.views.append_user_message', side_effect=cancel_after_save), \
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

    def test_incomplete_unknown_and_empty_terminal_never_publish_or_save(self):
        for result in (
            [gateway_frame('Partial text', finish=None)],
            [gateway_frame('Truncated text', finish='length')],
            [gateway_frame('  ')],
        ):
            ChatSession.objects.all().delete()
            gateway = FakeGateway(result)
            with patch('api.services.ai_article_chat.build_gateway_client', return_value=gateway):
                response = self._chat(model=self.model)
                wire = self._wire(response)
            self.assertIn('"status": "failed"', wire)
            self.assertNotIn('Partial text', wire)
            self.assertNotIn('Truncated text', wire)
            messages = ChatSession.objects.get(user=self.owner, news=self.news).messages
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]['role'], 'user')
            self.assertTrue(gateway.closed)

    def test_late_key_revocation_and_article_change_cannot_save_answer(self):
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
