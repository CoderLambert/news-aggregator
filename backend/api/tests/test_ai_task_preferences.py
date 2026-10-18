"""T03 five-purpose model preferences: owner, version, proof and fail-closed tests."""
import json
import socket
import uuid
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.ai_model_models import AIModelProbeAttempt, UserAIModelConfig
from api.ai_preference_models import UserAITaskPreference, TASK_KINDS
from api.services.ai_execution import PersonalAIUnavailable, personal_clients_for_user
from api.services.ai_task_preferences import (
    ModelSelectionError, require_task_model_snapshot, resolve_task_model,
)


BASE = '/api/me/ai/connections/'
PREFERENCES = '/api/me/ai/task-preferences/'
SYNTHETIC_KEY = 'synthetic-t03-key-never-real-0123456'


@override_settings(AI_BYOK_ENABLED=True, PUBLIC_SITE_MODE='full',
                   PROVIDER_CREDENTIAL_ENCRYPTION_KEY='synthetic-t03-encryption-material-only',
                   PUBLIC_AI_ENABLED=False)
class AITaskPreferenceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user('t03-owner', password='test-pass-only')
        self.other = User.objects.create_user('t03-other', password='test-pass-only')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.connection = self.create_connection(self.owner)
        self.model = self.create_model(self.connection)

    def create_connection(self, user):
        client = APIClient()
        client.force_authenticate(user)
        response = client.post(BASE, {
            'provider_id': 'deepseek', 'endpoint_profile': 'deepseek_default',
            'display_name': 'test model owner', 'api_key': SYNTHETIC_KEY,
            'request_id': str(uuid.uuid4()),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.data

    def create_model(self, connection):
        path = BASE + connection['id'] + '/models/'
        response = self.api.post(path, {'model_id': 'deepseek-chat'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return UserAIModelConfig.objects.select_related('connection').get(pk=response.data['id'])

    def grant(self, model, kinds=('text',)):
        model.refresh_from_db()
        conn = model.connection
        receipts = dict(model.capability_results)
        for kind in kinds:
            identity = uuid.uuid4()
            AIModelProbeAttempt.objects.create(
                id=identity, request_id=uuid.uuid4(), user_id=conn.user_id,
                connection=conn, model_config=model,
                model_id=model.model_id, model_revision=model.config_revision,
                probe_kind=kind, status='succeeded',
                credential_epoch=conn.credential_epoch,
                credential_version=conn.credential_version,
                endpoint_profile=conn.endpoint_profile,
                endpoint_profile_version=conn.endpoint_profile_version,
                proxy_alias='deepseek/deepseek-chat',
            )
            setattr(model, f'last_{kind}_attempt', identity)
            receipts[kind] = {
                'attempt_id': str(identity), 'status': 'supported',
                'config_revision': model.config_revision,
                'credential_epoch': conn.credential_epoch,
                'credential_version': conn.credential_version,
                'endpoint_profile': conn.endpoint_profile,
                'endpoint_profile_version': conn.endpoint_profile_version,
            }
        model.capability_results = receipts
        model.save(update_fields=['capability_results', 'last_text_attempt',
                                  'last_tools_attempt', 'updated_at'])

    def selection(self, default=None, article_qa=None, full_translation=None,
                  deep_research=None, question_suggestions=None, revision=0):
        values = locals()
        return {'revision': revision, 'preferences': [
            {'task_kind': kind, 'model_config_id': str(values[kind]) if values[kind] else None}
            for kind in TASK_KINDS
        ]}

    def save(self, body):
        return self.api.patch(PREFERENCES, body, format='json')

    def test_read_empty_preferences_does_not_write_or_call_model(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
            response = self.api.get(PREFERENCES)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response.data['revision'], 0)
        self.assertEqual([row['task_kind'] for row in response.data['preferences']], list(TASK_KINDS))
        self.assertEqual(response.data['preferences'][0]['selection_state'], 'unset')
        self.assertTrue(all(row['model_config_id'] is None for row in response.data['preferences']))
        self.assertFalse(UserAITaskPreference.objects.exists())

    def test_atomic_save_owner_scope_and_stale_revision(self):
        self.grant(self.model, ('text','tools'))
        payload = self.selection(default=self.model.pk, article_qa=self.model.pk,
                                 deep_research=self.model.pk)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
            response = self.save(payload)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['revision'], 1)
        self.assertEqual(UserAITaskPreference.objects.filter(user=self.owner).count(), 5)
        self.assertTrue(all(p.revision == 1 for p in UserAITaskPreference.objects.filter(user=self.owner)))
        self.assertEqual(response.data['preferences'][3]['selection_state'], 'available')
        self.assertEqual(self.api.get(PREFERENCES).data['revision'], 1)
        self.assertEqual(self.save(payload).status_code, 409)
        self.assertEqual(UserAITaskPreference.objects.count(), 5)

        other = APIClient()
        other.force_authenticate(self.other)
        hidden = other.get(PREFERENCES)
        self.assertEqual(hidden.status_code, 200)
        self.assertEqual(hidden.data['revision'], 0)
        self.assertTrue(all(p['model_config_id'] is None for p in hidden.data['preferences']))
        self.assertNotIn(str(self.model.pk), str(hidden.data))

    def test_unverified_and_unapproved_models_cannot_be_selected(self):
        response = self.save(self.selection(default=self.model.pk))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error_code'], 'model_not_verified')
        self.assertEqual(UserAITaskPreference.objects.count(), 0)
        # Missing attempt audit must never be treated as a genuine T02 result.
        self.grant(self.model)
        AIModelProbeAttempt.objects.filter(model_config=self.model).delete()
        self.assertEqual(self.save(self.selection(default=self.model.pk)).status_code, 409)
        self.assertFalse(UserAITaskPreference.objects.exists())

    def test_deep_research_requires_separate_tool_probe_and_default_fallback_fails_closed(self):
        self.grant(self.model, ('text',))
        response = self.save(self.selection(default=self.model.pk))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(resolve_task_model(self.owner,'article_qa').model_config_id, str(self.model.pk))
        with self.assertRaises(ModelSelectionError) as ctx:
            resolve_task_model(self.owner, 'deep_research')
        self.assertEqual(ctx.exception.code, 'model_not_verified')
        attempt = self.save(self.selection(default=self.model.pk, deep_research=self.model.pk, revision=1))
        self.assertEqual(attempt.status_code, 409)
        self.assertEqual(attempt.data['error_code'], 'model_not_verified')
        self.grant(self.model, ('tools',))
        saved = self.save(self.selection(default=self.model.pk, deep_research=self.model.pk, revision=1))
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(resolve_task_model(self.owner, 'deep_research').tools_attempt_id,
                         str(self.model.last_tools_attempt))

    def test_other_user_model_rejected_atomically_and_not_exposed_on_corruption(self):
        self.grant(self.model, ('text',))
        foreign_connection = self.create_connection(self.other)
        self.api.force_authenticate(self.other)
        foreign_model = self.create_model(foreign_connection)
        self.api.force_authenticate(self.owner)
        self.assertEqual(self.save(self.selection(default=self.model.pk, full_translation=foreign_model.pk)).status_code, 404)
        self.assertEqual(UserAITaskPreference.objects.filter(user=self.owner).count(), 0)
        self.assertEqual(self.save(self.selection(default=self.model.pk)).status_code, 200)
        UserAITaskPreference.objects.filter(user=self.owner, task_kind='default').update(model_config=foreign_model)
        data = self.api.get(PREFERENCES).data
        self.assertEqual(data['preferences'][0]['selection_state'], 'needs_reselection')
        self.assertIsNone(data['preferences'][0]['model_config_id'])
        self.assertNotIn(str(foreign_model.pk), json.dumps(data))
        with self.assertRaises(ModelSelectionError):
            resolve_task_model(self.owner, 'article_qa')

    def test_deleted_model_or_disabled_connection_never_falls_back(self):
        self.grant(self.model, ('text',))
        self.assertEqual(self.save(self.selection(default=self.model.pk)).status_code, 200)
        active = resolve_task_model(self.owner,'full_translation')
        require_task_model_snapshot(active, owner_id=self.owner.pk)
        db_conn = self.model.connection
        db_conn.is_enabled = False
        db_conn.credential_epoch += 1
        db_conn.save(update_fields=['is_enabled','credential_epoch'])
        self.assertEqual(self.api.get(PREFERENCES).data['preferences'][0]['selection_state'], 'needs_reselection')
        with self.assertRaises(ModelSelectionError) as ctx:
            resolve_task_model(self.owner,'full_translation')
        self.assertEqual(ctx.exception.code,'model_connection_unavailable')
        with self.assertRaises(ModelSelectionError):
            require_task_model_snapshot(active, owner_id=self.owner.pk)

        db_conn.is_enabled = True
        db_conn.credential_epoch += 1
        db_conn.save(update_fields=['is_enabled','credential_epoch'])
        self.model.is_deleted = True
        self.model.save(update_fields=['is_deleted'])
        with self.assertRaises(ModelSelectionError):
            resolve_task_model(self.owner, 'article_qa')

    def test_changed_default_only_affects_new_snapshots_but_rekey_revokes_both(self):
        self.grant(self.model, ('text',))
        second = UserAIModelConfig.objects.create(
            connection=self.model.connection, model_id='manual-model-id', display_name='Other',
        )
        # Trusted routing requires the same approved ID; second config uses
        # another independent connection so duplicate model IDs are allowed.
        alternative_conn = self.create_connection(self.owner)
        self.api.force_authenticate(self.owner)
        alternative = self.create_model(alternative_conn)
        self.grant(alternative, ('text',))
        self.assertEqual(self.save(self.selection(default=self.model.pk)).status_code, 200)
        old = resolve_task_model(self.owner, 'article_qa')
        with self.assertRaises(FrozenInstanceError):
            old.model_id = 'tampered'
        changed = self.save(self.selection(default=alternative.pk, revision=1))
        self.assertEqual(changed.status_code, 200, changed.content)
        new = resolve_task_model(self.owner, 'article_qa')
        self.assertNotEqual(old.model_config_id, new.model_config_id)
        self.assertEqual(old.preference_revision, 1)
        self.assertEqual(new.preference_revision, 2)
        require_task_model_snapshot(old, owner_id=self.owner.pk)
        require_task_model_snapshot(new, owner_id=self.owner.pk)
        self.assertNotIn(SYNTHETIC_KEY, repr(old))
        self.assertEqual(UserAITaskPreference.objects.count(), 5)
        with self.assertRaises(ModelSelectionError):
            require_task_model_snapshot(new, owner_id=self.other.pk)
        # An actual key rotation revokes that connection's old immutable proof.
        original = self.model.connection
        response = self.api.put(BASE + str(original.pk) + '/key/',
            {'revision': original.revision, 'api_key': 'synthetic-t03-key-replaced-99999'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        with self.assertRaises(ModelSelectionError):
            require_task_model_snapshot(old, owner_id=self.owner.pk)
        require_task_model_snapshot(new, owner_id=self.owner.pk)
        with self.assertRaises(PersonalAIUnavailable):
            personal_clients_for_user(self.owner)

    def test_query_validation_csrf_viewer_and_feature_gates(self):
        self.grant(self.model, ('text',))
        payload=self.selection(default=self.model.pk)
        self.assertEqual(self.api.patch(PREFERENCES, {**payload,'api_key':SYNTHETIC_KEY}, format='json').status_code,400)
        self.assertEqual(self.api.patch(PREFERENCES, {'revision':0,'preferences':payload['preferences'][:-1]},format='json').status_code,400)
        self.assertEqual(self.api.get(PREFERENCES, {'not_allowed':'x'}).status_code, 400)
        session = APIClient(enforce_csrf_checks=True)
        session.force_login(self.owner)
        self.assertEqual(session.patch(PREFERENCES,payload,format='json').status_code,403)
        session.get('/api/auth/csrf/')
        csrf=session.cookies['csrftoken'].value
        self.assertEqual(session.patch(PREFERENCES,payload,format='json', HTTP_X_CSRFTOKEN=csrf,
                                       HTTP_X_WORKSPACE_VIEWER=str(self.other.pk)).status_code,409)
        self.assertEqual(session.patch(PREFERENCES,payload,format='json', HTTP_X_CSRFTOKEN=csrf,
                                       HTTP_ORIGIN='https://evil.example').status_code,403)
        with override_settings(AI_BYOK_ENABLED=False):
            self.assertEqual(self.api.get(PREFERENCES).status_code,403)
            self.assertEqual(self.save(payload).status_code,403)
        with override_settings(PUBLIC_SITE_MODE='read_only'):
            self.assertEqual(self.save(payload).status_code,403)
        self.assertEqual(UserAITaskPreference.objects.count(),0)

    def test_new_model_revision_invalidates_frozen_selection_without_rebinding(self):
        self.grant(self.model,('text',))
        self.assertEqual(self.save(self.selection(article_qa=self.model.pk)).status_code,200)
        original=resolve_task_model(self.owner,'article_qa')
        self.model.config_revision += 1
        self.model.save(update_fields=['config_revision'])
        with self.assertRaises(ModelSelectionError) as ctx:
            require_task_model_snapshot(original,owner_id=self.owner.pk)
        self.assertEqual(ctx.exception.code,'execution_model_changed')
        with self.assertRaises(ModelSelectionError):
            resolve_task_model(self.owner,'article_qa')

    def test_migrations_remain_in_sync(self):
        call_command('makemigrations','api',check=True,dry_run=True,verbosity=0)
