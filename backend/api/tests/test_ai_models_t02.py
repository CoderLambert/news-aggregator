"""T02 owner/CSRF, no-implicit-billing, attempt-fence and terminal regressions."""
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.ai_model_models import AIModelProbeAttempt, UserAIModelConfig
from api.ai_connection_models import UserAIConnection
from api.services.ai_execution import personal_clients_for_user, PersonalAIUnavailable
from api.services.ai_model_probe import ProbeOutcome, parse_completion


BASE = '/api/me/ai/connections/'
KEY = 'synthetic-t02-key-never-real-0123456789'
MODEL = 'deepseek-chat'


@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full',
                   PROVIDER_CREDENTIAL_ENCRYPTION_KEY='synthetic-t02-keymaterial-not-real',
                   PUBLIC_AI_ENABLED=False)
class AIModelT02Tests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('t02-model-owner', password='SyntheticPassword123')
        self.other = User.objects.create_user('t02-model-other', password='SyntheticPassword123')
        self.api = APIClient()
        self.test_atomic_depth = len(connection.atomic_blocks)  # TestCase itself owns test transactions.
        self.api.force_authenticate(self.owner)
        response = self.api.post(BASE, {
            'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
            'display_name': 'test connection', 'api_key': KEY,
            'request_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.connection = response.data
        self.model_base = BASE + self.connection['id'] + '/models/'

    def create_model(self, model_id=MODEL):
        response = self.api.post(self.model_base, {'model_id': model_id}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.data

    def probe(self, row, kind='text', request_id=None, revision=None):
        return self.api.post(
            self.model_base + row['id'] + '/probe/',
            {'probe_kind': kind, 'revision': revision or row['config_revision'],
             'request_id': request_id or str(uuid.uuid4())}, format='json')

    def test_catalog_and_models_are_owner_scoped_and_get_cannot_bill_or_write(self):
        row = self.create_model('deepseek/deepseek-chat')
        self.assertEqual(row['model_id'], MODEL)
        self.assertEqual(row['capabilities'], {'text': 'unknown', 'tools': 'unknown'})
        self.assertTrue(row['article_chat_supported'])
        before = AIModelProbeAttempt.objects.count()
        with patch('api.ai_model_views.send_model_probe', side_effect=AssertionError('paid GET')):
            catalog = self.api.get(BASE + self.connection['id'] + '/model-catalog/')
            models = self.api.get(self.model_base)
            detail = self.api.get(self.model_base + row['id'] + '/')
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.data['models'][0]['model_id'], MODEL)
        self.assertEqual(len(models.data['models']), 1)
        self.assertEqual(detail.data['id'], row['id'])
        self.assertEqual(AIModelProbeAttempt.objects.count(), before)
        self.assertEqual(models['Cache-Control'], 'private, no-store')
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.get(self.model_base).status_code, 404)
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').status_code, 404)
        self.assertEqual(self.api.post(self.model_base, {'model_id': MODEL}, format='json').status_code, 404)
        self.assertEqual(self.probe(row).status_code, 404)
        self.assertEqual(UserAIModelConfig.objects.count(), 1)

    def test_unknown_user_model_may_be_saved_but_cannot_enter_proxy(self):
        manual = self.create_model('user-manual-model')
        self.assertFalse(manual['has_trusted_route'])
        self.assertFalse(manual['article_chat_supported'])
        with patch('api.ai_model_views.send_model_probe') as sender:
            self.assertEqual(self.probe(manual).status_code, 409)
        sender.assert_not_called()
        self.assertFalse(AIModelProbeAttempt.objects.exists())

    def test_no_arbitrary_endpoint_messages_or_secret_reflection(self):
        for bad in ('https://evil.example', 'deepseek/../escape', ' sk-secret ', 'deepseek//bad'):
            response = self.api.post(self.model_base, {'model_id': bad}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(bad, response.content.decode())
        row = self.create_model()
        for payload in (
            {'probe_kind': 'text', 'revision': 1, 'request_id': str(uuid.uuid4()),
             'messages': [{'role': 'user', 'content': 'private news'}]},
            {'probe_kind': 'text', 'revision': 1, 'request_id': str(uuid.uuid4()),
             'api_base': 'https://evil.example'},
            {'probe_kind': 'tools', 'revision': 1, 'request_id': str(uuid.uuid4()),
             'extra_body': {'api_key': KEY}},
        ):
            with patch('api.ai_model_views.send_model_probe') as sender:
                response = self.api.post(self.model_base + row['id'] + '/probe/', payload, format='json')
            self.assertEqual(response.status_code, 400)
            sender.assert_not_called()
            self.assertNotIn(KEY, response.content.decode())

    def test_separate_capabilities_and_idempotent_request_does_not_charge_twice(self):
        row = self.create_model()
        request_id = str(uuid.uuid4())
        def sender(**kwargs):
            self.assertEqual(len(connection.atomic_blocks), self.test_atomic_depth,
                             'external request is inside a view-owned DB transaction')
            self.assertEqual(kwargs['model_alias'], 'deepseek/deepseek-chat')
            self.assertEqual(kwargs['provider_key'], KEY)
            return ProbeOutcome('succeeded', provider_request_id='synthetic-provider-ref')
        with patch('api.ai_model_views.send_model_probe', side_effect=sender) as send:
            first = self.probe(row, request_id=request_id)
            replay = self.probe(row, request_id=request_id)
            self.assertEqual(first.status_code, 200, first.content)
            self.assertEqual(replay.status_code, 200, replay.content)
            self.assertEqual(replay.data['attempt_id'], first.data['attempt_id'])
            self.assertEqual(send.call_count, 1)
            mismatch = self.probe(row, kind='tools', request_id=request_id)
            self.assertEqual(mismatch.status_code, 409)
        after = self.api.get(self.model_base + row['id'] + '/').data
        self.assertEqual(after['capabilities'], {'text': 'supported', 'tools': 'unknown'})
        self.assertEqual(AIModelProbeAttempt.objects.count(), 1)
        with patch('api.ai_model_views.send_model_probe', return_value=ProbeOutcome('unsupported')):
            tools = self.probe(row, kind='tools')
        self.assertEqual(tools.status_code, 200)
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').data['capabilities'],
                         {'text': 'supported', 'tools': 'unsupported'})
        with self.assertRaises(PersonalAIUnavailable):
            personal_clients_for_user(self.owner)

    def test_rekey_after_dispatch_fences_late_result_without_rebilling(self):
        row = self.create_model()
        old_id = str(uuid.uuid4())
        def sender(**kwargs):
            changed = self.api.put(BASE + self.connection['id'] + '/key/', {
                'revision': self.connection['revision'], 'api_key': 'synthetic-t02-new-key-00000001',
            }, format='json')
            self.assertEqual(changed.status_code, 200, changed.content)
            return ProbeOutcome('succeeded')
        with patch('api.ai_model_views.send_model_probe', side_effect=sender):
            result = self.probe(row, request_id=old_id)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.data['stale'])
        self.assertEqual(result.data['capability'], 'unknown')
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').data['capabilities']['text'], 'unknown')
        self.assertEqual(AIModelProbeAttempt.objects.get(request_id=old_id).status, 'stale')

    def test_competing_same_kind_attempt_has_latest_attempt_wins(self):
        row = self.create_model()
        invoked = []
        def sender(**kwargs):
            invoked.append(True)
            if len(invoked) == 1:
                # Concurrent request after first probe was admitted and saved.
                nested = self.probe(row)
                self.assertEqual(nested.status_code, 200, nested.content)
                self.assertEqual(nested.data['status'], 'succeeded')
                return ProbeOutcome('unsupported')
            return ProbeOutcome('succeeded')
        with patch('api.ai_model_views.send_model_probe', side_effect=sender):
            old = self.probe(row)
        self.assertTrue(old.data['stale'])
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').data['capabilities']['text'], 'supported')
        self.assertEqual(AIModelProbeAttempt.objects.filter(status='stale').count(), 1)

    def test_model_revision_delete_and_connection_disable_invalidate_receipts(self):
        row = self.create_model()
        with patch('api.ai_model_views.send_model_probe', return_value=ProbeOutcome('succeeded')):
            self.assertEqual(self.probe(row).status_code, 200)
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').data['capabilities']['text'], 'supported')
        changed = self.api.patch(self.model_base + row['id'] + '/', {
            'revision': row['config_revision'], 'display_name': 'New label'}, format='json')
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.data['capabilities']['text'], 'unknown')
        self.assertEqual(self.probe(row, revision=1).status_code, 409)
        with patch('api.ai_model_views.send_model_probe', return_value=ProbeOutcome('succeeded')):
            self.assertEqual(self.probe(changed.data).status_code, 200)
        disabled = self.api.patch(BASE + self.connection['id'] + '/', {
            'revision': self.connection['revision'], 'is_enabled': False}, format='json')
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').data['capabilities']['text'], 'unknown')
        self.assertEqual(self.probe(changed.data).status_code, 409)
        deleted = self.api.delete(self.model_base + row['id'] + '/',
            {'revision': changed.data['config_revision']}, format='json')
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').status_code, 404)

    def test_unknown_provider_result_and_retry_reconciles_attempt(self):
        row = self.create_model()
        request_id = str(uuid.uuid4())
        with patch('api.ai_model_views.send_model_probe', return_value=ProbeOutcome('unknown', 'gateway_rejected')) as send:
            first = self.probe(row, request_id=request_id)
            second = self.probe(row, request_id=request_id)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(first.data['status'], 'unknown')
        self.assertEqual(second.data['attempt_id'], first.data['attempt_id'])
        self.assertEqual(self.api.get(self.model_base + row['id'] + '/').data['capabilities']['text'], 'unknown')
        listing = self.api.get(self.model_base + row['id'] + '/attempts/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data['attempts'][0]['safe_error_code'], 'gateway_rejected')
        self.assertNotIn(KEY, json.dumps(listing.data))

    def test_csrf_session_and_feature_gates(self):
        row = self.create_model()
        session = APIClient(enforce_csrf_checks=True)
        session.force_login(self.owner)
        self.assertEqual(session.post(self.model_base, {'model_id':'x'}, format='json').status_code, 403)
        session.get('/api/auth/csrf/')
        csrf = session.cookies['csrftoken'].value
        payload = {'probe_kind': 'text', 'revision': row['config_revision'],
                   'request_id': str(uuid.uuid4())}
        probe_url = self.model_base + row['id'] + '/probe/'
        self.assertEqual(session.post(probe_url,payload,format='json',
                         HTTP_X_CSRFTOKEN=csrf, HTTP_ORIGIN='https://evil.example').status_code,403)
        self.assertEqual(session.post(probe_url,payload,format='json',
                         HTTP_X_CSRFTOKEN=csrf, HTTP_X_WORKSPACE_VIEWER=str(self.other.pk)).status_code,409)
        with override_settings(AI_BYOK_ENABLED=False):
            self.assertEqual(self.api.get(self.model_base).status_code,403)
            self.assertEqual(self.probe(row).status_code,403)
        with override_settings(PUBLIC_SITE_MODE='read_only'):
            self.assertEqual(self.probe(row).status_code,403)
        self.assertEqual(AIModelProbeAttempt.objects.count(), 0)

    def test_schema_matches_migration(self):
        call_command('makemigrations', 'api', check=True, dry_run=True, verbosity=0)


class ProbeTerminalTests(TestCase):
    def test_strict_text_terminal_only(self):
        base = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'yes'}}]}
        self.assertEqual(parse_completion(200, {}, json.dumps(base).encode(), 'text').status, 'succeeded')
        for reason in ('length', 'tool_calls', None, 'content_filter'):
            payload = {'choices': [{'finish_reason': reason, 'message': {'content': 'yes'}}]}
            self.assertEqual(parse_completion(200, {}, json.dumps(payload).encode(), 'text').status, 'unknown')
        self.assertEqual(parse_completion(200, {}, json.dumps({'choices': [base['choices'][0],base['choices'][0]]}).encode(), 'text').status, 'unknown')
        self.assertEqual(parse_completion(200, {}, json.dumps(base).encode()+b' '*65536, 'text').status, 'unknown')
        self.assertEqual(parse_completion(429, {}, json.dumps(base).encode(), 'text').status, 'unknown')

    def test_tool_requires_single_valid_call_complete_terminal(self):
        def choice(arguments='{"ok":true}', reason='tool_calls', name='byok_probe', calls=1):
            return {'choices': [{'finish_reason': reason, 'message': {'tool_calls': [{
                'type': 'function','id':'call_test_1','function': {'name':name,'arguments':arguments},
            } for _ in range(calls)]}}]}
        good = json.dumps(choice()).encode()
        self.assertEqual(parse_completion(200, {}, good, 'tools').status,'succeeded')
        for bad in (
            choice('{"ok":true,"ok":true}'), choice('{"ok":1}'),choice('{"ok":false}'),
            choice('{"ok":NaN}'),choice('[]'),choice('{bad'),choice(reason='stop'),
            choice(name='other'),choice(calls=2),
        ):
            self.assertEqual(parse_completion(200,{},json.dumps(bad).encode(),'tools').status,'unknown')
        unsupported = {'choices':[{'finish_reason':'stop','message': {'content':'I cannot call tools'}}]}
        self.assertEqual(parse_completion(200,{},json.dumps(unsupported).encode(),'tools').status,'unsupported')
        self.assertEqual(parse_completion(200,{},b'{"choices":[]}', 'tools').status,'unknown')
