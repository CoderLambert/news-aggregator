"""Website SIWC adaptation: offline tests only, never call real OpenAI."""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Category, ChatGPTSubscriptionConnection, ChatGPTAuthAttempt,
    News, Source, UserNewsChatSession,
)
from api.services import chatgpt_subscription as subscription
from api.services.siwc_modes import SiwcConfigError, load_siwc_config

ORIGIN = 'https://news.lambert.host'
CALLBACK = ORIGIN + '/api/chatgpt-subscription/callback/'
CLIENT_ID = 'oaiapp_website_test'


@pytest.fixture
def website(settings, monkeypatch):
    settings.CHATGPT_SIWC_MODE = 'website'
    settings.CHATGPT_WEBSITE_PARTNER_APPROVED = True
    settings.CHATGPT_WEBSITE_APPROVAL_REFERENCE = 'example-written-approval-only'
    settings.CHATGPT_WEBSITE_ORIGIN = ORIGIN
    settings.CHATGPT_WEBSITE_CLIENT_ID = CLIENT_ID
    settings.CHATGPT_WEBSITE_CLIENT_SECRET = ''
    settings.CHATGPT_WEBSITE_REDIRECT_URI = CALLBACK
    settings.CHATGPT_WEBSITE_TOKEN_AUTH_METHOD = 'none'
    settings.CHATGPT_WEBSITE_SCOPES = (
        'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
    )
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ['testserver', 'news.lambert.host']
    settings.CORS_ALLOW_ALL_ORIGINS = False
    settings.CSRF_TRUSTED_ORIGINS = [ORIGIN]
    settings.CHATGPT_HANDOFF_ALLOWED_ORIGINS = [ORIGIN]
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    monkeypatch.setattr(subscription, '_encryption_key', lambda: b'x' * 32)
    return settings


@pytest.fixture
def discovery():
    return {
        'authorization_endpoint': 'https://auth.openai.com/api/accounts/authorize',
        'token_endpoint': 'https://auth.openai.com/api/accounts/oauth/token',
        'jwks_uri': 'https://auth.openai.com/.well-known/jwks.json',
        'issuer': 'https://auth.openai.com',
    }


def user_for(name):
    return get_user_model().objects.create_user(username=name, password='not-used')


def begin(user, key, discovery):
    with patch.object(subscription, '_discovery', return_value=discovery):
        started = subscription.create_authorization_attempt(user, session_key=key, origin=ORIGIN)
        browser_cookie, url = subscription.handoff_authorization(
            started['attempt_id'], started['handoff_token'],
            session_key=key, origin=ORIGIN,
        )
    return started, browser_cookie, parse_qs(urlparse(url).query)


@pytest.mark.django_db
def test_website_mode_refuses_missing_approval_even_with_client_id(website):
    website.CHATGPT_WEBSITE_PARTNER_APPROVED = False
    with pytest.raises(SiwcConfigError, match='明确托管授权'):
        load_siwc_config()
    client = APIClient()
    client.force_authenticate(user=user_for('disabled-user'))
    response = client.get('/api/chatgpt-subscription/')
    assert response.status_code == 200
    assert response.data['available'] is False
    assert response.data['connections'] == []
    denied = client.post('/api/chatgpt-subscription/connect/', {}, format='json', HTTP_ORIGIN=ORIGIN)
    assert denied.status_code == 400
    assert not ChatGPTAuthAttempt.objects.exists()


@pytest.mark.django_db
def test_website_start_uses_fixed_client_https_pkce_and_no_dynamic_host(website, discovery):
    user = user_for('fixed-client')
    started, cookie, params = begin(user, 'website-session', discovery)
    assert cookie
    assert started['handoff_url'] == ORIGIN + '/api/chatgpt-subscription/handoff/'
    assert params['client_id'] == [CLIENT_ID]
    assert params['redirect_uri'] == [CALLBACK]
    assert params['code_challenge_method'] == ['S256']
    assert subscription.REQUIRED_DIRECT_SCOPE in params['scope'][0].split()
    assert 'ext_agent_host_id' not in params
    assert 'agent_name_hint' not in params
    assert 'id_token_hint' not in params
    attempt = ChatGPTAuthAttempt.objects.get(pk=started['attempt_id'])
    assert attempt.oauth_mode == 'website'
    assert attempt.redirect_uri == CALLBACK
    assert attempt.token_auth_method == 'none'


@pytest.mark.django_db
def test_website_handoff_cookie_is_secure_and_browser_bound(website, discovery):
    user = user_for('cookie-user')
    client = APIClient()
    client.force_authenticate(user=user)
    with patch.object(subscription, '_discovery', return_value=discovery):
        started = client.post(
            '/api/chatgpt-subscription/connect/', {}, format='json', HTTP_ORIGIN=ORIGIN,
        )
    assert started.status_code == 201
    other = APIClient()
    stolen = other.post(
        '/api/chatgpt-subscription/handoff/',
        {'attempt_id': started.data['attempt_id'], 'handoff_token': started.data['handoff_token']},
        format='json', HTTP_ORIGIN=ORIGIN,
    )
    assert stolen.status_code == 400
    handoff = client.post(
        '/api/chatgpt-subscription/handoff/',
        {'attempt_id': started.data['attempt_id'], 'handoff_token': started.data['handoff_token']},
        format='json', HTTP_ORIGIN=ORIGIN,
    )
    assert handoff.status_code == 302
    assert handoff.cookies[subscription.BINDING_COOKIE_NAME]['secure']
    assert handoff.cookies[subscription.BINDING_COOKIE_NAME]['httponly']
    assert handoff.cookies[subscription.BINDING_COOKIE_NAME]['path'] == subscription.BINDING_COOKIE_PATH


@pytest.mark.django_db
def test_website_users_keep_separate_tokens_under_same_client(website, discovery):
    users = [user_for('website-user-a'), user_for('website-user-b')]
    output = []
    for index, user in enumerate(users):
        _, cookie, params = begin(user, f'website-session-{index}', discovery)
        subject = f'chatgpt-subject-{index}'
        token_response = {
            'access_token': f'access-{index}',
            'refresh_token': f'refresh-{index}',
            'id_token': 'mock-id-token',
            'expires_in': 3600,
            'scope': website.CHATGPT_WEBSITE_SCOPES,
        }
        with (
            patch.object(subscription, '_discovery', return_value=discovery),
            patch.object(subscription, '_exchange_code', return_value=token_response) as exchange,
            patch.object(subscription, '_verify_id_token', return_value={
                'iss': discovery['issuer'], 'sub': subject, 'name': subject,
            }),
        ):
            connection = subscription.complete_authorization({
                'state': params['state'][0], 'code': 'fake-code', 'client_id': CLIENT_ID,
            }, cookie)
            assert exchange.call_args.kwargs['redirect_uri'] == CALLBACK
        output.append(connection)
    assert len({connection.user_id for connection in output}) == 2
    assert all(connection.issued_client_id == CLIENT_ID for connection in output)
    assert all(connection.oauth_mode == 'website' for connection in output)
    assert output[0].registration_key_hash != output[1].registration_key_hash
    assert subscription.decrypt_secret(output[0].encrypted_access_token, 'subscription-access-token') == 'access-0'
    assert subscription.decrypt_secret(output[1].encrypted_access_token, 'subscription-access-token') == 'access-1'
    with pytest.raises(subscription.SubscriptionError, match='不存在'):
        subscription.get_user_connection(users[0], output[1].pk)
    assert subscription.active_connection_for_user(users[0]).pk == output[0].pk


@pytest.mark.django_db
def test_callback_fails_if_client_configuration_changes_midflight(website, discovery):
    user = user_for('midflight-change')
    _, cookie, params = begin(user, 'website-midflight', discovery)
    website.CHATGPT_WEBSITE_CLIENT_ID = 'oaiapp_another_approved_client'
    with patch.object(subscription, '_exchange_code') as exchange:
        with pytest.raises(subscription.SubscriptionError, match='Client ID'):
            subscription.complete_authorization({
                'state': params['state'][0], 'code': 'fake-code',
            }, cookie)
    exchange.assert_not_called()
    assert not ChatGPTSubscriptionConnection.objects.exists()


@pytest.mark.django_db
def test_old_local_registration_never_becomes_website_connection(website):
    user = user_for('legacy-user')
    legacy = ChatGPTSubscriptionConnection.objects.create(
        user=user, oauth_mode='local', subject_hash='s' * 64,
        issuer='https://auth.openai.com', issued_client_id='oaiapp_old_local',
        registration_key_hash='r' * 64,
        is_active=True,
    )
    assert subscription.active_connection_for_user(user) is None
    with pytest.raises(subscription.SubscriptionError, match='不存在'):
        subscription.get_user_connection(user, legacy.pk)


def test_website_rejects_identity_only_scopes_or_insecure_redirect(website):
    website.CHATGPT_WEBSITE_SCOPES = 'openid profile email'
    with pytest.raises(SiwcConfigError, match='订阅模型'):
        load_siwc_config()
    website.CHATGPT_WEBSITE_SCOPES = (
        'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
    )
    website.CHATGPT_WEBSITE_REDIRECT_URI = 'http://127.0.0.1:9527/api/chatgpt-subscription/callback/'
    with pytest.raises(SiwcConfigError, match='HTTPS'):
        load_siwc_config()


def test_confidential_website_client_uses_basic_and_never_logs_secret(website):
    website.CHATGPT_WEBSITE_TOKEN_AUTH_METHOD = 'client_secret_basic'
    website.CHATGPT_WEBSITE_CLIENT_SECRET = 'not-a-real-secret'
    config = load_siwc_config()

    class FakeResponse:
        status_code = 200
        def json(self):
            return {'id_token': 'test-token'}

    with patch.object(subscription.requests, 'post', return_value=FakeResponse()) as post:
        subscription._exchange_code(
            'fake-code', config.client_id, 'verifier',
            'https://auth.openai.com/api/accounts/oauth/token',
            redirect_uri=config.redirect_uri, token_auth_method=config.token_auth_method,
            client_secret=config.client_secret, resource=config.resource,
        )
    auth = post.call_args.kwargs['headers']['Authorization']
    assert auth.startswith('Basic ')
    assert config.client_secret not in post.call_args.kwargs['data']
    assert post.call_args.kwargs['data']['redirect_uri'] == CALLBACK


@pytest.mark.django_db
def test_website_refresh_reauthenticates_using_the_approved_client(website, discovery):
    website.CHATGPT_WEBSITE_TOKEN_AUTH_METHOD = 'client_secret_basic'
    website.CHATGPT_WEBSITE_CLIENT_SECRET = 'not-a-real-secret'
    user = user_for('refresh-website')
    connection = ChatGPTSubscriptionConnection.objects.create(
        user=user, oauth_mode='website', subject_hash='s' * 64,
        issuer='https://auth.openai.com', issued_client_id=CLIENT_ID,
        registration_key_hash='r' * 64, is_active=True,
        encrypted_access_token=subscription.encrypt_secret('expired', 'subscription-access-token'),
        encrypted_refresh_token=subscription.encrypt_secret('refresh', 'subscription-refresh-token'),
        access_token_expires_at=timezone.now() - timedelta(seconds=10),
        granted_scopes=website.CHATGPT_WEBSITE_SCOPES.split(),
    )

    class FakeResponse:
        status_code = 200
        def json(self):
            return {'access_token': 'renewed', 'expires_in': 3600, 'refresh_token': 'rotated'}

    with (
        patch.object(subscription, '_discovery', return_value=discovery),
        patch.object(subscription.requests, 'post', return_value=FakeResponse()) as post,
    ):
        assert subscription._refresh_access_token(connection.pk) == 'renewed'
    assert post.call_args.kwargs['headers']['Authorization'].startswith('Basic ')
    assert post.call_args.kwargs['data']['client_id'] == CLIENT_ID
    connection.refresh_from_db()
    assert subscription.decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token') == 'rotated'


@pytest.mark.django_db
def test_website_article_chat_history_is_private_and_no_key_fallback(website):
    category = Category.objects.create(name='Web privacy', slug='web-privacy')
    source = Source.objects.create(
        name='Source Web', url='https://example.com', language='en',
    )
    news = News.objects.create(
        title='Article', content='Article body', url='https://example.com/a',
        source=source, category=category, publish_time=timezone.now(),
    )
    alice = user_for('chat-alice')
    bob = user_for('chat-bob')
    UserNewsChatSession.objects.create(
        news=news, user=alice,
        messages=[{'role': 'user', 'content': 'Alice private question'}],
    )
    path = f'/api/news/{news.pk}/chat/'
    a = APIClient()
    a.force_authenticate(user=alice)
    b = APIClient()
    b.force_authenticate(user=bob)
    assert a.get(path).data['messages'][0]['content'] == 'Alice private question'
    assert b.get(path).data['messages'] == []
    assert APIClient().get(path).status_code == 401
    assert b.delete(path).status_code == 200
    assert UserNewsChatSession.objects.filter(user=alice, news=news).exists()
    # Without the user's own SIWC connection the API must NOT call its
    # ordinary server-paid streaming provider.
    with patch('api.views.stream_chat') as paid_llm:
        denied = b.post(path, {'question': 'Explain this'}, format='json')
    assert denied.status_code == 403
    paid_llm.assert_not_called()


@pytest.mark.django_db
def test_hosted_chatgpt_identity_cannot_be_shared_across_site_users(website, discovery):
    alice = user_for('owner-alice')
    bob = user_for('owner-bob')
    tokens = {
        'access_token': 'a', 'refresh_token': 'r', 'id_token': 'signed',
        'expires_in': 1800, 'scope': website.CHATGPT_WEBSITE_SCOPES,
    }
    for index, user in enumerate((alice, bob)):
        _, cookie, params = begin(user, f'shared-login-{index}', discovery)
        with (
            patch.object(subscription, '_discovery', return_value=discovery),
            patch.object(subscription, '_exchange_code', return_value=tokens),
            patch.object(subscription, '_verify_id_token', return_value={
                'iss': discovery['issuer'], 'sub': 'same-ChatGPT-user',
            }),
        ):
            if index == 0:
                subscription.complete_authorization({
                    'state': params['state'][0], 'code': 'fake',
                }, cookie)
            else:
                with pytest.raises(subscription.SubscriptionError, match='其他网站账号'):
                    subscription.complete_authorization({
                        'state': params['state'][0], 'code': 'fake',
                    }, cookie)
    assert ChatGPTSubscriptionConnection.objects.filter(oauth_mode='website').count() == 1


@pytest.mark.django_db
def test_website_translation_does_not_use_admin_provider_without_subscription(website):
    category = Category.objects.create(name='No fallback', slug='no-fallback')
    source = Source.objects.create(name='No fallback source', url='https://test.example', language='en')
    news = News.objects.create(
        title='No fallback', content='Body', url='https://test.example/a',
        source=source, category=category, publish_time=timezone.now(),
        full_content='# Original article',
    )
    client = APIClient()
    client.force_authenticate(user=user_for('translation-no-fallback'))
    with patch('api.views.get_clients') as paid_clients:
        response = client.post(f'/api/news/{news.pk}/translate/', {}, format='json')
        assert response.status_code == 200
        result = b''.join(response.streaming_content).decode('utf-8')
    assert '请先登录并连接 ChatGPT 订阅账号' in result
    paid_clients.assert_not_called()
