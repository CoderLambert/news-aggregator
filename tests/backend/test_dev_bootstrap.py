"""Standalone real-Django dev bootstrap tests. All data/keys are synthetic."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bootstrap_runtime', ROOT / 'backend/newsaggregator/dev_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class BootstrapTests(unittest.TestCase):
    @classmethod
    def make_runtime(cls, directory):
        directory.mkdir(mode=0o700, parents=True)
        for name in ('home', 'tmp', 'cache', 'media', 'chroma', 'tts'):
            (directory / name).mkdir(mode=0o700)
        marker = directory / 'instance.json'
        marker.write_text(json.dumps({'kind': runtime.KIND, 'root': str(ROOT), 'directory': str(directory),
                                      'id': str(uuid.uuid4()), 'secret': 'synthetic-bootstrap-secret-' * 4}))
        marker.chmod(0o600)

    @classmethod
    def setUpClass(cls):
        cls.schema_temp = tempfile.TemporaryDirectory(prefix='newshub-bootstrap-schema-')
        cls.addClassCleanup(cls.schema_temp.cleanup)
        template = Path(cls.schema_temp.name) / 'template'
        cls.make_runtime(template)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'backend/manage.py'), 'migrate', '--noinput'],
                                env=runtime.environment(template, 29527, 25173), cwd=ROOT,
                                capture_output=True, text=True, timeout=120, umask=0o077)
        if result.returncode:
            raise RuntimeError('Synthetic schema creation failed: ' + result.stderr[-1500:])
        cls.template = template / 'db.sqlite3'
        # Reuse the repository's committed-SQLite backup helper, not DB/WAL file copying.
        support_spec = importlib.util.spec_from_file_location('bootstrap_fixture_support', ROOT / 'conftest.py')
        cls.support = importlib.util.module_from_spec(support_spec)
        support_spec.loader.exec_module(cls.support)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newshub-bootstrap-test-')
        self.base = Path(self.temp.name)
        self.env = {'PATH': f'{Path(sys.executable).parent}:/usr/bin:/bin', 'HOME': str(self.base),
                    'NEWSHUB_DEV_PYTHON': sys.executable, 'NEWSHUB_DEV_STATE_DIR': str(self.base / 'state'),
                    'NEWSHUB_DEV_INSTANCE': 'bootstrap', 'PYTHONDONTWRITEBYTECODE': '1'}
        state = self.base / 'state'
        state.mkdir(mode=0o700)
        slot = state / (hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:16] + '-bootstrap')
        slot.mkdir(mode=0o700)
        directory = slot / 'backend'
        self.make_runtime(directory)
        self.support.backup_synthetic_db(self.template, directory / 'db.sqlite3')
        (directory / 'db.sqlite3').chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, action='init', **changes):
        return subprocess.run(['bash', str(ROOT / 'scripts/news-server'), 'dev', action],
                              cwd=ROOT, env=self.env | changes, capture_output=True, text=True, timeout=180)

    def directory(self):
        return next((self.base / 'state').glob('*/backend'))

    def code(self, code):
        result = subprocess.run([sys.executable, '-B', '-c', 'import django; django.setup();\n' + code],
                                cwd=ROOT, env=runtime.environment(self.directory(), 29527, 25173),
                                capture_output=True, text=True, timeout=30, umask=0o077)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_cli_creates_both_accounts_and_private_unverified_candidates(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.code('''
from django.contrib.auth.models import User
from api.ai_connection_models import UserAIConnection
from api.ai_model_models import UserAIModelConfig, AIModelProbeAttempt
from api.ai_preference_models import UserAITaskPreference
from api.services.ai_model_capabilities import verified_for_task
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
try: validate_password('12345678')
except ValidationError: pass
else: raise AssertionError('global weak-password validation was disabled')
assert set(User.objects.values_list('username', flat=True)) == {'admin', 'user'}
for name in ('admin', 'user'):
    user = User.objects.get(username=name)
    assert user.check_password('12345678')
    assert authenticate(username=name, password='12345678').pk == user.pk
    assert user.is_staff == user.is_superuser == (name == 'admin')
    connection = UserAIConnection.objects.get(user=user)
    assert connection.provider_id == 'deepseek' and connection.endpoint_profile == 'deepseek_default'
    assert not connection.is_enabled and not connection.credential_ciphertext
    model = UserAIModelConfig.objects.get(connection=connection)
    assert model.model_id == 'deepseek-flash' and model.capability_results == {}
    assert not verified_for_task(model, 'default')
assert not AIModelProbeAttempt.objects.exists()
assert not UserAITaskPreference.objects.exists()
''')


    def test_repeat_preserves_password_permissions_config_and_preferences(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults
from django.contrib.auth.models import User
from api.ai_connection_models import UserAIConnection
from api.ai_model_models import UserAIModelConfig
from api.ai_preference_models import UserAITaskPreference, TASK_KINDS
seed_defaults()
admin = User.objects.get(username='admin')
admin.set_password('different-synthetic-password')
admin.is_staff = admin.is_superuser = False
admin.save()
conn = UserAIConnection.objects.get(user=admin)
conn.display_name = 'Changed by developer'; conn.revision += 1; conn.save()
model = UserAIModelConfig.objects.get(connection=conn)
model.model_id = 'changed-model'; model.config_revision += 1; model.save()
for kind in TASK_KINDS:
    UserAITaskPreference.objects.create(user=admin, task_kind=kind,
        selection_source='unset' if kind == 'default' else 'inherit', revision=7)
def snapshot():
    return [list(cls.objects.order_by('pk').values()) for cls in
        (User, UserAIConnection, UserAIModelConfig, UserAITaskPreference)]
before = snapshot()
seed_defaults(); seed_defaults()
assert snapshot() == before
assert not User.objects.get(username='admin').is_superuser
''')

    def test_initial_keys_are_owner_bound_and_api_payloads_are_redacted(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults
from api.services.ai_credentials import decrypt_credential, CredentialUnavailable, require_active_connection
from api.services.ai_model_capabilities import verified_for_task
from api.ai_connection_models import UserAIConnection
from api.ai_connection_views import UserAIConnectionDetailView
from api.ai_model_models import UserAIModelConfig
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate
key = 'synthetic-owner-bound-key-only'
seed_defaults(key)
rows = list(UserAIConnection.objects.select_related('user').order_by('user__username'))
assert rows[0].credential_ciphertext != rows[1].credential_ciphertext
for conn in rows:
    assert decrypt_credential(conn) == key
    assert (conn.credential_epoch, conn.credential_version, conn.revision) == (1, 1, 1)
    assert not conn.is_enabled
    assert not verified_for_task(UserAIModelConfig.objects.get(connection=conn), 'default')
    try: require_active_connection(user_id=conn.user_id, connection_id=conn.pk, expected_epoch=1)
    except CredentialUnavailable: pass
    else: raise AssertionError('offline candidate authorized execution')
with override_settings(AI_BYOK_ENABLED=True):
    for index, conn in enumerate(rows):
        for target, expected in [(conn, 200), (rows[1-index], 404)]:
            request = APIRequestFactory().get('/api/me/ai/connections/')
            force_authenticate(request, user=conn.user)
            response = UserAIConnectionDetailView.as_view()(request, connection_id=target.pk)
            assert response.status_code == expected
            assert key not in str(response.data) and conn.credential_ciphertext not in str(response.data)
rows[0].user_id = rows[1].user_id
try: decrypt_credential(rows[0])
except CredentialUnavailable: pass
else: raise AssertionError('ciphertext accepted wrong owner')
''')

    def test_first_late_import_fences_epoch_and_never_overwrites_existing_key(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults
from api.ai_connection_models import UserAIConnection
from api.services.ai_credentials import decrypt_credential
seed_defaults()
seed_defaults('synthetic-first-key', existing_only=True)
rows = list(UserAIConnection.objects.order_by('pk').values())
for conn in UserAIConnection.objects.all():
    assert (conn.credential_epoch, conn.credential_version, conn.revision) == (2, 2, 2)
    assert decrypt_credential(conn) == 'synthetic-first-key' and not conn.is_enabled
seed_defaults('synthetic-second-key', existing_only=True)
seed_defaults()
assert list(UserAIConnection.objects.order_by('pk').values()) == rows
''')

    def test_revoked_empty_key_is_not_restored_and_other_owner_is_not_partially_updated(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from api.ai_connection_models import UserAIConnection
seed_defaults()
conn = UserAIConnection.objects.get(user__username='user')
conn.credential_epoch += 1; conn.credential_version += 1; conn.revision += 1; conn.save()
before = list(UserAIConnection.objects.order_by('pk').values())
seed_defaults()
try: seed_defaults('synthetic-new-key', existing_only=True)
except BootstrapError: pass
else: raise AssertionError('revocation was reset')
assert list(UserAIConnection.objects.order_by('pk').values()) == before
''')

    def test_foreign_username_is_rejected_without_elevation_or_partial_admin_creation(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from django.contrib.auth.models import User
from api.ai_connection_models import UserAIConnection
foreign = User.objects.create_user(username='user', password='foreign-synthetic-password')
before = list(User.objects.values())
try: seed_defaults()
except BootstrapError: pass
else: raise AssertionError('foreign account adopted')
assert list(User.objects.values()) == before
assert not User.objects.filter(username='admin').exists()
assert not UserAIConnection.objects.exists()
''')
        self.assertFalse((self.directory() / 'defaults.json').exists())

    def test_tampered_owner_receipt_fails_closed(self):
        self.code('from newsaggregator.dev_defaults import seed_defaults; seed_defaults()')
        path = self.directory() / 'defaults.json'
        value = json.loads(path.read_text())
        value['accounts']['admin']['connection_id'] = value['accounts']['user']['connection_id']
        path.write_text(json.dumps(value))
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from api.ai_connection_models import UserAIConnection
before = list(UserAIConnection.objects.order_by('pk').values())
try: seed_defaults('synthetic-new-key')
except BootstrapError: pass
else: raise AssertionError('cross-owner receipt accepted')
assert list(UserAIConnection.objects.order_by('pk').values()) == before
''')

    def test_deleted_model_and_replacement_are_not_adopted(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from api.ai_model_models import UserAIModelConfig
seed_defaults()
model = UserAIModelConfig.objects.get(connection__user__username='user')
model.is_deleted = True; model.save()
UserAIModelConfig.objects.create(connection=model.connection, model_id=model.model_id, display_name='replacement')
before = list(UserAIModelConfig.objects.order_by('pk').values())
try: seed_defaults()
except BootstrapError: pass
else: raise AssertionError('deleted model revived or replacement adopted')
assert list(UserAIModelConfig.objects.order_by('pk').values()) == before
''')

    def test_deleted_and_recreated_admin_does_not_regain_privileges(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from django.contrib.auth.models import User
seed_defaults()
User.objects.get(username='admin').delete()
User.objects.create_user(username='admin', password='replacement-synthetic-password')
before = list(User.objects.order_by('pk').values())
try: seed_defaults()
except BootstrapError: pass
else: raise AssertionError('replacement administrator adopted')
assert list(User.objects.order_by('pk').values()) == before
assert not User.objects.get(username='admin').is_superuser
''')

    def test_changed_pending_model_rejects_key_import_without_overwriting_config(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from api.ai_model_models import UserAIModelConfig
from api.ai_connection_models import UserAIConnection
seed_defaults()
model = UserAIModelConfig.objects.get(connection__user__username='user')
model.model_id = 'different-model'; model.config_revision += 1; model.save()
seed_defaults()
try: seed_defaults('synthetic-new-key')
except BootstrapError: pass
else: raise AssertionError('edited candidate silently received credentials')
assert not UserAIConnection.objects.exclude(credential_ciphertext='').exists()
assert UserAIModelConfig.objects.get(pk=model.pk).model_id == 'different-model'
''')

    def test_ordinary_settings_and_wrong_database_are_rejected(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from django.test import override_settings
from django.db import connection
from django.contrib.auth.models import User
from unittest.mock import patch
for overrides in ({'SETTINGS_MODULE': 'newsaggregator.settings'}, {'DJANGO_ENV': 'production'}, {'AI_BYOK_ENABLED': True}):
    with override_settings(**overrides):
        try: seed_defaults()
        except BootstrapError: pass
        else: raise AssertionError('unsafe settings admitted')
with patch.dict(connection.settings_dict, {'NAME': '/must-not-open-real.sqlite3'}):
    try: seed_defaults()
    except BootstrapError: pass
    else: raise AssertionError('foreign database admitted')
assert not User.objects.exists()
''')

    def test_post_commit_receipt_failure_never_guesses_ownership_on_retry(self):
        self.code('''
import json, os
from pathlib import Path
from unittest.mock import patch
from newsaggregator import dev_defaults as seed
from django.contrib.auth.models import User
original = seed.write_receipt
def fail_completion(directory, value):
    if value['state'] == 'complete': raise OSError('synthetic disk failure')
    original(directory, value)
with patch.object(seed, 'write_receipt', side_effect=fail_completion):
    try: seed.seed_defaults()
    except OSError: pass
    else: raise AssertionError('fault not exercised')
before = list(User.objects.order_by('pk').values())
assert len(before) == 2
assert json.loads((Path(os.environ['NEWSHUB_DEV_RUNTIME']) / 'defaults.json').read_text())['state'] == 'pending'
try: seed.seed_defaults()
except seed.BootstrapError: pass
else: raise AssertionError('ambiguous commit adopted')
assert list(User.objects.order_by('pk').values()) == before
''')

    def test_same_name_foreign_connection_is_not_adopted(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError, DISPLAY
from api.ai_connection_models import UserAIConnection
seed_defaults()
original = UserAIConnection.objects.get(user__username='user')
UserAIConnection.objects.create(user=original.user, provider_id='deepseek', endpoint_profile='deepseek_default',
    display_name=DISPLAY, request_hash='synthetic-request-hash')
before = list(UserAIConnection.objects.order_by('pk').values())
try: seed_defaults()
except BootstrapError: pass
else: raise AssertionError('name conflict ignored')
assert list(UserAIConnection.objects.order_by('pk').values()) == before
''')

    def test_real_cli_private_file_import_is_redacted_and_preserves_existing_keys(self):
        key = self.base / 'bootstrap-key'
        sentinel = 'synthetic-cli-key-never-a-provider-credential'
        key.write_text(sentinel + '\n'); key.chmod(0o600)
        result = self.cli(NEWSHUB_DEV_KEY_FILE=str(key))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"key": "imported"', result.stdout)
        self.assertNotIn(sentinel, result.stdout + result.stderr)
        self.assertNotIn(sentinel, (self.directory() / 'django.log').read_text())
        self.assertNotIn(sentinel, (self.directory() / 'defaults.json').read_text())
        key.write_text('synthetic-different-key')
        result = self.cli('import-key', NEWSHUB_DEV_KEY_FILE=str(key))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"key": "preserved"', result.stdout)
        self.code('''
from api.ai_connection_models import UserAIConnection
from api.services.ai_credentials import decrypt_credential
for conn in UserAIConnection.objects.all():
    assert decrypt_credential(conn) == 'synthetic-cli-key-never-a-provider-credential'
    assert conn.credential_epoch == 1 and not conn.is_enabled
''')

    def test_unexpected_encryption_failure_is_redacted_and_rolls_back_both_accounts(self):
        self.code('''
import io, sys
from unittest.mock import patch
from django.core.management import call_command, CommandError
from django.contrib.auth.models import User
from api.ai_connection_models import UserAIConnection
from newsaggregator import dev_defaults
sentinel = 'synthetic-error-secret-never-log'
stream = io.TextIOWrapper(io.BytesIO(sentinel.encode('ascii')))
output = io.StringIO()
with patch.object(sys, 'stdin', stream), patch.object(dev_defaults, 'encrypt_credential', side_effect=RuntimeError(sentinel)):
    try: call_command('dev_bootstrap', key_stdin=True, stdout=output)
    except CommandError as error:
        assert sentinel not in str(error)
    else: raise AssertionError('injected error was ignored')
assert sentinel not in output.getvalue()
assert not User.objects.exists() and not UserAIConnection.objects.exists()
''')

    def test_changed_endpoint_or_epoch_cannot_receive_a_default_key(self):
        self.code('''
from newsaggregator.dev_defaults import seed_defaults, BootstrapError
from api.ai_connection_models import UserAIConnection
seed_defaults()
conn = UserAIConnection.objects.get(user__username='user')
for field, value in [('endpoint_profile_version', 2), ('endpoint_profile', 'unapproved'),
                     ('provider_id', 'openai'), ('credential_epoch', 3), ('auth_mode', 'none'), ('is_enabled', True)]:
    original = getattr(conn, field)
    setattr(conn, field, value); conn.save()
    before = list(UserAIConnection.objects.order_by('pk').values())
    try: seed_defaults('synthetic-input-key', existing_only=True)
    except BootstrapError: pass
    else: raise AssertionError('modified destination/epoch accepted')
    assert list(UserAIConnection.objects.order_by('pk').values()) == before
    setattr(conn, field, original); conn.save()
''')

    def test_concurrent_initializers_do_not_duplicate_or_reset_accounts(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.cli(), range(2)))
        self.assertTrue(all(result.returncode == 0 for result in results), [result.stderr for result in results])
        self.code('''
from django.contrib.auth.models import User
from api.ai_connection_models import UserAIConnection
from api.ai_model_models import UserAIModelConfig
assert User.objects.count() == UserAIConnection.objects.count() == UserAIModelConfig.objects.count() == 2
assert all(user.check_password('12345678') for user in User.objects.all())
''')


if __name__ == '__main__':
    unittest.main()
