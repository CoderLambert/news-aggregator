"""Mock-only coverage for local ChatGPT subscription auth and translation."""

import base64
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.contrib.auth import get_user_model
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


def make_connection(user, *, active=True, subject='provider-subject', generation=0):
    return ChatGPTSubscriptionConnection.objects.create(
        user=user,
        subject_hash=hashlib.sha256(subject.encode()).hexdigest(),
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


def _attempt(user, state, *, expires_at=None, client_id=subscription.DYNAMIC_CLIENT_ID):
    return ChatGPTAuthAttempt.objects.create(
        user=user,
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        nonce_hash=hashlib.sha256(b'nonce').hexdigest(),
        encrypted_pkce_verifier='encrypted-verifier',
        requested_client_id=client_id,
        expires_at=expires_at or (timezone.now() + timedelta(minutes=5)),
    )


def test_callback_rejects_authorization_without_direct_scope(user, crypto):
    state = 'one-use-state'
    _attempt(user, state)
    ChatGPTOAuthClient.objects.create(pk=1, host_id='stable-host-id')
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
            subscription.complete_authorization({'state': state, 'code': 'authorization-code', 'client_id': 'issued-client-id'})
    assert not ChatGPTSubscriptionConnection.objects.filter(user=user).exists()


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
    with (
        patch.object(subscription, '_discovery', return_value=discovery),
        patch.object(subscription, 'decrypt_secret', return_value='mock-pkce-verifier'),
    ):
        authorization_url = subscription.create_authorization_attempt(user)
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
                'sub': 'account-subject', 'name': 'Reader', 'email': 'reader@example.com',
            }),
        ):
            connection = subscription.complete_authorization({
                'state': state, 'code': 'mock-code', 'client_id': 'issued-client-id',
            })
            assert exchange.call_args.args[1] == 'issued-client-id'

    installation = ChatGPTOAuthClient.objects.get(pk=1)
    connection.refresh_from_db()
    assert installation.issued_client_id == 'issued-client-id'
    assert connection.account_name == 'Reader'
    assert connection.account_email == 'reader@example.com'
    assert connection.connected and connection.is_active
    assert subscription.decrypt_secret(connection.encrypted_access_token, 'subscription-access-token') == 'mock-access'
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'mock-refresh'
    with patch.object(subscription, '_discovery', return_value=discovery):
        next_url = subscription.create_authorization_attempt(user)
    next_params = parse_qs(urlparse(next_url).query)
    assert next_params['client_id'] == ['issued-client-id']
    assert 'agent_name_hint' not in next_params


def test_expired_oauth_state_is_rejected(user):
    state = 'expired-state'
    _attempt(user, state, expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(subscription.SubscriptionError, match='已过期'):
        subscription.complete_authorization({'state': state, 'code': 'ignored'})


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


def test_refresh_is_serialized_and_rotates_refresh_token(user, crypto, transactional_db):
    connection = make_connection(user)
    connection.access_token_expires_at = timezone.now() - timedelta(seconds=5)
    connection.save(update_fields=['access_token_expires_at'])
    ChatGPTOAuthClient.objects.create(pk=1, host_id='stable-host-id', issued_client_id='issued-client-id')
    discovery_response = FakeResponse(payload={
        'authorization_endpoint': 'https://auth.example/authorize',
        'token_endpoint': 'https://auth.example/token',
        'jwks_uri': 'https://auth.example/keys',
        'issuer': 'https://auth.example',
    })
    refresh_response = FakeResponse(payload={
        'access_token': 'rotated-access',
        'refresh_token': 'rotated-refresh',
        'expires_in': 3600,
    })
    barrier = threading.Barrier(2)
    original_get = subscription._refresh_access_token
    post_mock = Mock(return_value=refresh_response)
    with (
        patch('api.services.chatgpt_subscription.requests.get', return_value=discovery_response),
        patch('api.services.chatgpt_subscription.requests.post', post_mock),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        futures = [pool.submit(lambda: (barrier.wait(), original_get(connection.pk))[1]) for _ in range(2)]
        assert [future.result(timeout=5) for future in futures] == ['rotated-access', 'rotated-access']
    assert post_mock.call_count == 1
    connection.refresh_from_db()
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'rotated-refresh'


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
    ChatGPTOAuthClient.objects.create(pk=1, host_id='stable-host-id', issued_client_id='issued-client-id')
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
    payload = {'data': [
        {'slug': 'exact-server-slug-v2', 'display_name': 'Visible Model', 'visibility': 'list'},
        {'slug': 'hidden-server-slug', 'display_name': 'Hidden', 'visibility': 'hidden'},
        {'id': 'id-only-entry', 'visibility': 'list'},
    ]}
    with (
        patch.object(subscription, 'access_token_for', return_value='mock-access'),
        patch('api.services.chatgpt_subscription.requests.get', return_value=FakeResponse(payload=payload)),
    ):
        assert subscription.discover_models(connection) == [
            {'slug': 'exact-server-slug-v2', 'display_name': 'Visible Model'},
        ]


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
    assert sent_payload['model'] == 'listed-model-slug'
    assert sent_payload['store'] is False
    assert sent_payload['stream'] is True
    assert sent_payload['input'].endswith(news.full_content)
    if expected_content:
        assert job.error is None
        assert job.result['full_content_zh'] == expected_content
        record = ChatGPTArticleTranslation.objects.get(user=user, connection=connection, news=news)
        assert record.content == expected_content
    else:
        assert expected_error in job.error
        assert ChatGPTArticleTranslation.objects.filter(user=user, connection=connection, news=news).count() == 0
