"""Local, user-bound ChatGPT subscription OAuth and Responses API integration.

Only server-side code sees subscription tokens. OAuth client registration,
refresh rotation, model discovery, and response streaming use the public SIWC
and Responses endpoints; no ChatGPT web/private endpoints are called.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import secrets
import threading
import time
import uuid
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from api.models import (
    ChatGPTArticleTranslation,
    ChatGPTAuthAttempt,
    ChatGPTOAuthClient,
    ChatGPTSubscriptionConnection,
)

logger = logging.getLogger(__name__)

DISCOVERY_URL = 'https://auth.openai.com/.well-known/openid-configuration'
REDIRECT_URI = 'http://127.0.0.1:9527/api/chatgpt-subscription/callback/'
HANDOFF_URI = 'http://127.0.0.1:9527/api/chatgpt-subscription/handoff/'
BINDING_COOKIE_NAME = 'chatgpt_oauth_binding'
BINDING_COOKIE_PATH = '/api/chatgpt-subscription/callback/'
API_RESOURCE = 'https://api.openai.com/v1'
MODELS_URL = f'{API_RESOURCE}/models'
RESPONSES_URL = f'{API_RESOURCE}/responses'
DYNAMIC_CLIENT_ID = 'dynamic_agent_client'
REQUIRED_DIRECT_SCOPE = 'chatgpt.tokens.use.direct'
REQUESTED_SCOPES = (
    'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
)
AUTH_ATTEMPT_TTL = timedelta(minutes=10)
REFRESH_LEASE_TTL = timedelta(seconds=35)
REFRESH_WAIT_SECONDS = 40


class SubscriptionError(Exception):
    """Safe-to-display subscription flow error."""


class ConnectionChangedError(SubscriptionError):
    pass


_USER_LOCKS: dict[int, threading.RLock] = {}
_USER_LOCKS_GUARD = threading.Lock()


def _user_lock(user_id) -> threading.RLock:
    key = int(user_id)
    with _USER_LOCKS_GUARD:
        return _USER_LOCKS.setdefault(key, threading.RLock())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def _encryption_key() -> bytes:
    material = getattr(settings, 'CHATGPT_TOKEN_ENCRYPTION_KEY', '')
    if not material:
        raise SubscriptionError('服务端缺少稳定的订阅凭据加密密钥。')
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'news-aggregator-chatgpt-subscription-v1',
        info=b'oauth-token-encryption',
    ).derive(material.encode('utf-8'))


def encrypt_secret(value: str, purpose: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(nonce, value.encode('utf-8'), purpose.encode('utf-8'))
    return _b64url(nonce + ciphertext)


def decrypt_secret(value: str, purpose: str) -> str:
    try:
        raw = _b64url_decode(value)
        plaintext = AESGCM(_encryption_key()).decrypt(raw[:12], raw[12:], purpose.encode('utf-8'))
        return plaintext.decode('utf-8')
    except Exception as exc:
        raise SubscriptionError('本地订阅凭据无法解密，请重新连接账号。') from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _subject_hash(subject: str) -> str:
    return hmac.new(_encryption_key(), subject.encode('utf-8'), hashlib.sha256).hexdigest()


def _registration_key_hash(issuer: str, client_id: str, host_id: str, subject: str) -> str:
    material = '\0'.join((issuer, client_id, host_id, subject)).encode('utf-8')
    return hmac.new(_encryption_key(), material, hashlib.sha256).hexdigest()


def _session_binding_hash(session_key: str) -> str:
    if not session_key:
        return ''
    return hmac.new(
        str(settings.SECRET_KEY).encode('utf-8'),
        b'local-session\0' + session_key.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _validate_handoff_origin(origin: str) -> str:
    allowed_origins = getattr(settings, 'CHATGPT_HANDOFF_ALLOWED_ORIGINS', ())
    if not isinstance(origin, str) or not origin or origin not in allowed_origins:
        raise SubscriptionError('请从 http://127.0.0.1:5173 打开本地应用，再开始订阅连接。')
    return origin


def _parse_granted_scopes(value) -> set[str]:
    if isinstance(value, str):
        return set(value.split())
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return set(value)
    return set()


def source_hash(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_installation_client() -> ChatGPTOAuthClient:
    client, _ = ChatGPTOAuthClient.objects.get_or_create(pk=1)
    return client


def _discovery() -> dict:
    try:
        response = requests.get(DISCOVERY_URL, timeout=10)
        if response.status_code != 200:
            raise SubscriptionError('无法读取 OpenAI 登录服务配置。')
        data = response.json()
    except SubscriptionError:
        raise
    except Exception as exc:
        raise SubscriptionError('暂时无法连接 OpenAI 登录服务。') from exc
    if not isinstance(data, dict):
        raise SubscriptionError('OpenAI 登录服务返回了无效配置。')
    for key in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
        parsed = urlparse(str(data.get(key, '')))
        if parsed.scheme != 'https' or not parsed.netloc:
            raise SubscriptionError('OpenAI 登录服务配置缺少有效 HTTPS 端点。')
    return data


def create_authorization_attempt(user, target_connection=None, session_key='', origin='') -> dict[str, str]:
    if target_connection is not None and target_connection.user_id != user.pk:
        raise SubscriptionError('不能操作其他用户的订阅连接。')
    if not session_key:
        raise SubscriptionError('请先登录本地账号后再连接 ChatGPT 订阅。')
    handoff_origin = _validate_handoff_origin(origin)
    discovery = _discovery()
    installation = get_installation_client()
    handoff_token = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    session_hash = _session_binding_hash(session_key)

    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        ChatGPTAuthAttempt.objects.filter(
            session_binding_hash=session_hash, status__in=['pending', 'authorizing', 'processing'],
        ).update(status='cancelled', status_message='新的连接请求已取代此请求。')
        current_target = None
        target_attempt_generation = 0
        if target_connection is not None:
            current_target = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                pk=target_connection.pk, user=user,
            ).first()
            if current_target is None:
                raise SubscriptionError('待重新连接的账号已不存在。')
            current_target.auth_attempt_generation += 1
            current_target.save(update_fields=['auth_attempt_generation', 'updated_at'])
            target_attempt_generation = current_target.auth_attempt_generation
            ChatGPTAuthAttempt.objects.filter(
                target_connection=current_target, status__in=['pending', 'authorizing', 'processing'],
            ).update(status='cancelled', status_message='此连接已开始新的授权请求。')
            requested_client_id = current_target.issued_client_id or DYNAMIC_CLIENT_ID
        else:
            requested_client_id = DYNAMIC_CLIENT_ID

        active_selection = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
            user=user, is_active=True,
        ).first()
        selection_connection_id = active_selection.pk if active_selection else None
        selection_generation = active_selection.generation if active_selection else 0

        params = {
            'response_type': 'code', 'client_id': requested_client_id, 'redirect_uri': REDIRECT_URI,
            'scope': REQUESTED_SCOPES, 'resource': API_RESOURCE, 'state': state, 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256',
            'ext_agent_host_id': installation.host_id,
        }
        if requested_client_id == DYNAMIC_CLIENT_ID:
            params['agent_name_hint'] = getattr(settings, 'CHATGPT_AGENT_NAME_HINT', 'News Aggregator')
        authorization_url = f"{discovery['authorization_endpoint']}?{urlencode(params)}"
        attempt = ChatGPTAuthAttempt.objects.create(
            user=user, target_connection=current_target, state_hash=_digest(state), nonce_hash=_digest(nonce),
            encrypted_pkce_verifier=encrypt_secret(verifier, 'oauth-pkce-verifier'),
            encrypted_authorization_url=encrypt_secret(authorization_url, 'oauth-authorization-url'),
            handoff_token_hash=_digest(handoff_token), session_binding_hash=session_hash,
            handoff_origin=handoff_origin,
            requested_client_id=requested_client_id, target_attempt_generation=target_attempt_generation,
            selection_connection_id_at_start=selection_connection_id,
            selection_generation_at_start=selection_generation,
            expires_at=timezone.now() + AUTH_ATTEMPT_TTL,
        )
    return {'attempt_id': str(attempt.pk), 'handoff_token': handoff_token, 'handoff_url': HANDOFF_URI}


def handoff_authorization(
    attempt_id: str, handoff_token: str, *, session_key: str, origin: str,
) -> tuple[str, str]:
    if not isinstance(session_key, str) or not session_key:
        raise SubscriptionError('本地登录状态已切换，请重新连接。')
    session_hash = _session_binding_hash(session_key)
    handoff_origin = _validate_handoff_origin(origin)
    if not isinstance(handoff_token, str) or not handoff_token:
        raise SubscriptionError('授权窗口校验失败，请重新连接。')
    now = timezone.now()
    browser_cookie = secrets.token_urlsafe(32)
    try:
        attempt = ChatGPTAuthAttempt.objects.get(pk=attempt_id)
        if (
            not hmac.compare_digest(attempt.session_binding_hash, session_hash) or
            not hmac.compare_digest(attempt.handoff_origin, handoff_origin)
        ):
            raise SubscriptionError('本地登录状态已切换，请从原始窗口重新连接。')
        if attempt.expires_at <= now:
            ChatGPTAuthAttempt.objects.filter(
                pk=attempt.pk, status='pending', expires_at__lte=now,
            ).update(status='failed', status_message='登录请求已过期，请重新连接。')
            raise SubscriptionError('登录请求已过期，请重新连接。')
        with transaction.atomic():
            updated = ChatGPTAuthAttempt.objects.filter(
                pk=attempt.pk, handoff_token_hash=_digest(handoff_token),
                session_binding_hash=session_hash, handoff_origin=handoff_origin,
                status='pending', expires_at__gt=now,
            ).update(
                handoff_token_hash='', browser_binding_hash=_digest(browser_cookie), status='authorizing',
            )
            if not updated:
                raise SubscriptionError('授权窗口校验失败或请求已使用。')
            authorization_url = decrypt_secret(attempt.encrypted_authorization_url, 'oauth-authorization-url')
        return browser_cookie, authorization_url
    except ChatGPTAuthAttempt.DoesNotExist as exc:
        raise SubscriptionError('登录请求不存在或已过期。') from exc
    except (TypeError, ValueError) as exc:
        raise SubscriptionError('登录请求不存在或已过期。') from exc


def _finish_attempt(attempt_id, status_value, message, connection=None):
    values = {'status': status_value, 'status_message': message[:255]}
    if connection is not None:
        values['result_connection'] = connection
    ChatGPTAuthAttempt.objects.filter(pk=attempt_id, status='processing').update(**values)


def cancel_authorization_attempt(user, attempt_id) -> bool:
    return bool(ChatGPTAuthAttempt.objects.filter(
        pk=attempt_id, user=user, status__in=['pending', 'authorizing', 'processing'],
    ).update(status='cancelled', status_message='授权请求已取消。'))


def invalidate_authorization_attempts_for_session(session_key: str) -> int:
    session_hash = _session_binding_hash(session_key)
    if not session_hash:
        return 0
    return ChatGPTAuthAttempt.objects.filter(
        session_binding_hash=session_hash, status__in=['pending', 'authorizing', 'processing'],
    ).update(status='cancelled', status_message='本地登录状态已切换，请重新连接。')


def authorization_attempt_status(user, attempt_id) -> dict[str, str | None]:
    try:
        attempt = ChatGPTAuthAttempt.objects.get(pk=attempt_id, user=user)
    except (ChatGPTAuthAttempt.DoesNotExist, ValueError, TypeError) as exc:
        raise SubscriptionError('授权请求不存在。') from exc
    if attempt.status in ('pending', 'authorizing', 'processing') and attempt.expires_at <= timezone.now():
        ChatGPTAuthAttempt.objects.filter(
            pk=attempt.pk, status__in=['pending', 'authorizing', 'processing'],
        ).update(status='failed', status_message='登录请求已过期，请重新连接。')
        attempt.refresh_from_db()
    return {
        'id': str(attempt.pk), 'status': attempt.status, 'message': attempt.status_message,
        'connection_id': str(attempt.result_connection_id) if attempt.result_connection_id else None,
    }


def _verify_id_token(id_token: str, client_id: str, nonce_hash: str, discovery: dict) -> dict:
    try:
        encoded_header, encoded_claims, encoded_signature = id_token.split('.')
        header = json.loads(_b64url_decode(encoded_header))
        claims = json.loads(_b64url_decode(encoded_claims))
        signature = _b64url_decode(encoded_signature)
    except Exception as exc:
        raise SubscriptionError('OpenAI 登录返回了格式无效的 ID token。') from exc

    algorithm = header.get('alg')
    if algorithm not in ('RS256', 'ES256') or not isinstance(header.get('kid'), str):
        raise SubscriptionError('OpenAI ID token 使用了不支持的签名算法。')
    try:
        response = requests.get(discovery['jwks_uri'], timeout=10)
        if response.status_code != 200:
            raise SubscriptionError('无法验证 OpenAI 登录签名。')
        jwks = response.json().get('keys', [])
    except SubscriptionError:
        raise
    except Exception as exc:
        raise SubscriptionError('暂时无法读取 OpenAI 登录签名密钥。') from exc
    jwk = next((key for key in jwks if key.get('kid') == header['kid']), None)
    if not isinstance(jwk, dict):
        raise SubscriptionError('OpenAI 登录签名密钥未找到。')
    if jwk.get('use') not in (None, 'sig') or jwk.get('alg') not in (None, algorithm):
        raise SubscriptionError('OpenAI 登录签名密钥用途无效。')

    signed = f'{encoded_header}.{encoded_claims}'.encode('ascii')
    try:
        if algorithm == 'RS256' and jwk.get('kty') == 'RSA':
            numbers = rsa.RSAPublicNumbers(
                int.from_bytes(_b64url_decode(jwk['e']), 'big'),
                int.from_bytes(_b64url_decode(jwk['n']), 'big'),
            )
            numbers.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        elif algorithm == 'ES256' and jwk.get('kty') == 'EC' and jwk.get('crv') == 'P-256':
            public_key = ec.EllipticCurvePublicNumbers(
                int.from_bytes(_b64url_decode(jwk['x']), 'big'),
                int.from_bytes(_b64url_decode(jwk['y']), 'big'),
                ec.SECP256R1(),
            ).public_key()
            if len(signature) != 64:
                raise ValueError('Invalid ES256 signature length')
            der_signature = utils.encode_dss_signature(
                int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big'),
            )
            public_key.verify(der_signature, signed, ec.ECDSA(hashes.SHA256()))
        else:
            raise SubscriptionError('OpenAI 登录签名密钥类型不匹配。')
    except SubscriptionError:
        raise
    except Exception as exc:
        raise SubscriptionError('OpenAI ID token 签名验证失败。') from exc

    now = timezone.now().timestamp()
    issuer = discovery.get('issuer')
    audience = claims.get('aud')
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(issuer, str) or claims.get('iss') != issuer:
        raise SubscriptionError('OpenAI ID token issuer 不匹配。')
    if not isinstance(audiences, list) or client_id not in audiences:
        raise SubscriptionError('OpenAI ID token audience 不匹配。')
    if len(audiences) > 1 and claims.get('azp') != client_id:
        raise SubscriptionError('OpenAI ID token authorized party 不匹配。')
    if (not isinstance(claims.get('exp'), (int, float)) or not math.isfinite(claims['exp'])
            or now >= claims['exp']):
        raise SubscriptionError('OpenAI ID token 已过期。')
    if 'nbf' in claims and (not isinstance(claims['nbf'], (int, float)) or isinstance(claims['nbf'], bool)
                            or not math.isfinite(claims['nbf']) or claims['nbf'] > now + 60):
        raise SubscriptionError('OpenAI ID token 尚未生效。')
    if 'iat' in claims and (not isinstance(claims['iat'], (int, float)) or isinstance(claims['iat'], bool)
                            or not math.isfinite(claims['iat']) or claims['iat'] > now + 60):
        raise SubscriptionError('OpenAI ID token 签发时间无效。')
    subject = claims.get('sub')
    nonce = claims.get('nonce')
    if not isinstance(subject, str) or not subject or not isinstance(nonce, str):
        raise SubscriptionError('OpenAI ID token 缺少用户或 nonce。')
    if not hmac.compare_digest(hashlib.sha256(nonce.encode('utf-8')).hexdigest(), nonce_hash):
        raise SubscriptionError('OpenAI ID token nonce 不匹配。')
    return claims


def _consume_attempt(state: str, browser_binding_token: str) -> ChatGPTAuthAttempt:
    if not isinstance(browser_binding_token, str) or not browser_binding_token:
        raise SubscriptionError('授权窗口校验失败，请从原页面重新连接。')
    state_hash = _digest(state)
    binding_hash = _digest(browser_binding_token)
    now = timezone.now()
    try:
        attempt = ChatGPTAuthAttempt.objects.get(state_hash=state_hash)
    except ChatGPTAuthAttempt.DoesNotExist as exc:
        raise SubscriptionError('登录状态无效或已使用。') from exc
    if attempt.expires_at <= now:
        ChatGPTAuthAttempt.objects.filter(
            pk=attempt.pk, status__in=['pending', 'authorizing', 'processing'], expires_at__lte=now,
        ).update(status='failed', status_message='登录请求已过期，请重新连接。')
        raise SubscriptionError('登录请求已过期，请重新连接。')
    if not hmac.compare_digest(attempt.browser_binding_hash, binding_hash):
        raise SubscriptionError('授权窗口与发起连接的浏览器不匹配。')
    with transaction.atomic():
        updated = ChatGPTAuthAttempt.objects.filter(
            pk=attempt.pk, status='authorizing', browser_binding_hash=binding_hash, expires_at__gt=now,
        ).update(status='processing', consumed_at=now)
        if not updated:
            raise SubscriptionError('登录状态无效、已使用或已取消。')
        attempt.status = 'processing'
        attempt.consumed_at = now
        return attempt


def _exchange_code(code: str, client_id: str, verifier: str, token_endpoint: str) -> dict:
    try:
        response = requests.post(token_endpoint, data={
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI,
            'client_id': client_id, 'code_verifier': verifier, 'resource': API_RESOURCE,
        }, timeout=20)
    except Exception as exc:
        raise SubscriptionError('连接 OpenAI 登录服务失败，请稍后重试。') from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise SubscriptionError('OpenAI 未完成订阅授权，请重新连接。')
    try:
        payload = response.json()
    except Exception as exc:
        raise SubscriptionError('OpenAI 登录服务返回了无效令牌响应。') from exc
    if not isinstance(payload, dict):
        raise SubscriptionError('OpenAI 登录服务返回了无效令牌响应。')
    return payload


def complete_authorization(query, browser_binding_token: str) -> ChatGPTSubscriptionConnection:
    state = query.get('state', '')
    if not state:
        raise SubscriptionError('登录状态缺失，请重新连接。')
    attempt = _consume_attempt(state, browser_binding_token)
    try:
        if query.get('error'):
            _finish_attempt(attempt.pk, 'cancelled', '你取消了 ChatGPT 订阅授权。')
            raise SubscriptionError('你取消了 ChatGPT 订阅授权。')
        code = query.get('code', '')
        if not code:
            raise SubscriptionError('OpenAI 登录回调缺少授权码。')
        installation = get_installation_client()
        returned_client_id = query.get('client_id', '')
        if attempt.requested_client_id == DYNAMIC_CLIENT_ID:
            if not isinstance(returned_client_id, str) or not returned_client_id or returned_client_id == DYNAMIC_CLIENT_ID:
                raise SubscriptionError('首次注册没有返回 OpenAI client_id。')
            client_id = returned_client_id
        else:
            client_id = attempt.requested_client_id
            if returned_client_id and returned_client_id != client_id:
                raise SubscriptionError('OpenAI 返回的 client_id 与此连接的注册不一致。')
        discovery = _discovery()
        verifier = decrypt_secret(attempt.encrypted_pkce_verifier, 'oauth-pkce-verifier')
        token_payload = _exchange_code(code, client_id, verifier, discovery['token_endpoint'])
        access_token = token_payload.get('access_token')
        refresh_token = token_payload.get('refresh_token')
        id_token = token_payload.get('id_token')
        expires_in = token_payload.get('expires_in')
        if not all(isinstance(value, str) and value for value in (access_token, refresh_token, id_token)):
            raise SubscriptionError('授权响应缺少 access、refresh 或 ID token。')
        if (not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool)
                or not math.isfinite(expires_in) or expires_in <= 0):
            raise SubscriptionError('授权响应中的 access token 有效期无效。')
        claims = _verify_id_token(id_token, client_id, attempt.nonce_hash, discovery)
        granted_scopes = _parse_granted_scopes(token_payload.get('scope'))
        if REQUIRED_DIRECT_SCOPE not in granted_scopes:
            raise SubscriptionError('订阅未授予 direct model access 权限，请重新授权并允许该权限。')
        subject = claims['sub']
        issuer = claims['iss']
        registration_key = _registration_key_hash(issuer, client_id, installation.host_id, subject)
        now = timezone.now()
        with transaction.atomic():
            locked_attempt = ChatGPTAuthAttempt.objects.select_for_update().filter(
                pk=attempt.pk, status='processing', expires_at__gt=now,
            ).first()
            if locked_attempt is None:
                raise SubscriptionError('本地登录状态已切换或授权请求已取消。')
            get_user_model().objects.select_for_update().get(pk=locked_attempt.user_id)
            target = None
            if locked_attempt.target_connection_id:
                target = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                    pk=locked_attempt.target_connection_id, user=locked_attempt.user,
                ).first()
                if target is None:
                    raise SubscriptionError('待重新连接的账号已不存在。')
                if target.auth_attempt_generation != locked_attempt.target_attempt_generation:
                    raise SubscriptionError('此授权窗口已过期，请从当前连接重新开始。')
                if target.registration_key_hash and target.registration_key_hash != registration_key:
                    raise SubscriptionError('登录的 ChatGPT 账号与所选连接不一致；请新建连接。')
            else:
                target = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                    user=locked_attempt.user, registration_key_hash=registration_key,
                ).first()
            if target is None:
                target = ChatGPTSubscriptionConnection(user=locked_attempt.user)
            active_selection = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                user=locked_attempt.user, is_active=True,
            ).first()
            current_selection_id = active_selection.pk if active_selection else None
            current_selection_generation = active_selection.generation if active_selection else 0
            selection_is_unchanged = (
                current_selection_id == locked_attempt.selection_connection_id_at_start and
                current_selection_generation == locked_attempt.selection_generation_at_start
            )
            if selection_is_unchanged:
                ChatGPTSubscriptionConnection.objects.filter(user=locked_attempt.user).exclude(pk=target.pk).update(
                    is_active=False, generation=F('generation') + 1,
                )
                target.is_active = True
            target.subject_hash = _subject_hash(subject)
            target.issuer = issuer
            target.issued_client_id = client_id
            target.registration_key_hash = registration_key
            target.encrypted_subject = encrypt_secret(subject, 'verified-oauth-subject')
            target.granted_scopes = sorted(granted_scopes)
            target.account_name = str(claims.get('name', ''))[:255]
            target.account_email = str(claims.get('email', ''))[:254]
            target.encrypted_access_token = encrypt_secret(access_token, 'subscription-access-token')
            target.encrypted_refresh_token = encrypt_secret(refresh_token, 'subscription-refresh-token')
            target.access_token_expires_at = now + timedelta(seconds=float(expires_in))
            target.refresh_lease_id = ''
            target.refresh_lease_expires_at = None
            target.needs_reauth = False
            target.credential_generation += 1
            target.generation += 1
            target.save()
            locked_attempt.status = 'completed'
            locked_attempt.status_message = 'ChatGPT 订阅连接已完成。'
            locked_attempt.result_connection = target
            locked_attempt.save(update_fields=['status', 'status_message', 'result_connection'])
            return target
    except SubscriptionError as exc:
        _finish_attempt(attempt.pk, 'failed', str(exc))
        raise
    except Exception as exc:
        logger.info('ChatGPT authorization callback failed without storing credentials.')
        _finish_attempt(attempt.pk, 'failed', '授权处理失败，请重新连接。')
        raise SubscriptionError('授权处理失败，请重新连接。') from exc


def active_connection_for_user(user):
    if not getattr(user, 'is_authenticated', False):
        return None
    return ChatGPTSubscriptionConnection.objects.filter(user=user, is_active=True).first()


def get_user_connection(user, connection_id) -> ChatGPTSubscriptionConnection:
    try:
        return ChatGPTSubscriptionConnection.objects.get(user=user, pk=connection_id)
    except (ChatGPTSubscriptionConnection.DoesNotExist, ValueError, TypeError, ValidationError) as exc:
        raise SubscriptionError('订阅连接不存在。') from exc


def activate_connection(user, connection_id) -> ChatGPTSubscriptionConnection:
    with _user_lock(user.pk):
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            target = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                user=user, pk=connection_id,
            ).first()
            if target is None:
                raise SubscriptionError('订阅连接不存在。')
            if not target.connected:
                raise SubscriptionError('该账号需要重新连接后才能启用。')
            for previous in ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                user=user, is_active=True,
            ):
                if previous.pk != target.pk:
                    previous.is_active = False
                    previous.generation += 1
                    previous.save(update_fields=['is_active', 'generation', 'updated_at'])
            target.is_active = True
            target.generation += 1
            target.save(update_fields=['is_active', 'generation', 'updated_at'])
            return target


def mark_needs_reauth(connection_id, credential_generation=None, refresh_lease_id=None) -> int:
    qs = ChatGPTSubscriptionConnection.objects.filter(pk=connection_id, needs_reauth=False)
    if credential_generation is not None:
        qs = qs.filter(credential_generation=credential_generation)
    if refresh_lease_id is not None:
        qs = qs.filter(refresh_lease_id=refresh_lease_id)
    return qs.update(
        needs_reauth=True, credential_generation=F('credential_generation') + 1,
        refresh_lease_id='', refresh_lease_expires_at=None, updated_at=timezone.now(),
    )


def _assert_current_selection(connection, expected_generation=None):
    if not connection.is_active or connection.needs_reauth:
        raise SubscriptionError('ChatGPT 订阅未连接或需要重新授权。')
    if expected_generation is not None and connection.generation != expected_generation:
        raise ConnectionChangedError('订阅账号已切换或断开，翻译没有保存。')


def _acquire_refresh_lease(connection_id, credential_generation, now, lease_id):
    return ChatGPTSubscriptionConnection.objects.filter(
        pk=connection_id, credential_generation=credential_generation, needs_reauth=False,
    ).filter(
        Q(refresh_lease_expires_at__isnull=True) | Q(refresh_lease_expires_at__lte=now),
    ).update(refresh_lease_id=lease_id, refresh_lease_expires_at=now + REFRESH_LEASE_TTL)


def _refresh_access_token_with_lease(connection, expected_generation, lease_id) -> str:
    connection_id = connection.pk
    credential_generation = connection.credential_generation
    refresh_token = decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token')
    if not connection.issued_client_id:
        raise SubscriptionError('此连接缺少注册 client_id，请重新连接。')
    try:
        discovery = _discovery()
        response = requests.post(discovery['token_endpoint'], data={
            'grant_type': 'refresh_token', 'refresh_token': refresh_token,
            'client_id': connection.issued_client_id, 'resource': API_RESOURCE,
        }, timeout=20)
    except Exception as exc:
        raise SubscriptionError('刷新 ChatGPT 订阅令牌失败，请稍后重试。') from exc
    if response.status_code in (400, 401) and 'invalid_grant' in response.text:
        changed = mark_needs_reauth(connection_id, credential_generation, lease_id)
        if not changed:
            raise ConnectionChangedError('订阅凭据已更新，已忽略旧 refresh token 的失效响应。')
        raise SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。')
    if response.status_code < 200 or response.status_code >= 300:
        raise SubscriptionError(f'ChatGPT 订阅令牌刷新失败（HTTP {response.status_code}）。')
    try:
        payload = response.json()
    except Exception as exc:
        raise SubscriptionError('令牌刷新响应格式无效。') from exc
    access_token = payload.get('access_token') if isinstance(payload, dict) else None
    expires_in = payload.get('expires_in') if isinstance(payload, dict) else None
    rotated_refresh = payload.get('refresh_token') if isinstance(payload, dict) else None
    if (not isinstance(access_token, str) or not access_token
            or not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool)
            or not math.isfinite(expires_in) or expires_in <= 0):
        raise SubscriptionError('令牌刷新响应缺少有效 access token。')
    scopes = connection.granted_scopes or []
    if 'scope' in payload:
        parsed_scopes = _parse_granted_scopes(payload['scope'])
        if REQUIRED_DIRECT_SCOPE not in parsed_scopes:
            changed = mark_needs_reauth(connection_id, credential_generation, lease_id)
            if not changed:
                raise ConnectionChangedError('订阅凭据已更新，已忽略旧 refresh token 的权限响应。')
            raise SubscriptionError('令牌刷新未保留 direct model access 权限，请重新连接。')
        scopes = sorted(parsed_scopes)
    elif REQUIRED_DIRECT_SCOPE not in scopes:
        changed = mark_needs_reauth(connection_id, credential_generation, lease_id)
        if not changed:
            raise ConnectionChangedError('订阅凭据已更新，已忽略旧 refresh token 的权限响应。')
        raise SubscriptionError('此连接没有保存 direct model access 授权，请重新连接。')
    next_refresh = rotated_refresh if isinstance(rotated_refresh, str) and rotated_refresh else refresh_token
    committed_at = timezone.now()
    updated = ChatGPTSubscriptionConnection.objects.filter(
        pk=connection_id, credential_generation=credential_generation,
        refresh_lease_id=lease_id, needs_reauth=False,
    ).update(
        encrypted_access_token=encrypt_secret(access_token, 'subscription-access-token'),
        encrypted_refresh_token=encrypt_secret(next_refresh, 'subscription-refresh-token'),
        access_token_expires_at=committed_at + timedelta(seconds=float(expires_in)),
        granted_scopes=scopes, credential_generation=F('credential_generation') + 1,
        refresh_lease_id='', refresh_lease_expires_at=None, updated_at=committed_at,
    )
    if not updated:
        raise ConnectionChangedError('订阅账号已断开或凭据已更新，当前令牌没有覆盖新状态。')
    latest = ChatGPTSubscriptionConnection.objects.get(pk=connection_id)
    _assert_current_selection(latest, expected_generation)
    return access_token


def _refresh_access_token(connection_id, expected_generation=None) -> str:
    deadline = time.monotonic() + REFRESH_WAIT_SECONDS
    while True:
        try:
            connection = ChatGPTSubscriptionConnection.objects.get(pk=connection_id)
        except ChatGPTSubscriptionConnection.DoesNotExist as exc:
            raise ConnectionChangedError('订阅连接已断开。') from exc
        _assert_current_selection(connection, expected_generation)
        now = timezone.now()
        if connection.access_token_expires_at and connection.access_token_expires_at > now + timedelta(seconds=60):
            token = decrypt_secret(connection.encrypted_access_token, 'subscription-access-token')
            _assert_current_selection(ChatGPTSubscriptionConnection.objects.get(pk=connection_id), expected_generation)
            return token
        if not connection.encrypted_refresh_token:
            raise SubscriptionError('ChatGPT 订阅缺少 refresh token，请重新连接。')
        if REQUIRED_DIRECT_SCOPE not in (connection.granted_scopes or []):
            mark_needs_reauth(connection_id, connection.credential_generation)
            raise SubscriptionError('此连接没有保存 direct model access 授权，请重新连接。')
        lease_id = uuid.uuid4().hex
        if _acquire_refresh_lease(connection_id, connection.credential_generation, now, lease_id):
            try:
                try:
                    latest = ChatGPTSubscriptionConnection.objects.get(pk=connection_id)
                except ChatGPTSubscriptionConnection.DoesNotExist:
                    continue
                if latest.refresh_lease_id != lease_id:
                    continue
                if latest.credential_generation != connection.credential_generation:
                    continue
                _assert_current_selection(latest, expected_generation)
                connection = latest
                if connection.access_token_expires_at and connection.access_token_expires_at > now + timedelta(seconds=60):
                    token = decrypt_secret(connection.encrypted_access_token, 'subscription-access-token')
                    released = ChatGPTSubscriptionConnection.objects.filter(
                        pk=connection_id, credential_generation=connection.credential_generation,
                        refresh_lease_id=lease_id, needs_reauth=False,
                    ).update(refresh_lease_id='', refresh_lease_expires_at=None)
                    if not released:
                        continue
                    current = ChatGPTSubscriptionConnection.objects.get(pk=connection_id)
                    _assert_current_selection(current, expected_generation)
                    return token
                return _refresh_access_token_with_lease(connection, expected_generation, lease_id)
            finally:
                # Release only this attempt's lease. A newer owner may have
                # replaced it while the account selection was changing.
                ChatGPTSubscriptionConnection.objects.filter(
                    pk=connection_id, refresh_lease_id=lease_id,
                ).update(refresh_lease_id='', refresh_lease_expires_at=None)
        if time.monotonic() >= deadline:
            raise SubscriptionError('订阅令牌正在由另一个请求刷新，请稍后重试。')
        time.sleep(0.05)


def access_token_for(connection: ChatGPTSubscriptionConnection, expected_generation=None) -> str:
    return _refresh_access_token(connection.pk, expected_generation)


def discover_models(connection: ChatGPTSubscriptionConnection) -> list[dict[str, str]]:
    access_token = access_token_for(connection)
    try:
        credential_generation = ChatGPTSubscriptionConnection.objects.values_list(
            'credential_generation', flat=True,
        ).get(pk=connection.pk)
    except ChatGPTSubscriptionConnection.DoesNotExist as exc:
        raise ConnectionChangedError('订阅连接已断开。') from exc
    try:
        response = requests.get(
            MODELS_URL,
            headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'},
            timeout=30,
        )
    except Exception as exc:
        raise SubscriptionError('读取 ChatGPT 订阅模型列表失败。') from exc
    if response.status_code == 401:
        mark_needs_reauth(connection.pk, credential_generation)
        raise SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。')
    if response.status_code == 429:
        raise SubscriptionError('模型列表请求过于频繁（HTTP 429），请稍后重试。')
    if response.status_code < 200 or response.status_code >= 300:
        raise SubscriptionError(f'读取模型列表失败（HTTP {response.status_code}）。')
    try:
        payload = response.json()
    except Exception as exc:
        raise SubscriptionError('模型列表响应格式无效。') from exc
    items = payload.get('models') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise SubscriptionError('模型列表响应缺少 models 数组。')
    models = []
    for item in items:
        if not isinstance(item, dict):
            raise SubscriptionError('模型列表包含格式无效的项目。')
        if item.get('visibility') != 'list':
            continue
        slug = item.get('slug')
        name = item.get('display_name')
        if not isinstance(slug, str) or not slug or not isinstance(name, str) or not name:
            raise SubscriptionError('可见模型缺少有效 slug 或 display_name。')
        models.append({'slug': slug, 'display_name': name})
    return models


def disconnect_connection(user, connection_id) -> bool:
    """Clear local secrets and invalidate in-flight auth/refresh work before revocation."""
    with _user_lock(user.pk):
        with transaction.atomic():
            connection = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                user=user, pk=connection_id,
            ).first()
            if connection is None:
                raise SubscriptionError('订阅连接不存在。')
            try:
                refresh_token = (
                    decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token')
                    if connection.encrypted_refresh_token else ''
                )
            except SubscriptionError:
                refresh_token = ''
            client_id = connection.issued_client_id
            connection.encrypted_access_token = ''
            connection.encrypted_refresh_token = ''
            connection.access_token_expires_at = None
            connection.is_active = False
            connection.needs_reauth = True
            connection.generation += 1
            connection.credential_generation += 1
            connection.auth_attempt_generation += 1
            connection.refresh_lease_id = ''
            connection.refresh_lease_expires_at = None
            connection.save(update_fields=[
                'encrypted_access_token', 'encrypted_refresh_token', 'access_token_expires_at',
                'is_active', 'needs_reauth', 'generation', 'credential_generation',
                'auth_attempt_generation', 'refresh_lease_id', 'refresh_lease_expires_at', 'updated_at',
            ])
            ChatGPTAuthAttempt.objects.filter(
                target_connection=connection, status__in=['pending', 'authorizing', 'processing'],
            ).update(status='cancelled', status_message='订阅连接已断开。')
    if not refresh_token or not client_id:
        return False
    try:
        discovery = _discovery()
        revocation_endpoint = discovery.get('revocation_endpoint', '')
        parsed = urlparse(revocation_endpoint)
        if parsed.scheme != 'https' or not parsed.netloc:
            return False
        response = requests.post(revocation_endpoint, data={
            'token': refresh_token, 'token_type_hint': 'refresh_token', 'client_id': client_id,
        }, timeout=15)
        return 200 <= response.status_code < 300
    except Exception:
        logger.info('ChatGPT token revocation was not confirmed for a disconnected local connection.')
        return False


def _extract_response_text(response_data: dict) -> str:
    direct = response_data.get('output_text')
    if isinstance(direct, str) and direct:
        return direct
    output = response_data.get('output', [])
    pieces = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get('content', [])
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                    pieces.append(part['text'])
    return ''.join(pieces)


def _api_error(status_code: int, response=None) -> SubscriptionError:
    if status_code == 401:
        return SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。')
    if status_code == 403:
        return SubscriptionError('订阅未允许此模型请求；请检查授权范围或选择其他可见模型。')
    if status_code == 400:
        # Keep provider diagnostics useful without ever forwarding its raw
        # message, which may echo submitted article text or other user data.
        code = ''
        param = ''
        try:
            payload = response.json() if response is not None else {}
            detail = payload.get('error') if isinstance(payload, dict) else None
            if isinstance(detail, dict):
                recognized_codes = {
                    'model_not_found', 'invalid_model', 'unsupported_model',
                    'unsupported_parameter', 'unsupported_value',
                    'context_length_exceeded', 'input_too_long',
                    'invalid_request_error', 'invalid_value', 'parameter_missing',
                }
                # Some API errors include a provider-specific `code` alongside
                # the standardized `type`. Ignore an unknown code and still
                # use a recognized type instead of falling back to a generic 400.
                for candidate in (detail.get('code'), detail.get('type')):
                    if isinstance(candidate, str) and candidate in recognized_codes:
                        code = candidate
                        break
                raw_param = detail.get('param')
                if isinstance(raw_param, str) and raw_param in {
                    'model', 'input', 'stream', 'store', 'temperature',
                    'text', 'max_output_tokens', 'max_tokens',
                }:
                    param = raw_param
        except Exception:
            pass

        if code in {'context_length_exceeded', 'input_too_long'}:
            return SubscriptionError('文章超过所选模型的输入长度限制（HTTP 400）。')
        if code in {'model_not_found', 'invalid_model', 'unsupported_model'}:
            return SubscriptionError('所选模型拒绝了 Responses API 请求（HTTP 400）；请在订阅设置中确认所选模型。')
        if code in {'unsupported_parameter', 'unsupported_value', 'invalid_value', 'parameter_missing'}:
            suffix = f'，参数 {param}' if param else ''
            return SubscriptionError(f'模型拒绝了当前请求参数（HTTP 400{suffix}）。')
        if code == 'invalid_request_error':
            suffix = f'，参数 {param}' if param else ''
            return SubscriptionError(f'OpenAI 拒绝了翻译请求格式（HTTP 400{suffix}）。')
    if status_code == 429:
        return SubscriptionError('模型请求受到速率或额度限制（HTTP 429），请稍后重试。')
    if status_code >= 500:
        return SubscriptionError(f'OpenAI 模型服务暂时不可用（HTTP {status_code}），请稍后重试。')
    return SubscriptionError(f'OpenAI 模型请求失败（HTTP {status_code}）。')


def stream_full_translation(
    connection_id,
    expected_generation: int,
    model_slug: str,
    article_markdown: str,
    on_delta,
) -> str:
    """Consume one Responses stream; return only after response.completed."""
    access_token = _refresh_access_token(connection_id, expected_generation)
    connection = ChatGPTSubscriptionConnection.objects.filter(pk=connection_id).first()
    if connection is None or not connection.is_active or connection.generation != expected_generation:
        raise ConnectionChangedError('订阅账号已切换或断开，翻译没有保存。')
    article_input = (
        '请将以下完整 Markdown 文章翻译成中文。保持所有 Markdown 结构、代码块、'
        '行内代码、链接和标识符原样；只返回翻译后的完整 Markdown。\n\n'
        f'{article_markdown}'
    )
    payload = {
        'model': model_slug,
        'input': [{'role': 'user', 'content': article_input}],
        'store': False,
        'stream': True,
    }
    try:
        response = requests.post(
            RESPONSES_URL,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'text/event-stream',
                'Content-Type': 'application/json',
            },
            json=payload,
            stream=True,
            timeout=(10, 120),
        )
    except Exception as exc:
        raise SubscriptionError('连接 OpenAI 模型服务失败。') from exc
    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code == 401:
            mark_needs_reauth(connection_id, connection.credential_generation)
        error = _api_error(response.status_code, response)
        response.close()
        raise error

    deltas: list[str] = []
    completed_response = None
    current_event = ''
    try:
        for raw_line in response.iter_lines(decode_unicode=True):
            line = raw_line.decode('utf-8', errors='replace') if isinstance(raw_line, bytes) else raw_line
            if not line:
                continue
            if line.startswith('event:'):
                current_event = line[6:].strip()
                continue
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                break
            try:
                event = json.loads(data)
            except (TypeError, ValueError):
                raise SubscriptionError('OpenAI 返回了无法解析的 SSE 事件。')
            if not isinstance(event, dict):
                continue
            event_type = event.get('type') or current_event
            if event_type == 'response.output_text.delta':
                delta = event.get('delta')
                if isinstance(delta, str) and delta:
                    deltas.append(delta)
                    on_delta(delta)
            elif event_type == 'response.completed':
                completed_response = event.get('response') if isinstance(event.get('response'), dict) else event
                break
            elif event_type in ('response.failed', 'response.incomplete', 'error'):
                detail = event.get('error')
                if isinstance(detail, dict):
                    code = detail.get('code')
                    if code == 'rate_limit_exceeded':
                        raise SubscriptionError('模型请求受到速率或额度限制（HTTP 429），请稍后重试。')
                raise SubscriptionError('OpenAI 模型未能完整完成本次翻译。')
    except SubscriptionError:
        raise
    except Exception as exc:
        raise SubscriptionError('模型 SSE 连接中断，未保存不完整译文。') from exc
    finally:
        response.close()

    if completed_response is None:
        raise SubscriptionError('模型 SSE 流在 response.completed 前中断，未保存不完整译文。')
    final_text = _extract_response_text(completed_response) or ''.join(deltas)
    if not final_text.strip():
        raise SubscriptionError('模型已完成响应，但没有返回译文。')
    return final_text


def save_completed_translation(
    user_id,
    connection_id,
    news_id,
    expected_generation: int,
    model_slug: str,
    text: str,
    source_digest: str,
) -> ChatGPTArticleTranslation:
    """Persist a whole result only if this account generation is still active."""
    with _user_lock(user_id):
        with transaction.atomic():
            connection = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                pk=connection_id, user_id=user_id, generation=expected_generation,
                is_active=True, needs_reauth=False,
            ).first()
            if connection is None:
                raise ConnectionChangedError('订阅账号已切换或断开，翻译没有保存。')
            record, _ = ChatGPTArticleTranslation.objects.update_or_create(
                user_id=user_id,
                connection=connection,
                news_id=news_id,
                defaults={
                    'source_hash': source_digest,
                    'model_slug': model_slug,
                    'content': text,
                    'completed_at': timezone.now(),
                },
            )
            return record
