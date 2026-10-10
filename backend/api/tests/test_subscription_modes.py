"""Fail-closed mode and OAuth attempt snapshot tests; all provider calls are mocked."""

import os
import subprocess
import sys
import textwrap
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ChatGPTAuthAttempt, ChatGPTSubscriptionConnection
from api.services import chatgpt_subscription as subscription

User = get_user_model()
HANDOFF_ORIGIN = 'http://127.0.0.1:5173'
CALLBACK_PATH = '/api/chatgpt-subscription/callback/'
DISCOVERY = {
    'authorization_endpoint': 'https://auth.example/authorize',
    'token_endpoint': 'https://auth.example/token',
    'jwks_uri': 'https://auth.example/keys',
    'issuer': 'https://auth.example',
}


@pytest.fixture
def crypto(monkeypatch):
    monkeypatch.setattr(subscription, '_encryption_key', lambda: b'mode-tests-32-byte-key-material!')


@pytest.fixture
def user(db):
    return User.objects.create_user(username='mode-reader', password='not-used')


@pytest.fixture(autouse=True)
def isolated_deployment_file(tmp_path):
    settings.CHATGPT_DEPLOYMENT_INSTANCE_ID = ''
    settings.CHATGPT_DEPLOYMENT_INSTANCE_FILE = tmp_path / 'chatgpt-deployment-id'


def _connection(user):
    return ChatGPTSubscriptionConnection.objects.create(
        user=user,
        subject_hash='subject-hash',
        issuer='https://auth.example',
        issued_client_id='issued-client',
        registration_key_hash='registration-hash',
        encrypted_subject='encrypted-subject',
        granted_scopes=[subscription.REQUIRED_DIRECT_SCOPE],
        encrypted_access_token='encrypted-access-token',
        encrypted_refresh_token='encrypted-refresh-token',
        encrypted_id_token='encrypted-id-token',
        access_token_expires_at=timezone.now() + timedelta(hours=1),
        selected_model='visible-model',
        is_active=True,
        needs_reauth=False,
    )


def _start(user, session_key='mode-session', target=None):
    with patch.object(subscription, '_discovery', return_value=DISCOVERY):
        return subscription.create_authorization_attempt(
            user, target_connection=target, session_key=session_key, origin=HANDOFF_ORIGIN,
        )


def _handoff(start, session_key='mode-session'):
    return subscription.handoff_authorization(
        start['attempt_id'], start['handoff_token'],
        session_key=session_key, origin=HANDOFF_ORIGIN,
    )


@pytest.mark.parametrize(
    ('mode', 'environment', 'error_code', 'status_code'),
    [
        ('disabled', 'development', 'subscription_disabled', 403),
        ('website', 'development', 'hosted_integration_unapproved', 503),
        ('local_oss', 'production', 'local_oss_production_forbidden', 403),
    ],
)
def test_network_entries_fail_closed_before_secrets_or_network(
    user, crypto, mode, environment, error_code, status_code,
):
    connection = _connection(user)
    with (
        override_settings(
            CHATGPT_AUTH_MODE=mode, DJANGO_ENV=environment,
            CHATGPT_CLIENT_ID='fake-client', CHATGPT_CLIENT_SECRET='fake-secret',
        ),
        patch.object(subscription, 'decrypt_secret', side_effect=AssertionError('must not decrypt')) as decrypt,
        patch.object(subscription.requests, 'get', side_effect=AssertionError('must not GET')) as get,
        patch.object(subscription.requests, 'post', side_effect=AssertionError('must not POST')) as post,
    ):
        network_calls = [
            lambda: subscription.create_authorization_attempt(
                user, session_key='blocked-session', origin=HANDOFF_ORIGIN,
            ),
            lambda: subscription.handoff_authorization(
                'missing-attempt', 'ticket', session_key='blocked-session', origin=HANDOFF_ORIGIN,
            ),
            lambda: subscription.complete_authorization(
                {}, '', session_key='blocked-session', user_id=user.pk,
            ),
            lambda: subscription._discovery(),
            lambda: subscription._exchange_code('code', 'client', 'verifier', {}),
            lambda: subscription._verify_id_token('token', 'client', 'nonce', {}),
            lambda: subscription._refresh_access_token(connection.pk),
            lambda: subscription._refresh_access_token_with_lease(connection, None, 'lease'),
            lambda: subscription.access_token_for(connection),
            lambda: subscription.discover_models(connection),
            lambda: subscription._revoke_refresh_token('refresh-token', 'client'),
            lambda: subscription.stream_full_translation(
                connection.pk, connection.generation, 'visible-model', 'article', lambda _: None,
            ),
            lambda: list(subscription.stream_chat_response(
                connection, [{'role': 'user', 'content': 'hello'}],
            )),
        ]
        for call in network_calls:
            with pytest.raises(subscription.SubscriptionError) as caught:
                call()
            assert caught.value.error_code == error_code
            assert caught.value.status_code == status_code

        assert subscription.active_connection_for_user(user) is None
        assert subscription.disconnect_connection(user, connection.pk) is False

    decrypt.assert_not_called()
    get.assert_not_called()
    post.assert_not_called()
    connection.refresh_from_db()
    assert connection.encrypted_access_token == ''
    assert connection.encrypted_refresh_token == ''
    assert connection.encrypted_id_token == ''


def test_inactive_user_cannot_start_or_finish_authorization(user, crypto):
    user.is_active = False
    user.save(update_fields=['is_active'])
    with patch.object(subscription, '_discovery') as discovery:
        with pytest.raises(subscription.SubscriptionError) as caught:
            subscription.create_authorization_attempt(
                user, session_key='inactive-session', origin=HANDOFF_ORIGIN,
            )
    assert caught.value.error_code == 'inactive_user'
    discovery.assert_not_called()


def test_snapshot_is_canonical_and_dynamic_client_sentinel_is_immutable(user, crypto):
    start = _start(user)
    attempt = ChatGPTAuthAttempt.objects.get(pk=start['attempt_id'])

    assert attempt.auth_mode == 'local_oss'
    assert attempt.protocol_snapshot == subscription._protocol_snapshot(
        DISCOVERY, subscription.DYNAMIC_CLIENT_ID,
    )
    assert attempt.protocol_snapshot['client_id'] == attempt.requested_client_id == subscription.DYNAMIC_CLIENT_ID
    assert attempt.protocol_snapshot['scopes'] == sorted(subscription.REQUESTED_SCOPES.split())
    assert attempt.config_fingerprint == subscription._snapshot_fingerprint(attempt.protocol_snapshot)
    assert set(attempt.protocol_snapshot) == subscription.PROTOCOL_SNAPSHOT_FIELDS


@pytest.mark.parametrize(
    'field,value',
    [
        ('authorization_endpoint', 'http://auth.example/authorize'),
        ('token_endpoint', 'https://user:secret@auth.example/token'),
        ('jwks_uri', 'https://auth.example/keys#fragment'),
        ('issuer', 'https://user@auth.example'),
    ],
)
def test_discovery_snapshot_rejects_insecure_userinfo_or_fragment(user, crypto, field, value):
    invalid = {**DISCOVERY, field: value}
    with patch.object(subscription, '_discovery', return_value=invalid):
        with pytest.raises(subscription.SubscriptionError) as caught:
            subscription.create_authorization_attempt(
                user, session_key='invalid-discovery-session', origin=HANDOFF_ORIGIN,
            )
    assert caught.value.error_code == 'invalid_protocol_config'
    assert not ChatGPTAuthAttempt.objects.filter(user=user).exists()


@pytest.mark.parametrize(
    'redirect_uri',
    [
        'http://evil.example/api/chatgpt-subscription/callback/',
        'https://user@news.lambert.host/api/chatgpt-subscription/callback/',
    ],
)
def test_handoff_rejects_untrusted_redirect_config_before_ticket_use(user, crypto, monkeypatch, redirect_uri):
    start = _start(user)
    with monkeypatch.context() as changed:
        changed.setattr(subscription, 'REDIRECT_URI', redirect_uri)
        with patch.object(subscription, 'decrypt_secret') as decrypt:
            with pytest.raises(subscription.SubscriptionError) as caught:
                _handoff(start)
    assert caught.value.error_code == 'config_changed'
    decrypt.assert_not_called()
    assert ChatGPTAuthAttempt.objects.get(pk=start['attempt_id']).status == 'pending'


def test_handoff_and_callback_reject_protocol_change_before_decrypt_or_exchange(user, crypto, monkeypatch):
    start = _start(user)
    with monkeypatch.context() as changed:
        changed.setattr(subscription, 'API_RESOURCE', 'https://api.openai.com/v1/changed')
        with patch.object(subscription, 'decrypt_secret') as decrypt:
            with pytest.raises(subscription.SubscriptionError) as caught:
                _handoff(start)
        assert caught.value.error_code == 'config_changed'
        decrypt.assert_not_called()
    attempt = ChatGPTAuthAttempt.objects.get(pk=start['attempt_id'])
    assert attempt.status == 'pending'

    browser_cookie, authorization_url = _handoff(start)
    state = parse_qs(urlparse(authorization_url).query)['state'][0]
    with monkeypatch.context() as changed:
        changed.setattr(subscription, 'API_RESOURCE', 'https://api.openai.com/v1/changed')
        with (
            patch.object(subscription, 'decrypt_secret') as decrypt,
            patch.object(subscription, '_exchange_code') as exchange,
        ):
            with pytest.raises(subscription.SubscriptionError) as caught:
                subscription.complete_authorization(
                    {'state': state, 'code': 'authorization-code'}, browser_cookie,
                    session_key='mode-session', user_id=user.pk,
                )
        assert caught.value.error_code == 'config_changed'
        decrypt.assert_not_called()
        exchange.assert_not_called()
    attempt.refresh_from_db()
    assert attempt.status == 'failed'
    assert attempt.status_message == 'config_changed'


def test_callback_identity_must_match_session_and_attempt_owner(user, crypto):
    other_user = User.objects.create_user(username='other-mode-reader', password='not-used')
    start = _start(user, session_key='bound-session')
    browser_cookie, authorization_url = _handoff(start, session_key='bound-session')
    state = parse_qs(urlparse(authorization_url).query)['state'][0]
    exchange = Mock()
    with patch.object(subscription, '_exchange_code', exchange):
        for session_key, user_id in (
            ('rotated-session', user.pk),
            ('bound-session', other_user.pk),
        ):
            with pytest.raises(subscription.SubscriptionError) as caught:
                subscription.complete_authorization(
                    {'state': state, 'code': 'authorization-code'}, browser_cookie,
                    session_key=session_key, user_id=user_id,
                )
            assert caught.value.error_code == 'session_mismatch'
    exchange.assert_not_called()
    assert subscription.authorization_attempt_status(user, start['attempt_id'])['status'] == 'authorizing'


def test_callback_maps_sqlite_consume_contention_to_safe_service_unavailable(user, crypto):
    with patch.object(
        ChatGPTAuthAttempt.objects, 'get', side_effect=OperationalError('database is locked'),
    ):
        with pytest.raises(subscription.SubscriptionError) as caught:
            subscription.complete_authorization(
                {'state': 'valid-shaped-state'}, 'browser-cookie',
                session_key='contention-session', user_id=user.pk,
            )
    assert caught.value.error_code == 'oauth_storage_busy'
    assert caught.value.status_code == 503


@pytest.mark.parametrize(
    ('message', 'raises'),
    [('database table is locked', False), ('disk I/O error', True)],
)
def test_attempt_failure_finalization_only_swallows_sqlite_busy(user, message, raises):
    queryset = Mock()
    queryset.update.side_effect = OperationalError(message)
    with patch.object(ChatGPTAuthAttempt.objects, 'filter', return_value=queryset):
        if raises:
            with pytest.raises(OperationalError, match='disk I/O error'):
                subscription._finish_attempt('attempt-id', 'failed', 'fixed-safe-message')
        else:
            subscription._finish_attempt('attempt-id', 'failed', 'fixed-safe-message')


def test_callback_maps_final_sqlite_busy_without_reexchanging_code(user, crypto):
    start = _start(user, session_key='final-storage-busy-session')
    browser_cookie, authorization_url = _handoff(
        start, session_key='final-storage-busy-session',
    )
    state = parse_qs(urlparse(authorization_url).query)['state'][0]
    attempt = ChatGPTAuthAttempt.objects.get(pk=start['attempt_id'])
    token_response = {
        'access_token': 'mock-access', 'refresh_token': 'mock-refresh',
        'id_token': 'mock-id-token', 'expires_in': 3600,
        'scope': f'openid offline_access resource.invoke {subscription.REQUIRED_DIRECT_SCOPE}',
    }
    original_filter = ChatGPTAuthAttempt.objects.filter

    def filter_with_final_storage_busy(*args, **kwargs):
        queryset = original_filter(*args, **kwargs)
        if (
            kwargs.get('pk') == attempt.pk and kwargs.get('status') == 'processing' and
            'session_binding_hash' in kwargs
        ):
            guarded_queryset = Mock()
            guarded_queryset.first.side_effect = queryset.first
            guarded_queryset.update.side_effect = OperationalError('database is locked')
            return guarded_queryset
        return queryset

    with (
        patch.object(subscription, '_discovery', return_value=DISCOVERY),
        patch.object(subscription, '_exchange_code', return_value=token_response) as exchange,
        patch.object(subscription, '_verify_id_token', return_value={
            'iss': DISCOVERY['issuer'], 'sub': 'storage-busy-subject',
        }),
        patch.object(ChatGPTAuthAttempt.objects, 'filter', side_effect=filter_with_final_storage_busy),
    ):
        with pytest.raises(subscription.SubscriptionError) as caught:
            subscription.complete_authorization(
                {'state': state, 'code': 'authorization-code', 'client_id': 'issued-client'},
                browser_cookie,
                session_key='final-storage-busy-session', user_id=user.pk,
            )

    assert caught.value.error_code == 'oauth_storage_busy'
    assert caught.value.status_code == 503
    exchange.assert_called_once()
    attempt.refresh_from_db()
    assert attempt.status == 'failed'
    assert not ChatGPTSubscriptionConnection.objects.filter(user=user).exists()


@pytest.mark.parametrize(
    ('change', 'expected_status'),
    [
        ('cancel', 'cancelled'),
        ('target_generation', 'failed'),
        ('inactive_user', 'failed'),
    ],
)
def test_callback_rechecks_attempt_fence_immediately_before_exchange(
    user, crypto, change, expected_status,
):
    target = _connection(user) if change == 'target_generation' else None
    session_key = f'fence-{change}-session'
    start = _start(user, session_key=session_key, target=target)
    browser_cookie, authorization_url = _handoff(start, session_key=session_key)
    state = parse_qs(urlparse(authorization_url).query)['state'][0]

    def change_after_consume_before_exchange():
        if change == 'cancel':
            assert subscription.cancel_authorization_attempt(user, start['attempt_id'])
        elif change == 'target_generation':
            target.refresh_from_db()
            target.auth_attempt_generation += 1
            target.save(update_fields=['auth_attempt_generation'])
        else:
            user.is_active = False
            user.save(update_fields=['is_active'])
        return DISCOVERY

    exchange = Mock()
    with (
        patch.object(subscription, '_discovery', side_effect=change_after_consume_before_exchange),
        patch.object(subscription, '_exchange_code', exchange),
    ):
        with pytest.raises(subscription.SubscriptionError):
            subscription.complete_authorization(
                {'state': state, 'code': 'authorization-code', 'client_id': 'issued-client'},
                browser_cookie,
                session_key=session_key,
                user_id=user.pk,
            )

    exchange.assert_not_called()
    assert subscription.authorization_attempt_status(user, start['attempt_id'])['status'] == expected_status


def test_two_database_connections_consume_callback_state_at_most_once(tmp_path):
    repository_root = Path(__file__).resolve().parents[3]
    backend_root = repository_root / 'backend'
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    home.chmod(0o700)
    database_path = (tmp_path / 'fresh-file-sqlite.sqlite3').resolve()
    child_script = tmp_path / 'callback_race.py'
    child_script.write_text(textwrap.dedent('''
        import os
        import threading
        import traceback
        from pathlib import Path
        from urllib.parse import parse_qs, urlparse
        from unittest.mock import patch

        import django
        django.setup()

        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.db import close_old_connections, connection
        from django.db.migrations.recorder import MigrationRecorder
        from api.models import ChatGPTAuthAttempt
        from api.services import chatgpt_subscription as subscription

        expected_environment = {
            'HOME', 'PATH', 'PYTHONPATH', 'DJANGO_SETTINGS_MODULE', 'RUN_MAIN',
            'DJANGO_ENV', 'DJANGO_DB_PATH', 'CHATGPT_DEPLOYMENT_INSTANCE_ID',
        }
        assert expected_environment <= set(os.environ)
        assert set(os.environ) <= expected_environment | {'LC_CTYPE', 'TZ'}
        assert Path(connection.settings_dict['NAME']).resolve() == Path(os.environ['DJANGO_DB_PATH']).resolve()
        call_command('migrate', interactive=False, verbosity=0)
        assert ('api', '0029_oauth_attempt_snapshot') in MigrationRecorder(connection).applied_migrations()

        discovery = {
            'authorization_endpoint': 'https://auth.example/authorize',
            'token_endpoint': 'https://auth.example/token',
            'jwks_uri': 'https://auth.example/keys',
            'issuer': 'https://auth.example',
        }
        token_response = {
            'access_token': 'mock-access', 'refresh_token': 'mock-refresh',
            'id_token': 'mock-id-token', 'expires_in': 3600,
            'scope': f'openid offline_access resource.invoke {subscription.REQUIRED_DIRECT_SCOPE}',
        }
        origin = 'http://127.0.0.1:5173'
        session_key = 'concurrent-session'
        subscription._encryption_key = lambda: b'mode-tests-32-byte-key-material!'
        user = get_user_model().objects.create_user(username='file-race-reader', password='not-used')
        with patch.object(subscription, '_discovery', return_value=discovery):
            start = subscription.create_authorization_attempt(
                user, session_key=session_key, origin=origin,
            )
        browser_cookie, authorization_url = subscription.handoff_authorization(
            start['attempt_id'], start['handoff_token'], session_key=session_key, origin=origin,
        )
        state = parse_qs(urlparse(authorization_url).query)['state'][0]
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []
        result_lock = threading.Lock()

        def callback_worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                result = subscription.complete_authorization(
                    {'state': state, 'code': 'mock-code', 'client_id': 'issued-client'},
                    browser_cookie,
                    session_key=session_key,
                    user_id=user.pk,
                )
                with result_lock:
                    outcomes.append(result.pk)
            except Exception as exc:
                with result_lock:
                    errors.append((exc, traceback.format_exc()))
            finally:
                close_old_connections()

        with (
            patch.object(subscription, '_discovery', return_value=discovery),
            patch.object(subscription, '_exchange_code', return_value=token_response) as exchange,
            patch.object(subscription, '_verify_id_token', return_value={
                'iss': discovery['issuer'], 'sub': 'file-race-subject',
            }),
        ):
            threads = [threading.Thread(target=callback_worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

        assert all(not thread.is_alive() for thread in threads), 'callback worker exceeded bounded join'
        assert len(outcomes) == 1, errors
        assert len(errors) == 1 and isinstance(errors[0][0], subscription.SubscriptionError), errors
        exchange.assert_called_once()
        attempt = ChatGPTAuthAttempt.objects.get(pk=start['attempt_id'])
        assert attempt.status == 'completed'
        assert errors[0][0].error_code in ('subscription_error', 'oauth_storage_busy')
        print('DATABASE=', connection.settings_dict['NAME'])
        print('MIGRATED_0029=ok')
        print('IDENTITY_ENV=clean')
        print('OUTCOMES=', len(outcomes), 'SAFE_REJECTIONS=', len(errors), 'EXCHANGE_CALLS=', exchange.call_count)
    '''), encoding='utf-8')
    child_script.chmod(0o600)
    child_environment = {
        'HOME': str(home),
        'PATH': '/usr/bin:/bin',
        'PYTHONPATH': os.pathsep.join((str(backend_root), str(repository_root / 'crawler'))),
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'RUN_MAIN': 'true',
        'DJANGO_ENV': 'development',
        'DJANGO_DB_PATH': str(database_path),
        'CHATGPT_DEPLOYMENT_INSTANCE_ID': '00000000-0000-0000-0000-000000000008',
    }
    previous_umask = os.umask(0o077)
    try:
        result = subprocess.run(
            [sys.executable, str(child_script)],
            cwd=repository_root,
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    finally:
        os.umask(previous_umask)
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}'
    assert 'MIGRATED_0029=ok' in result.stdout
    assert 'IDENTITY_ENV=clean' in result.stdout
    assert 'OUTCOMES= 1 SAFE_REJECTIONS= 1 EXCHANGE_CALLS= 1' in result.stdout


def test_callback_view_uses_session_auth_and_clears_host_only_cookie(user, crypto):
    client = APIClient()
    client.force_login(user)
    session_key = client.cookies['sessionid'].value
    start = _start(user, session_key=session_key)
    browser_cookie, authorization_url = _handoff(start, session_key=session_key)
    state = parse_qs(urlparse(authorization_url).query)['state'][0]
    client.cookies[subscription.BINDING_COOKIE_NAME] = browser_cookie
    token_response = {
        'access_token': 'mock-access', 'refresh_token': 'mock-refresh',
        'id_token': 'mock-id-token', 'expires_in': 3600,
        'scope': f'openid offline_access resource.invoke {subscription.REQUIRED_DIRECT_SCOPE}',
    }
    with (
        patch.object(subscription, '_discovery', return_value=DISCOVERY),
        patch.object(subscription, '_exchange_code', return_value=token_response),
        patch.object(subscription, '_verify_id_token', return_value={
            'iss': DISCOVERY['issuer'], 'sub': 'mode-callback-subject',
        }),
    ):
        response = client.get(
            f'{CALLBACK_PATH}?state={state}&code=mock-code&client_id=issued-client',
            HTTP_HOST='127.0.0.1:9527',
        )

    assert response.status_code == 200
    assert '连接已完成' in response.content.decode()
    cookie = response.cookies[subscription.BINDING_COOKIE_NAME]
    assert cookie['path'] == CALLBACK_PATH
    assert cookie['max-age'] == 0
    assert cookie['httponly']
    assert cookie['samesite'] == 'Lax'
    assert cookie['domain'] == ''
    assert cookie['secure'] == ''


def test_callback_view_rejects_anonymous_and_returns_fixed_error_html(user):
    anonymous = APIClient()
    denied = anonymous.get(
        f'{CALLBACK_PATH}?state=do-not-echo-this-state',
        HTTP_HOST='127.0.0.1:9527',
    )
    assert denied.status_code in (401, 403)

    client = APIClient()
    client.force_login(user)
    client.cookies[subscription.BINDING_COOKIE_NAME] = 'expired-binding'
    response = client.get(
        f'{CALLBACK_PATH}?state=do-not-echo-this-state',
        HTTP_HOST='127.0.0.1:9527',
    )
    assert response.status_code == 400
    assert 'do-not-echo-this-state' not in response.content.decode()
    cookie = response.cookies[subscription.BINDING_COOKIE_NAME]
    assert cookie['path'] == CALLBACK_PATH
    assert cookie['max-age'] == 0
    assert cookie['domain'] == ''

    client.cookies[subscription.BINDING_COOKIE_NAME] = 'wrong-host-binding'
    wrong_host = client.get(
        f'{CALLBACK_PATH}?state=do-not-echo-this-state',
        HTTP_HOST='news.lambert.host',
    )
    assert wrong_host.status_code == 400
    assert 'do-not-echo-this-state' not in wrong_host.content.decode()
    assert wrong_host.cookies[subscription.BINDING_COOKIE_NAME]['path'] == CALLBACK_PATH


@pytest.mark.parametrize(
    ('mode', 'environment', 'expected_status', 'expected_error'),
    [
        # Existing PublicPolicyMiddleware short-circuits disabled routes before views.
        ('disabled', 'development', 403, 'chatgpt_auth_disabled'),
        ('website', 'development', 503, 'hosted_integration_unapproved'),
        ('local_oss', 'production', 403, 'local_oss_production_forbidden'),
    ],
)
def test_connect_view_preserves_fail_closed_mode_status(
    user, mode, environment, expected_status, expected_error,
):
    client = APIClient()
    client.force_authenticate(user=user)
    with (
        override_settings(CHATGPT_AUTH_MODE=mode, DJANGO_ENV=environment),
        patch.object(subscription, '_discovery') as discovery,
    ):
        response = client.post(
            '/api/chatgpt-subscription/connect/', {}, format='json', HTTP_ORIGIN=HANDOFF_ORIGIN,
        )
    assert response.status_code == expected_status
    assert response.json()['error_code'] == expected_error
    discovery.assert_not_called()


def test_migration_fails_only_legacy_pending_attempts_forward_in_isolated_database(tmp_path):
    backend_root = Path(__file__).resolve().parents[2]
    home = tmp_path / 'migration-home'
    home.mkdir(mode=0o700)
    database_path = tmp_path / 'snapshot-migration.sqlite3'
    child_code = r'''
import django
django.setup()
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from datetime import timedelta

executor = MigrationExecutor(connection)
before = ('api', '0028_account_security')
executor.migrate([before])
apps = executor.loader.project_state([before]).apps
User = apps.get_model('auth', 'User')
Attempt = apps.get_model('api', 'ChatGPTAuthAttempt')
user = User.objects.create(username='migration-mode-user')
created = {}
for index, state in enumerate(('pending', 'authorizing', 'processing', 'completed', 'failed', 'cancelled')):
    created[state] = Attempt.objects.create(
        user_id=user.pk, state_hash=f'legacy-state-{index}', nonce_hash='n' * 64,
        encrypted_pkce_verifier='encrypted-verifier', encrypted_authorization_url='encrypted-url',
        handoff_token_hash='h' * 64, requested_client_id='dynamic_agent_client',
        status=state, status_message=f'legacy-{state}', expires_at=timezone.now() + timedelta(minutes=5),
    ).pk
executor = MigrationExecutor(connection)
executor.migrate([('api', '0029_oauth_attempt_snapshot')])
apps = executor.loader.project_state([('api', '0029_oauth_attempt_snapshot')]).apps
Attempt = apps.get_model('api', 'ChatGPTAuthAttempt')
for state in ('pending', 'authorizing', 'processing'):
    attempt = Attempt.objects.get(pk=created[state])
    assert (attempt.status, attempt.status_message) == ('failed', 'config_changed')
    assert attempt.auth_mode == '' and attempt.protocol_snapshot == {} and attempt.config_fingerprint == ''
for state in ('completed', 'failed', 'cancelled'):
    attempt = Attempt.objects.get(pk=created[state])
    assert (attempt.status, attempt.status_message) == (state, f'legacy-{state}')
'''
    environment = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'HOME': str(home),
        'PYTHONPATH': os.pathsep.join((str(backend_root), str(backend_root.parent / 'crawler'))),
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings',
        'DJANGO_ENV': 'development',
        'RUN_MAIN': 'true',
        'DJANGO_DB_PATH': str(database_path),
    }
    result = subprocess.run(
        [sys.executable, '-c', child_code],
        cwd=str(backend_root),
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}'

