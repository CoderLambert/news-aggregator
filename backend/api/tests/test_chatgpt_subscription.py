"""Mock-only coverage for local ChatGPT subscription auth and translation."""

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.contrib.auth import get_user_model
from django.db import connection as django_connection
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from api.models import (
    Category,
    ChatGPTArticleTranslation,
    ChatGPTAuthAttempt,
    ChatGPTOAuthClient,
    ChatGPTSubscriptionConnection,
    News,
    Source,
)
from api.serializers import NewsDetailSerializer
from api.services import chatgpt_subscription as subscription
from api.services import chatgpt_subscription_jobs as translation_jobs

User = get_user_model()
HANDOFF_ORIGIN = 'http://127.0.0.1:5173'


@pytest.fixture
def crypto(monkeypatch):
    monkeypatch.setattr(subscription, '_encryption_key', lambda: b'x' * 32)


@pytest.fixture
def clear_subscription_jobs():
    with translation_jobs._jobs_lock:
        translation_jobs._jobs.clear()
    yield
    with translation_jobs._jobs_lock:
        translation_jobs._jobs.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(username='local-reader', password='not-used')


@pytest.fixture
def news(db):
    category = Category.objects.create(name='Tech', slug='tech')
    source = Source.objects.create(name='Example', url='https://example.com', language='en')
    return News.objects.create(
        title='Full article',
        content='Short body',
        url='https://example.com/article',
        source=source,
        category=category,
        publish_time=timezone.now(),
        full_content='# Original article\n\nFull English text.',
        full_content_zh='SHARED PUBLIC TRANSLATION',
    )


def make_connection(user, *, active=True, subject='provider-subject', generation=0, client_id='issued-client-id'):
    issuer = 'https://auth.example'
    installation = subscription.get_installation_client()
    return ChatGPTSubscriptionConnection.objects.create(
        user=user,
        subject_hash=subscription._subject_hash(subject),
        issuer=issuer,
        issued_client_id=client_id,
        registration_key_hash=subscription._registration_key_hash(issuer, client_id, installation.host_id, subject),
        encrypted_subject=subscription.encrypt_secret(subject, 'verified-oauth-subject'),
        granted_scopes=[subscription.REQUIRED_DIRECT_SCOPE],
        account_name=subject,
        encrypted_access_token=subscription.encrypt_secret('access-token', 'subscription-access-token'),
        encrypted_refresh_token=subscription.encrypt_secret('refresh-token', 'subscription-refresh-token'),
        access_token_expires_at=timezone.now() + timedelta(hours=1),
        selected_model='listed-model-slug',
        is_active=active,
        needs_reauth=False,
        generation=generation,
    )


class FakeResponse:
    def __init__(self, status_code=200, payload=None, lines=(), text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = list(lines)
        self.text = text
        self.closed = False

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        yield from self._lines

    def close(self):
        self.closed = True


def _attempt(user, state, *, expires_at=None, client_id=subscription.DYNAMIC_CLIENT_ID, target=None, browser_cookie='browser-cookie'):
    return ChatGPTAuthAttempt.objects.create(
        user=user,
        target_connection=target,
        state_hash=subscription._digest(state),
        nonce_hash=hashlib.sha256(b'nonce').hexdigest(),
        encrypted_pkce_verifier='encrypted-verifier',
        encrypted_authorization_url='encrypted-url',
        handoff_token_hash='unused-handoff-token',
        browser_binding_hash=subscription._digest(browser_cookie),
        requested_client_id=client_id,
        target_attempt_generation=target.auth_attempt_generation if target else 0,
        status='authorizing',
        expires_at=expires_at or (timezone.now() + timedelta(minutes=5)),
    )


def _create_attempt(user, *, session_key, target=None):
    return subscription.create_authorization_attempt(
        user, target, session_key=session_key, origin=HANDOFF_ORIGIN,
    )


def _handoff(start, *, session_key):
    return subscription.handoff_authorization(
        start['attempt_id'], start['handoff_token'],
        session_key=session_key, origin=HANDOFF_ORIGIN,
    )


def test_callback_rejects_authorization_without_direct_scope(user, crypto):
    state = 'one-use-state'
    _attempt(user, state)
    token_response = {
        'access_token': 'access',
        'refresh_token': 'refresh',
        'id_token': 'signed-id-token',
        'expires_in': 3600,
        'scope': 'openid profile email offline_access resource.invoke',
    }
    with (
        patch.object(subscription, '_discovery', return_value={
            'token_endpoint': 'https://auth.example/token',
            'issuer': 'https://auth.example',
            'jwks_uri': 'https://auth.example/keys',
        }),
        patch.object(subscription, 'decrypt_secret', return_value='pkce-verifier'),
        patch.object(subscription, '_exchange_code', return_value=token_response),
        patch.object(subscription, '_verify_id_token', return_value={'sub': 'account-1'}),
    ):
        with pytest.raises(subscription.SubscriptionError, match='direct model access'):
            subscription.complete_authorization({'state': state, 'code': 'authorization-code', 'client_id': 'issued-client-id'}, 'browser-cookie')
    assert not ChatGPTSubscriptionConnection.objects.filter(user=user).exists()


def test_auth_register_login_and_logout_do_not_require_subscription_encryption_key(db, monkeypatch):
    def unavailable_key():
        raise AssertionError('ordinary local authentication must not access the subscription key')

    monkeypatch.setattr(subscription, '_encryption_key', unavailable_key)
    client = APIClient()
    credentials = {'username': 'reader-without-subscription-key', 'password': 'strong-enough-password'}

    registered = client.post('/api/auth/register/', credentials, format='json')
    assert registered.status_code == 201
    logged_in = client.post('/api/auth/login/', credentials, format='json')
    assert logged_in.status_code == 200
    logged_out = client.post('/api/auth/logout/', {}, format='json')
    assert logged_out.status_code == 200


def test_handoff_requires_the_starting_origin_and_local_session(user, crypto):
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    client = APIClient()
    client.force_authenticate(user=user)
    with patch.object(subscription, '_discovery', return_value=discovery):
        started = client.post(
            '/api/chatgpt-subscription/connect/', {}, format='json', HTTP_ORIGIN=HANDOFF_ORIGIN,
        )
    assert started.status_code == 201
    assert client.cookies.get('sessionid') is not None
    payload = {
        'attempt_id': started.data['attempt_id'],
        'handoff_token': started.data['handoff_token'],
    }

    other_client = APIClient()
    ticket_only = other_client.post(
        '/api/chatgpt-subscription/handoff/', payload, format='json', HTTP_ORIGIN=HANDOFF_ORIGIN,
    )
    assert ticket_only.status_code == 400
    assert 'Location' not in ticket_only
    assert subscription.BINDING_COOKIE_NAME not in ticket_only.cookies

    wrong_origin = client.post(
        '/api/chatgpt-subscription/handoff/', payload, format='json', HTTP_ORIGIN='https://example.com',
    )
    assert wrong_origin.status_code == 400
    assert 'Location' not in wrong_origin
    assert subscription.BINDING_COOKIE_NAME not in wrong_origin.cookies

    missing_origin = client.post('/api/chatgpt-subscription/handoff/', payload, format='json')
    assert missing_origin.status_code == 400
    assert 'Location' not in missing_origin
    assert subscription.BINDING_COOKIE_NAME not in missing_origin.cookies

    handed_off = client.post(
        '/api/chatgpt-subscription/handoff/', payload, format='json', HTTP_ORIGIN=HANDOFF_ORIGIN,
    )
    assert handed_off.status_code == 302
    assert handed_off['Location'].startswith('https://auth.example/authorize?')
    assert subscription.BINDING_COOKIE_NAME in handed_off.cookies


def test_reconnect_callback_does_not_override_a_newer_account_selection(user, crypto):
    account_a = make_connection(user, subject='account-a')
    account_b = make_connection(user, active=False, subject='account-b')
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    token_response = {
        'access_token': 'updated-a-access', 'refresh_token': 'updated-a-refresh',
        'id_token': 'mock-id-token', 'expires_in': 3600,
        'scope': f'openid offline_access resource.invoke {subscription.REQUIRED_DIRECT_SCOPE}',
    }
    real_decrypt = subscription.decrypt_secret
    with (
        patch.object(subscription, '_discovery', return_value=discovery),
        patch.object(
            subscription, 'decrypt_secret',
            side_effect=lambda value, purpose: 'mock-pkce-verifier' if purpose == 'oauth-pkce-verifier' else real_decrypt(value, purpose),
        ),
    ):
        start = _create_attempt(user, target=account_a, session_key='reconnect-selection-session')
        cookie, authorization_url = _handoff(start, session_key='reconnect-selection-session')
        state = parse_qs(urlparse(authorization_url).query)['state'][0]

        def switch_then_exchange(*_args, **_kwargs):
            subscription.activate_connection(user, account_b.pk)
            return token_response

        with (
            patch.object(subscription, '_exchange_code', side_effect=switch_then_exchange),
            patch.object(subscription, '_verify_id_token', return_value={
                'iss': 'https://auth.example', 'sub': 'account-a', 'name': 'Account A',
            }),
        ):
            completed = subscription.complete_authorization({
                'state': state, 'code': 'mock-code', 'client_id': account_a.issued_client_id,
            }, cookie)

    account_a.refresh_from_db()
    account_b.refresh_from_db()
    assert completed.pk == account_a.pk
    assert account_a.is_active is False
    assert account_b.is_active is True
    assert subscription.decrypt_secret(account_a.encrypted_access_token, 'subscription-access-token') == 'updated-a-access'


def test_dynamic_oauth_callback_persists_issued_client_id_and_encrypted_tokens(user, crypto):
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    token_response = {
        'access_token': 'mock-access',
        'refresh_token': 'mock-refresh',
        'id_token': 'mock-id-token',
        'expires_in': 3600,
        'scope': f'openid offline_access resource.invoke {subscription.REQUIRED_DIRECT_SCOPE}',
    }
    real_decrypt = subscription.decrypt_secret
    with (
        patch.object(subscription, '_discovery', return_value=discovery),
        patch.object(
            subscription, 'decrypt_secret',
            side_effect=lambda value, purpose: 'mock-pkce-verifier' if purpose == 'oauth-pkce-verifier' else real_decrypt(value, purpose),
        ),
    ):
        start = _create_attempt(user, session_key='local-session-1')
        browser_cookie, authorization_url = _handoff(start, session_key='local-session-1')
        params = parse_qs(urlparse(authorization_url).query)
        assert params['client_id'] == [subscription.DYNAMIC_CLIENT_ID]
        assert params['redirect_uri'] == [subscription.REDIRECT_URI]
        assert params['code_challenge_method'] == ['S256']
        assert params['resource'] == [subscription.API_RESOURCE]
        assert subscription.REQUIRED_DIRECT_SCOPE in params['scope'][0].split()
        state = params['state'][0]
        with (
            patch.object(subscription, '_exchange_code', return_value=token_response) as exchange,
            patch.object(subscription, '_verify_id_token', return_value={
                'iss': 'https://auth.example', 'sub': 'account-subject', 'name': 'Reader', 'email': 'reader@example.com',
            }),
        ):
            connection = subscription.complete_authorization({
                'state': state, 'code': 'mock-code', 'client_id': 'issued-client-id',
            }, browser_cookie)
            assert exchange.call_args.args[1] == 'issued-client-id'

    installation = ChatGPTOAuthClient.objects.get(pk=1)
    connection.refresh_from_db()
    assert installation.host_id.startswith('urn:uuid:')
    assert connection.issued_client_id == 'issued-client-id'
    assert connection.account_name == 'Reader'
    assert connection.account_email == 'reader@example.com'
    assert connection.connected and connection.is_active
    assert subscription.decrypt_secret(connection.encrypted_access_token, 'subscription-access-token') == 'mock-access'
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'mock-refresh'
    with patch.object(subscription, '_discovery', return_value=discovery):
        next_start = _create_attempt(user, target=connection, session_key='local-session-2')
        _, next_url = _handoff(next_start, session_key='local-session-2')
    next_params = parse_qs(urlparse(next_url).query)
    assert next_params['client_id'] == ['issued-client-id']
    assert 'agent_name_hint' not in next_params


def test_expired_oauth_state_is_rejected(user):
    state = 'expired-state'
    attempt = _attempt(user, state, expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(subscription.SubscriptionError, match='已过期'):
        subscription.complete_authorization({'state': state, 'code': 'ignored'}, 'browser-cookie')
    attempt.refresh_from_db()
    assert attempt.status == 'failed'


def test_expired_handoff_is_recorded_as_failed(user, crypto):
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    with patch.object(subscription, '_discovery', return_value=discovery):
        start = _create_attempt(user, session_key='expired-handoff-session')
    ChatGPTAuthAttempt.objects.filter(pk=start['attempt_id']).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    with pytest.raises(subscription.SubscriptionError, match='已过期'):
        _handoff(start, session_key='expired-handoff-session')

    assert subscription.authorization_attempt_status(user, start['attempt_id'])['status'] == 'failed'


def test_id_token_signature_issuer_audience_expiry_and_nonce_are_verified(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        'kid': 'test-key',
        'kty': 'RSA',
        'n': subscription._b64url(public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, 'big')),
        'e': subscription._b64url(public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, 'big')),
    }
    now = timezone.now().timestamp()

    def make_token(expiry, *, audience='issued-client', nonce='test-nonce'):
        header = subscription._b64url(json.dumps({'alg': 'RS256', 'kid': 'test-key'}).encode())
        claims = subscription._b64url(json.dumps({
            'iss': 'https://issuer.example',
            'aud': audience,
            'sub': 'account-subject',
            'nonce': nonce,
            'iat': now,
            'exp': expiry,
        }).encode())
        signed = f'{header}.{claims}'.encode('ascii')
        signature = private_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return f'{header}.{claims}.{subscription._b64url(signature)}'

    monkeypatch.setattr(
        'api.services.chatgpt_subscription.requests.get',
        lambda *args, **kwargs: FakeResponse(payload={'keys': [jwk]}),
    )
    discovery = {'jwks_uri': 'https://issuer.example/keys', 'issuer': 'https://issuer.example'}
    nonce_hash = hashlib.sha256(b'test-nonce').hexdigest()
    claims = subscription._verify_id_token(make_token(now + 300), 'issued-client', nonce_hash, discovery)
    assert claims['sub'] == 'account-subject'
    with pytest.raises(subscription.SubscriptionError, match='已过期'):
        subscription._verify_id_token(make_token(now - 1), 'issued-client', nonce_hash, discovery)
    with pytest.raises(subscription.SubscriptionError, match='audience'):
        subscription._verify_id_token(make_token(now + 300, audience='wrong-client'), 'issued-client', nonce_hash, discovery)
    with pytest.raises(subscription.SubscriptionError, match='nonce'):
        subscription._verify_id_token(make_token(now + 300, nonce='wrong-nonce'), 'issued-client', nonce_hash, discovery)
    with pytest.raises(subscription.SubscriptionError, match='签名验证失败'):
        tampered = make_token(now + 300).rsplit('.', 1)
        bad_signature = subscription._b64url(b'not-a-valid-signature')
        subscription._verify_id_token(f'{tampered[0]}.{bad_signature}', 'issued-client', nonce_hash, discovery)


def test_refresh_rotates_refresh_token_once_and_reuses_fresh_access_token(user, crypto, transactional_db):
    connection = make_connection(user)
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=5)
    connection.save(update_fields=['access_token_expires_at'])
    refresh_response = FakeResponse(payload={
        'access_token': 'rotated-access',
        'refresh_token': 'rotated-refresh',
        'expires_in': 3600,
    })
    post_mock = Mock(return_value=refresh_response)
    with (
        patch.object(subscription, '_discovery', return_value={'token_endpoint': 'https://auth.example/token'}),
        patch('api.services.chatgpt_subscription.requests.post', post_mock),
    ):
        assert subscription._refresh_access_token(connection.pk) == 'rotated-access'
        assert subscription._refresh_access_token(connection.pk) == 'rotated-access'
    assert post_mock.call_count == 1
    assert post_mock.call_args.kwargs['data']['client_id'] == 'issued-client-id'
    connection.refresh_from_db()
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'rotated-refresh'
    assert connection.credential_generation == 1


@pytest.mark.parametrize('advance_credential_generation', [False, True])
def test_refresh_rereads_rotated_credentials_before_using_a_stale_refresh_token(
    user, crypto, advance_credential_generation,
):
    connection = make_connection(user)
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=5)
    connection.save(update_fields=['access_token_expires_at'])
    original_acquire = subscription._acquire_refresh_lease
    rotated = False

    def rotate_before_lease(connection_id, credential_generation, now, lease_id):
        nonlocal rotated
        if not rotated:
            rotated = True
            updates = {
                'encrypted_access_token': subscription.encrypt_secret('worker-b-access', 'subscription-access-token'),
                'encrypted_refresh_token': subscription.encrypt_secret('worker-b-refresh', 'subscription-refresh-token'),
                'access_token_expires_at': now + timedelta(hours=1),
            }
            if advance_credential_generation:
                updates['credential_generation'] = credential_generation + 1
            ChatGPTSubscriptionConnection.objects.filter(pk=connection_id).update(**updates)
        return original_acquire(connection_id, credential_generation, now, lease_id)

    post = Mock()
    with (
        patch.object(subscription, '_acquire_refresh_lease', side_effect=rotate_before_lease),
        patch('api.services.chatgpt_subscription.requests.post', post),
    ):
        assert subscription._refresh_access_token(connection.pk) == 'worker-b-access'

    post.assert_not_called()
    connection.refresh_from_db()
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'worker-b-refresh'
    assert connection.needs_reauth is False
    assert connection.refresh_lease_id == ''



@pytest.mark.parametrize('post_acquire_behavior', ['switch', 'raise', 'new_owner'])
def test_refresh_releases_only_its_lease_after_post_acquire_failure(
    user, crypto, transactional_db, monkeypatch, post_acquire_behavior,
):
    connection = make_connection(user, subject='lease-owner')
    other = make_connection(user, active=False, subject='other-owner')
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=5)
    connection.save(update_fields=['access_token_expires_at'])
    expected_generation = connection.generation
    original_acquire = subscription._acquire_refresh_lease
    original_assert = subscription._assert_current_selection
    lease_ids = []

    def acquire_then_change(connection_id, credential_generation, now, lease_id):
        acquired = original_acquire(connection_id, credential_generation, now, lease_id)
        if acquired:
            lease_ids.append(lease_id)
            if post_acquire_behavior == 'switch':
                subscription.activate_connection(user, other.pk)
                subscription.activate_connection(user, connection.pk)
            elif post_acquire_behavior == 'new_owner':
                ChatGPTSubscriptionConnection.objects.filter(
                    pk=connection_id, refresh_lease_id=lease_id,
                ).update(
                    refresh_lease_id='new-owner-lease',
                    refresh_lease_expires_at=timezone.now() + subscription.REFRESH_LEASE_TTL,
                )
        return acquired

    def assert_selection_after_acquire(current, expected=None):
        if lease_ids:
            if post_acquire_behavior == 'switch':
                return original_assert(current, expected)
            raise RuntimeError('injected post-acquisition selection failure')
        return original_assert(current, expected)

    post = Mock(side_effect=AssertionError('refresh HTTP must not run in this test'))
    monkeypatch.setattr(subscription, '_acquire_refresh_lease', acquire_then_change)
    monkeypatch.setattr(subscription, '_assert_current_selection', assert_selection_after_acquire)
    monkeypatch.setattr(subscription.requests, 'post', post)

    if post_acquire_behavior == 'switch':
        with pytest.raises(subscription.ConnectionChangedError, match='切换或断开'):
            subscription._refresh_access_token(connection.pk, expected_generation)
    else:
        with pytest.raises(RuntimeError, match='post-acquisition'):
            subscription._refresh_access_token(connection.pk, expected_generation)

    post.assert_not_called()
    connection.refresh_from_db()
    assert lease_ids
    if post_acquire_behavior == 'new_owner':
        assert connection.refresh_lease_id == 'new-owner-lease'
        assert connection.refresh_lease_expires_at is not None
    else:
        assert connection.refresh_lease_id == ''
        assert connection.refresh_lease_expires_at is None
    if post_acquire_behavior == 'switch':
        assert connection.is_active
        assert connection.generation > expected_generation

def test_switching_accounts_invalidates_late_result_and_private_results_do_not_leak(user, news, crypto):
    first = make_connection(user, subject='first-account')
    second = make_connection(user, active=False, subject='second-account')
    ChatGPTArticleTranslation.objects.create(
        user=user,
        connection=second,
        news=news,
        source_hash=subscription.source_hash(news.full_content),
        model_slug='listed-model-slug',
        content='SECOND ACCOUNT PRIVATE RESULT',
        completed_at=timezone.now(),
    )
    old_generation = first.generation
    subscription.activate_connection(user, second.pk)
    first.refresh_from_db()
    assert first.is_active is False
    assert first.generation == old_generation + 1
    with pytest.raises(subscription.ConnectionChangedError, match='已切换或断开'):
        subscription.save_completed_translation(
            user_id=user.pk,
            connection_id=first.pk,
            news_id=news.pk,
            expected_generation=old_generation,
            model_slug='listed-model-slug',
            text='LATE RESULT',
            source_digest=subscription.source_hash(news.full_content),
        )

    request = APIRequestFactory().get('/api/news/1/')
    request.user = user
    serialized = NewsDetailSerializer(news, context={'request': request}).data
    assert serialized['full_content_zh'] == 'SECOND ACCOUNT PRIVATE RESULT'
    assert serialized['full_content_zh_source'] == 'chatgpt'


def test_disconnect_clears_tokens_advances_generation_and_revokes(user, news, crypto):
    connection = make_connection(user)
    previous_generation = connection.generation
    response = FakeResponse(status_code=200)
    with (
        patch.object(subscription, '_discovery', return_value={'revocation_endpoint': 'https://auth.example/revoke'}),
        patch('api.services.chatgpt_subscription.requests.post', return_value=response) as post,
    ):
        confirmed = subscription.disconnect_connection(user, connection.pk)
    connection.refresh_from_db()
    assert confirmed is True
    assert post.call_args.kwargs['data']['token'] == 'refresh-token'
    assert connection.encrypted_access_token == ''
    assert connection.encrypted_refresh_token == ''
    assert connection.is_active is False
    assert connection.generation == previous_generation + 1
    with pytest.raises(subscription.ConnectionChangedError, match='已切换或断开'):
        subscription.save_completed_translation(
            user_id=user.pk,
            connection_id=connection.pk,
            news_id=news.pk,
            expected_generation=previous_generation,
            model_slug='listed-model-slug',
            text='late result',
            source_digest=subscription.source_hash(news.full_content),
        )
    assert not ChatGPTArticleTranslation.objects.filter(user=user, connection=connection, news=news).exists()


def test_discovery_returns_only_list_visible_models_and_preserves_slugs(user, crypto):
    connection = make_connection(user)
    payload = {'models': [
        {'slug': 'z-server-slug-v2', 'display_name': 'Zulu Model', 'visibility': 'list'},
        {'slug': 'hidden-server-slug', 'display_name': 'Hidden', 'visibility': 'hidden'},
        {'slug': 'a-server-slug-v1', 'display_name': 'Alpha Model', 'visibility': 'list'},
    ]}
    with (
        patch.object(subscription, 'access_token_for', return_value='mock-access'),
        patch('api.services.chatgpt_subscription.requests.get', return_value=FakeResponse(payload=payload)),
    ):
        assert subscription.discover_models(connection) == [
            {'slug': 'z-server-slug-v2', 'display_name': 'Zulu Model'},
            {'slug': 'a-server-slug-v1', 'display_name': 'Alpha Model'},
        ]


def test_discovery_401_marks_the_generation_created_by_a_token_refresh(user, crypto):
    connection = make_connection(user)

    def refresh_and_return(_connection):
        ChatGPTSubscriptionConnection.objects.filter(pk=connection.pk).update(
            credential_generation=connection.credential_generation + 1,
        )
        return 'refreshed-access'

    with (
        patch.object(subscription, 'access_token_for', side_effect=refresh_and_return),
        patch(
            'api.services.chatgpt_subscription.requests.get',
            return_value=FakeResponse(status_code=401),
        ),
    ):
        with pytest.raises(subscription.SubscriptionError, match='重新连接账号'):
            subscription.discover_models(connection)

    connection.refresh_from_db()
    assert connection.needs_reauth is True
    assert connection.credential_generation == 2


def test_subscription_views_are_scoped_and_never_return_credentials(user, crypto):
    own_connection = make_connection(user)
    other_user = User.objects.create_user(username='other-reader', password='not-used')
    other_connection = make_connection(other_user, subject='other-account')
    client = APIClient()
    client.force_authenticate(user=user)

    status_response = client.get('/api/chatgpt-subscription/')
    assert status_response.status_code == 200
    assert [item['id'] for item in status_response.data['connections']] == [str(own_connection.pk)]
    assert 'access_token' not in json.dumps(status_response.data)
    assert 'refresh_token' not in json.dumps(status_response.data)

    models_response = client.get(f'/api/chatgpt-subscription/connections/{other_connection.pk}/models/')
    assert models_response.status_code == 400
    assert '不存在' in models_response.data['error']
    connect_response = client.post(
        '/api/chatgpt-subscription/connect/',
        {'connection_id': str(other_connection.pk)},
        format='json',
    )
    assert connect_response.status_code == 400
    assert '不存在' in connect_response.data['error']


def test_subscription_api_requires_authentication_and_csrf_for_connect(user, crypto):
    anonymous = APIClient(enforce_csrf_checks=True)
    assert anonymous.get('/api/chatgpt-subscription/').status_code in (401, 403)
    with patch.object(subscription, '_discovery') as discovery:
        response = anonymous.post('/api/chatgpt-subscription/connect/', {}, format='json')
    assert response.status_code in (401, 403)
    discovery.assert_not_called()
    assert not ChatGPTAuthAttempt.objects.exists()

    no_csrf = APIClient(enforce_csrf_checks=True)
    no_csrf.force_login(user)
    rejected = no_csrf.post('/api/chatgpt-subscription/connect/', {}, format='json')
    assert rejected.status_code == 403
    assert not ChatGPTAuthAttempt.objects.exists()

    authorized = APIClient(enforce_csrf_checks=True)
    authorized.force_login(user)
    csrf_response = authorized.get('/api/auth/csrf/')
    token = csrf_response.cookies['csrftoken'].value
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    with patch.object(subscription, '_discovery', return_value=discovery):
        accepted = authorized.post(
            '/api/chatgpt-subscription/connect/', {}, format='json',
            HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN=HANDOFF_ORIGIN,
        )
    assert accepted.status_code == 201
    assert ChatGPTAuthAttempt.objects.filter(user=user, status='pending').count() == 1


def test_active_subscription_errors_do_not_fall_back_to_provider_api_key(user, news, crypto):
    connection = make_connection(user)
    connection.needs_reauth = True
    connection.save(update_fields=['needs_reauth'])
    client = APIClient()
    client.force_authenticate(user=user)
    with patch('api.views.get_clients') as get_clients:
        response = client.post(f'/api/news/{news.pk}/translate/', {'force': False}, format='json')
        body = b''.join(response.streaming_content).decode('utf-8')
    assert '重新连接账号' in body
    get_clients.assert_not_called()


def test_responses_http400_uses_safe_json_fields_without_echoing_provider_message(user, crypto):
    connection = make_connection(user)
    response = FakeResponse(status_code=400, payload={
        'error': {
            'type': 'unsupported_parameter',
            'param': 'temperature',
            'message': 'DO_NOT_ECHO_ARTICLE_OR_CREDENTIAL_SENTINEL',
        },
    })
    with (
        patch('api.services.chatgpt_subscription._refresh_access_token', return_value='mock-bearer'),
        patch('api.services.chatgpt_subscription.requests.post', return_value=response),
    ):
        with pytest.raises(subscription.SubscriptionError) as error:
            subscription.stream_full_translation(
                connection.pk, connection.generation, 'listed-model-slug',
                'mock article body', Mock(),
            )

    assert response.closed is True
    assert 'HTTP 400' in str(error.value)
    assert 'temperature' in str(error.value)
    assert 'DO_NOT_ECHO_ARTICLE_OR_CREDENTIAL_SENTINEL' not in str(error.value)
    assert 'mock article body' not in str(error.value)


def test_responses_http400_uses_recognized_type_when_code_is_unknown(user, crypto):
    connection = make_connection(user)
    response = FakeResponse(status_code=400, payload={
        'error': {
            'code': 'provider_specific_rejection',
            'type': 'invalid_request_error',
            'param': 'input',
            'message': 'DO_NOT_ECHO_ARTICLE_OR_CREDENTIAL_SENTINEL',
        },
    })
    with (
        patch('api.services.chatgpt_subscription._refresh_access_token', return_value='mock-bearer'),
        patch('api.services.chatgpt_subscription.requests.post', return_value=response),
    ):
        with pytest.raises(subscription.SubscriptionError) as error:
            subscription.stream_full_translation(
                connection.pk, connection.generation, 'listed-model-slug',
                'mock article body', Mock(),
            )

    assert response.closed is True
    assert '翻译请求格式' in str(error.value)
    assert '参数 input' in str(error.value)
    assert 'DO_NOT_ECHO_ARTICLE_OR_CREDENTIAL_SENTINEL' not in str(error.value)
    assert 'mock article body' not in str(error.value)
    assert 'provider_specific_rejection' not in str(error.value)


def test_responses_http400_non_json_body_stays_generic_and_safe(user, crypto):
    connection = make_connection(user)

    class NonJsonResponse(FakeResponse):
        def json(self):
            raise ValueError('DO_NOT_ECHO_NON_JSON_RESPONSE_SENTINEL')

    response = NonJsonResponse(status_code=400)
    with (
        patch('api.services.chatgpt_subscription._refresh_access_token', return_value='mock-bearer'),
        patch('api.services.chatgpt_subscription.requests.post', return_value=response),
    ):
        with pytest.raises(subscription.SubscriptionError) as error:
            subscription.stream_full_translation(
                connection.pk, connection.generation, 'listed-model-slug',
                'mock article body', Mock(),
            )

    assert response.closed is True
    assert str(error.value) == 'OpenAI 模型请求失败（HTTP 400）。'
    assert 'DO_NOT_ECHO_NON_JSON_RESPONSE_SENTINEL' not in str(error.value)


def test_responses_http400_unknown_json_error_does_not_echo_sensitive_fields(user, crypto):
    connection = make_connection(user)
    response = FakeResponse(status_code=400, payload={
        'error': {
            'code': 'invalid_request_error',
            'param': 'input',
            'message': 'DO_NOT_ECHO_UNKNOWN_ARTICLE_OR_BEARER_SENTINEL',
            'metadata': {'submitted_text': 'DO_NOT_ECHO_METADATA_SENTINEL'},
        },
    })
    with (
        patch('api.services.chatgpt_subscription._refresh_access_token', return_value='mock-bearer'),
        patch('api.services.chatgpt_subscription.requests.post', return_value=response),
    ):
        with pytest.raises(subscription.SubscriptionError) as error:
            subscription.stream_full_translation(
                connection.pk, connection.generation, 'listed-model-slug',
                'mock article body', Mock(),
            )

    assert response.closed is True
    assert 'HTTP 400' in str(error.value)
    assert '参数 input' in str(error.value)
    assert 'DO_NOT_ECHO_UNKNOWN_ARTICLE_OR_BEARER_SENTINEL' not in str(error.value)
    assert 'DO_NOT_ECHO_METADATA_SENTINEL' not in str(error.value)
    assert 'mock article body' not in str(error.value)


@pytest.mark.parametrize(
    ('lines', 'expected_content', 'expected_error'),
    [
        (
            [
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":"第一段"}',
                '',
                'event: response.completed',
                'data: {"type":"response.completed","response":{"status":"completed","output_text":"完整译文"}}',
            ],
            '完整译文',
            None,
        ),
        (
            [
                'event: response.output_text.delta',
                'data: {"type":"response.output_text.delta","delta":"未完成片段"}',
            ],
            None,
            'response.completed 前中断',
        ),
    ],
)
def test_responses_sse_saves_only_after_completed_event(
    user, news, crypto, clear_subscription_jobs, transactional_db, lines, expected_content, expected_error,
):
    connection = make_connection(user)
    response = FakeResponse(lines=lines)
    request_mock = Mock(return_value=response)
    with (
        patch('api.services.chatgpt_subscription._refresh_access_token', return_value='mock-bearer'),
        patch('api.services.chatgpt_subscription.requests.post', request_mock),
    ):
        job = translation_jobs.start_or_get_job(user, connection, news)
        deadline = time.monotonic() + 5
        while not job.done and time.monotonic() < deadline:
            job.wait_for_update(len(job.text), timeout=0.05)

    assert job.done
    assert response.closed is True
    sent_payload = request_mock.call_args.kwargs['json']
    assert set(sent_payload) == {'model', 'input', 'store', 'stream'}
    assert sent_payload['model'] == 'listed-model-slug'
    assert sent_payload['store'] is False
    assert sent_payload['stream'] is True
    assert isinstance(sent_payload['input'], list)
    assert len(sent_payload['input']) == 1
    assert set(sent_payload['input'][0]) == {'role', 'content'}
    assert sent_payload['input'][0]['role'] == 'user'
    assert sent_payload['input'][0]['content'].endswith(news.full_content)
    assert not {'temperature', 'max_output_tokens', 'metadata', 'previous_response_id'} & set(sent_payload)
    if expected_content:
        assert job.error is None
        assert job.result['full_content_zh'] == expected_content
        record = ChatGPTArticleTranslation.objects.get(user=user, connection=connection, news=news)
        assert record.content == expected_content
    else:
        assert expected_error in job.error
        assert ChatGPTArticleTranslation.objects.filter(user=user, connection=connection, news=news).count() == 0





def test_host_id_is_stable_urn_uuid_and_registration_is_client_scoped(user, crypto):
    first_host = subscription.get_installation_client().host_id
    second_host = subscription.get_installation_client().host_id
    first = make_connection(user, subject='same-subject', client_id='workspace-client-a')
    second = make_connection(user, subject='same-subject', client_id='workspace-client-b', active=False)
    assert first_host == second_host
    assert first_host.startswith('urn:uuid:')
    assert first.subject_hash == second.subject_hash
    assert first.registration_key_hash != second.registration_key_hash
    assert ChatGPTSubscriptionConnection.objects.filter(user=user).count() == 2


def test_id_token_scope_claim_cannot_replace_missing_token_response_scope(user, crypto):
    state = 'scope-fallback-state'
    _attempt(user, state)
    token_response = {
        'access_token': 'access', 'refresh_token': 'refresh',
        'id_token': 'signed-id-token', 'expires_in': 3600,
    }
    with (
        patch.object(subscription, '_discovery', return_value={
            'token_endpoint': 'https://auth.example/token',
            'issuer': 'https://auth.example', 'jwks_uri': 'https://auth.example/keys',
        }),
        patch.object(subscription, 'decrypt_secret', return_value='pkce-verifier'),
        patch.object(subscription, '_exchange_code', return_value=token_response),
        patch.object(subscription, '_verify_id_token', return_value={
            'iss': 'https://auth.example', 'sub': 'account-1',
            'scope': subscription.REQUIRED_DIRECT_SCOPE,
        }),
    ):
        with pytest.raises(subscription.SubscriptionError, match='direct model access'):
            subscription.complete_authorization(
                {'state': state, 'code': 'authorization-code', 'client_id': 'issued-client-id'},
                'browser-cookie',
            )
    assert not ChatGPTSubscriptionConnection.objects.filter(user=user).exists()


def test_handoff_is_one_use_and_callback_requires_the_same_browser_cookie(user, crypto):
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    with patch.object(subscription, '_discovery', return_value=discovery):
        start = _create_attempt(user, session_key='same-browser-session')
        cookie, authorization_url = _handoff(start, session_key='same-browser-session')
    params = parse_qs(urlparse(authorization_url).query)
    exchange = Mock()
    with patch.object(subscription, '_exchange_code', exchange):
        with pytest.raises(subscription.SubscriptionError, match='浏览器不匹配'):
            subscription.complete_authorization(
                {'state': params['state'][0], 'code': 'mock-code', 'client_id': 'issued-client-id'},
                'different-browser-cookie',
            )
    exchange.assert_not_called()
    with pytest.raises(subscription.SubscriptionError, match='已使用'):
        _handoff(start, session_key='same-browser-session')


def test_login_session_change_cancels_callback_before_code_exchange(user, crypto):
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    with patch.object(subscription, '_discovery', return_value=discovery):
        start = _create_attempt(user, session_key='session-before-switch')
        cookie, url = _handoff(start, session_key='session-before-switch')
    state = parse_qs(urlparse(url).query)['state'][0]
    assert subscription.invalidate_authorization_attempts_for_session('session-before-switch') == 1
    exchange = Mock()
    with patch.object(subscription, '_exchange_code', exchange):
        with pytest.raises(subscription.SubscriptionError, match='取消'):
            subscription.complete_authorization(
                {'state': state, 'code': 'late-code', 'client_id': 'issued-client-id'}, cookie,
            )
    exchange.assert_not_called()
    assert subscription.authorization_attempt_status(user, start['attempt_id'])['status'] == 'cancelled'


def test_explicit_cancel_during_callback_processing_prevents_connection_commit(user, crypto):
    state = 'cancel-while-processing-state'
    attempt = _attempt(user, state, client_id='issued-client-id')
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
    real_decrypt = subscription.decrypt_secret

    def cancel_while_exchanging(*_args, **_kwargs):
        attempt.refresh_from_db()
        assert attempt.status == 'processing'
        assert subscription.cancel_authorization_attempt(user, attempt.pk)
        return token_response

    with (
        patch.object(subscription, '_discovery', return_value=discovery),
        patch.object(
            subscription, 'decrypt_secret',
            side_effect=lambda value, purpose: 'mock-pkce-verifier' if purpose == 'oauth-pkce-verifier' else real_decrypt(value, purpose),
        ),
        patch.object(subscription, '_exchange_code', side_effect=cancel_while_exchanging) as exchange,
        patch.object(subscription, '_verify_id_token', return_value={
            'iss': 'https://auth.example', 'sub': 'cancelled-account', 'name': 'Cancelled account',
        }),
    ):
        with pytest.raises(subscription.SubscriptionError, match='授权请求已取消'):
            subscription.complete_authorization({
                'state': state, 'code': 'mock-code', 'client_id': 'issued-client-id',
            }, 'browser-cookie')

    exchange.assert_called_once()
    attempt.refresh_from_db()
    assert attempt.status == 'cancelled'
    assert not ChatGPTSubscriptionConnection.objects.filter(user=user).exists()


def test_same_subject_under_new_dynamic_registration_creates_distinct_connection(user, crypto):
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    }
    token_response = {
        'access_token': 'access', 'refresh_token': 'refresh', 'id_token': 'id-token',
        'expires_in': 3600, 'scope': f'openid {subscription.REQUIRED_DIRECT_SCOPE}',
    }
    real_decrypt = subscription.decrypt_secret
    connections = []
    with (
        patch.object(subscription, '_discovery', return_value=discovery),
        patch.object(
            subscription, 'decrypt_secret',
            side_effect=lambda value, purpose: 'verifier' if purpose == 'oauth-pkce-verifier' else real_decrypt(value, purpose),
        ),
        patch.object(subscription, '_exchange_code', return_value=token_response),
        patch.object(subscription, '_verify_id_token', return_value={
            'iss': 'https://auth.example', 'sub': 'same-oidc-subject',
        }),
    ):
        for session, actual_client_id in (('browser-a', 'dynamic-client-a'), ('browser-b', 'dynamic-client-b')):
            start = _create_attempt(user, session_key=session)
            cookie, url = _handoff(start, session_key=session)
            state = parse_qs(urlparse(url).query)['state'][0]
            connections.append(subscription.complete_authorization({
                'state': state, 'code': 'mock-code', 'client_id': actual_client_id,
            }, cookie))
    assert connections[0].issued_client_id == 'dynamic-client-a'
    assert connections[1].issued_client_id == 'dynamic-client-b'
    assert connections[0].subject_hash == connections[1].subject_hash
    assert connections[0].registration_key_hash != connections[1].registration_key_hash
    assert ChatGPTSubscriptionConnection.objects.filter(user=user).count() == 2


def test_reconnect_rejects_mismatched_returned_client_id_before_exchange(user, crypto):
    connection = make_connection(user)
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys', 'issuer': 'https://auth.example',
    }
    with patch.object(subscription, '_discovery', return_value=discovery):
        start = _create_attempt(user, target=connection, session_key='reconnect-session')
        cookie, url = _handoff(start, session_key='reconnect-session')
    state = parse_qs(urlparse(url).query)['state'][0]
    exchange = Mock()
    with patch.object(subscription, '_exchange_code', exchange):
        with pytest.raises(subscription.SubscriptionError, match='client_id'):
            subscription.complete_authorization({
                'state': state, 'code': 'mock-code', 'client_id': 'other-client-id',
            }, cookie)
    exchange.assert_not_called()
    assert subscription.authorization_attempt_status(user, start['attempt_id'])['status'] == 'failed'


def test_refresh_uses_per_connection_client_id_and_keeps_saved_scope(user, crypto, transactional_db):
    connection = make_connection(user, client_id='connection-specific-client')
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=1)
    connection.save(update_fields=['access_token_expires_at'])
    response = FakeResponse(payload={'access_token': 'rotated-access', 'refresh_token': 'rotated-refresh', 'expires_in': 1800})
    with (
        patch.object(subscription, '_discovery', return_value={'token_endpoint': 'https://auth.example/token'}),
        patch('api.services.chatgpt_subscription.requests.post', return_value=response) as post,
    ):
        assert subscription._refresh_access_token(connection.pk) == 'rotated-access'
    assert post.call_args.kwargs['data']['client_id'] == 'connection-specific-client'
    connection.refresh_from_db()
    assert subscription.REQUIRED_DIRECT_SCOPE in connection.granted_scopes
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'rotated-refresh'


def test_refresh_token_rotation_survives_account_switch_away_and_back(user, crypto, transactional_db):
    first = make_connection(user, subject='refresh-first')
    second = make_connection(user, subject='refresh-second', active=False)
    first.access_token_expires_at = timezone.now() - timedelta(seconds=1)
    first.save(update_fields=['access_token_expires_at'])
    old_selection_generation = first.generation
    response = FakeResponse(payload={'access_token': 'rotated-access', 'refresh_token': 'rotated-refresh', 'expires_in': 1800})

    def switch_then_refresh(*args, **kwargs):
        subscription.activate_connection(user, second.pk)
        subscription.activate_connection(user, first.pk)
        return response

    with (
        patch.object(subscription, '_discovery', return_value={'token_endpoint': 'https://auth.example/token'}),
        patch('api.services.chatgpt_subscription.requests.post', side_effect=switch_then_refresh),
    ):
        with pytest.raises(subscription.ConnectionChangedError, match='切换或断开'):
            subscription._refresh_access_token(first.pk, old_selection_generation)
    first.refresh_from_db()
    assert first.is_active
    assert first.generation > old_selection_generation
    assert subscription.decrypt_secret(first.encrypted_refresh_token, 'subscription-refresh-token') == 'rotated-refresh'


def test_disconnect_during_refresh_cannot_be_undone_by_late_rotation(user, crypto, transactional_db):
    connection = make_connection(user)
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=1)
    connection.save(update_fields=['access_token_expires_at'])
    refresh_response = FakeResponse(payload={'access_token': 'late-access', 'refresh_token': 'late-refresh', 'expires_in': 1800})

    def disconnect_while_refreshing(*args, **kwargs):
        data = kwargs.get('data', {})
        if data.get('grant_type') == 'refresh_token':
            subscription.disconnect_connection(user, connection.pk)
            return refresh_response
        return FakeResponse(status_code=200)

    with (
        patch.object(subscription, '_discovery', return_value={
            'token_endpoint': 'https://auth.example/token', 'revocation_endpoint': 'https://auth.example/revoke',
        }),
        patch('api.services.chatgpt_subscription.requests.post', side_effect=disconnect_while_refreshing),
    ):
        with pytest.raises(subscription.ConnectionChangedError, match='断开或凭据已更新'):
            subscription._refresh_access_token(connection.pk)
    connection.refresh_from_db()
    assert connection.needs_reauth and not connection.is_active
    assert connection.encrypted_access_token == ''
    assert connection.encrypted_refresh_token == ''


def test_refresh_lease_is_atomic_across_independent_processes(user, crypto, transactional_db, tmp_path):
    connection = make_connection(user)
    database_path = tmp_path / 'refresh-lease.sqlite3'
    source_connection = django_connection.connection
    with sqlite3.connect(database_path) as target_connection:
        source_connection.backup(target_connection)
        target_connection.execute('PRAGMA journal_mode=WAL')
    gate = tmp_path / 'start-processes'
    child_code = r"""
import os, sys, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'newsaggregator.settings')
import django
django.setup()
from django.db import connections
connections.close_all()
connections['default'].settings_dict['NAME'] = sys.argv[1]
# This fixture has already enabled WAL before the concurrent start gate. Avoid
# racing two cold connections on PRAGMA journal_mode; this test is for the
# refresh-lease UPDATE, not SQLite journal initialization.
connections['default'].settings_dict['OPTIONS']['init_command'] = 'PRAGMA foreign_keys=ON;'
from django.utils import timezone
from api.services import chatgpt_subscription as subscription
while not os.path.exists(sys.argv[2]):
    time.sleep(0.01)
result = subscription._acquire_refresh_lease(sys.argv[3], int(sys.argv[4]), timezone.now(), sys.argv[5])
print(int(bool(result)), flush=True)
connections.close_all()
"""
    env = os.environ.copy()
    env['DJANGO_SETTINGS_MODULE'] = 'newsaggregator.settings'
    processes = [
        subprocess.Popen(
            [sys.executable, '-c', child_code, str(database_path), str(gate), str(connection.pk),
             str(connection.credential_generation), f'lease-{index}'],
            cwd=str(Path(__file__).resolve().parents[2]), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for index in range(2)
    ]
    gate.touch()
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        results.append(bool(int(stdout.strip())))
    assert sorted(results) == [False, True]


def test_models_response_requires_official_models_array(user, crypto):
    connection = make_connection(user)
    with (
        patch.object(subscription, 'access_token_for', return_value='mock-access'),
        patch('api.services.chatgpt_subscription.requests.get', return_value=FakeResponse(payload={'data': []})),
    ):
        with pytest.raises(subscription.SubscriptionError, match='models 数组'):
            subscription.discover_models(connection)


def test_disconnect_cancels_targeted_oauth_and_callback_cannot_restore_it(user, crypto):
    connection = make_connection(user)
    discovery = {
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys', 'issuer': 'https://auth.example',
        'revocation_endpoint': 'https://auth.example/revoke',
    }
    with patch.object(subscription, '_discovery', return_value=discovery):
        start = _create_attempt(user, target=connection, session_key='disconnect-session')
        cookie, url = _handoff(start, session_key='disconnect-session')
    state = parse_qs(urlparse(url).query)['state'][0]
    with patch('api.services.chatgpt_subscription.requests.post', return_value=FakeResponse(status_code=200)):
        subscription.disconnect_connection(user, connection.pk)
    exchange = Mock()
    with patch.object(subscription, '_exchange_code', exchange):
        with pytest.raises(subscription.SubscriptionError, match='取消'):
            subscription.complete_authorization({
                'state': state, 'code': 'late-code', 'client_id': connection.issued_client_id,
            }, cookie)
    exchange.assert_not_called()
    connection.refresh_from_db()
    assert connection.encrypted_access_token == '' and connection.encrypted_refresh_token == ''
