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
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
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
API_RESOURCE = 'https://api.openai.com/v1'
MODELS_URL = f'{API_RESOURCE}/models'
RESPONSES_URL = f'{API_RESOURCE}/responses'
DYNAMIC_CLIENT_ID = 'dynamic_agent_client'
REQUIRED_DIRECT_SCOPE = 'chatgpt.tokens.use.direct'
REQUESTED_SCOPES = (
    'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
)
AUTH_ATTEMPT_TTL = timedelta(minutes=10)


class SubscriptionError(Exception):
    """Safe-to-display subscription flow error."""


class ConnectionChangedError(SubscriptionError):
    pass


_CONNECTION_LOCKS: dict[str, threading.RLock] = {}
_CONNECTION_LOCKS_GUARD = threading.Lock()
_USER_LOCKS: dict[int, threading.RLock] = {}
_USER_LOCKS_GUARD = threading.Lock()


def _user_lock(user_id) -> threading.RLock:
    key = int(user_id)
    with _USER_LOCKS_GUARD:
        return _USER_LOCKS.setdefault(key, threading.RLock())


def _connection_lock(connection_id) -> threading.RLock:
    key = str(connection_id)
    with _CONNECTION_LOCKS_GUARD:
        return _CONNECTION_LOCKS.setdefault(key, threading.RLock())


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


def _subject_hash(subject: str) -> str:
    key = _encryption_key()
    return hmac.new(key, subject.encode('utf-8'), hashlib.sha256).hexdigest()


def source_hash(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_installation_client() -> ChatGPTOAuthClient:
    client, _ = ChatGPTOAuthClient.objects.get_or_create(
        pk=1,
        defaults={'host_id': secrets.token_urlsafe(32)},
    )
    return client


def get_oauth_client_id() -> str:
    client_id = get_installation_client().issued_client_id
    if not client_id:
        raise SubscriptionError('尚未完成 ChatGPT 订阅客户端注册。')
    return client_id


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


def create_authorization_attempt(user, target_connection=None) -> str:
    if target_connection is not None and target_connection.user_id != user.pk:
        raise SubscriptionError('不能操作其他用户的订阅连接。')

    installation = get_installation_client()
    requested_client_id = installation.issued_client_id or DYNAMIC_CLIENT_ID
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    attempt = ChatGPTAuthAttempt.objects.create(
        user=user,
        target_connection=target_connection,
        state_hash=hashlib.sha256(state.encode('ascii')).hexdigest(),
        nonce_hash=hashlib.sha256(nonce.encode('ascii')).hexdigest(),
        encrypted_pkce_verifier=encrypt_secret(verifier, 'oauth-pkce-verifier'),
        requested_client_id=requested_client_id,
        expires_at=timezone.now() + AUTH_ATTEMPT_TTL,
    )
    discovery = _discovery()
    params = {
        'response_type': 'code',
        'client_id': requested_client_id,
        'redirect_uri': REDIRECT_URI,
        'scope': REQUESTED_SCOPES,
        'resource': API_RESOURCE,
        'state': state,
        'nonce': nonce,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'ext_agent_host_id': installation.host_id,
    }
    if requested_client_id == DYNAMIC_CLIENT_ID:
        params['agent_name_hint'] = getattr(settings, 'CHATGPT_AGENT_NAME_HINT', 'News Aggregator')
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


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


def _consume_attempt(state: str) -> ChatGPTAuthAttempt:
    state_hash = hashlib.sha256(state.encode('utf-8')).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        try:
            attempt = ChatGPTAuthAttempt.objects.get(state_hash=state_hash)
        except ChatGPTAuthAttempt.DoesNotExist as exc:
            raise SubscriptionError('登录状态无效或已使用。') from exc
        if attempt.expires_at <= now:
            ChatGPTAuthAttempt.objects.filter(pk=attempt.pk, consumed_at__isnull=True).update(consumed_at=now)
            raise SubscriptionError('登录请求已过期，请重新连接。')
        updated = ChatGPTAuthAttempt.objects.filter(
            pk=attempt.pk, consumed_at__isnull=True, expires_at__gt=now,
        ).update(consumed_at=now)
        if not updated:
            raise SubscriptionError('登录状态无效或已使用。')
        attempt.consumed_at = now
        return attempt


def _exchange_code(code: str, client_id: str, verifier: str, token_endpoint: str) -> dict:
    try:
        response = requests.post(
            token_endpoint,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI,
                'client_id': client_id,
                'code_verifier': verifier,
                'resource': API_RESOURCE,
            },
            timeout=20,
        )
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


def complete_authorization(query) -> ChatGPTSubscriptionConnection:
    state = query.get('state', '')
    if not state:
        raise SubscriptionError('登录状态缺失，请重新连接。')
    attempt = _consume_attempt(state)
    if query.get('error'):
        raise SubscriptionError('你取消了 ChatGPT 订阅授权。')
    code = query.get('code', '')
    if not code:
        raise SubscriptionError('OpenAI 登录回调缺少授权码。')

    installation = get_installation_client()
    returned_client_id = query.get('client_id', '')
    if attempt.requested_client_id == DYNAMIC_CLIENT_ID:
        if not returned_client_id or returned_client_id == DYNAMIC_CLIENT_ID:
            raise SubscriptionError('首次注册没有返回 OpenAI client_id。')
        client_id = returned_client_id
    else:
        client_id = attempt.requested_client_id
        if returned_client_id and returned_client_id != client_id:
            raise SubscriptionError('OpenAI 返回的 client_id 与本地注册不一致。')

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
    granted_scopes = token_payload.get('scope') or claims.get('scope') or ''
    if isinstance(granted_scopes, str):
        scope_set = set(granted_scopes.split())
    elif isinstance(granted_scopes, list):
        scope_set = set(granted_scopes)
    else:
        scope_set = set()
    if REQUIRED_DIRECT_SCOPE not in scope_set:
        raise SubscriptionError('订阅未授予 direct model access 权限，请重新授权并允许该权限。')

    subject = claims['sub']
    subject_hash = _subject_hash(subject)
    with _user_lock(attempt.user_id):
        with transaction.atomic():
            installation = ChatGPTOAuthClient.objects.select_for_update().get(pk=1)
            if installation.issued_client_id and installation.issued_client_id != client_id:
                raise SubscriptionError('本地 OpenAI 动态客户端身份发生变化，请重新开始连接。')
            if not installation.issued_client_id:
                installation.issued_client_id = client_id
                installation.save(update_fields=['issued_client_id', 'updated_at'])

            target = None
            if attempt.target_connection_id:
                target = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                    pk=attempt.target_connection_id, user=attempt.user,
                ).first()
                if target is None:
                    raise SubscriptionError('待重新连接的账号已不存在。')
                if target.subject_hash != subject_hash:
                    raise SubscriptionError('登录的 ChatGPT 账号与所选连接不一致；请新建连接。')
            else:
                target = ChatGPTSubscriptionConnection.objects.select_for_update().filter(
                    user=attempt.user, subject_hash=subject_hash,
                ).first()
            if target is None:
                target = ChatGPTSubscriptionConnection(
                    user=attempt.user,
                    subject_hash=subject_hash,
                )
            ChatGPTSubscriptionConnection.objects.filter(user=attempt.user).exclude(pk=target.pk).update(
                is_active=False, generation=F('generation') + 1,
            )
            target.account_name = str(claims.get('name', ''))[:255]
            target.account_email = str(claims.get('email', ''))[:254]
            target.encrypted_access_token = encrypt_secret(access_token, 'subscription-access-token')
            target.encrypted_refresh_token = encrypt_secret(refresh_token, 'subscription-refresh-token')
            target.access_token_expires_at = timezone.now() + timedelta(seconds=float(expires_in))
            target.is_active = True
            target.needs_reauth = False
            target.generation += 1
            target.save()
            return target


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


def mark_needs_reauth(connection_id, generation=None) -> None:
    qs = ChatGPTSubscriptionConnection.objects.filter(pk=connection_id)
    if generation is not None:
        qs = qs.filter(generation=generation)
    qs.update(needs_reauth=True)


def _refresh_access_token(connection_id, expected_generation=None) -> str:
    with _connection_lock(connection_id):
        try:
            connection = ChatGPTSubscriptionConnection.objects.get(pk=connection_id)
        except ChatGPTSubscriptionConnection.DoesNotExist as exc:
            raise ConnectionChangedError('订阅连接已断开。') from exc
        if expected_generation is not None and connection.generation != expected_generation:
            raise ConnectionChangedError('订阅账号已切换或断开，翻译没有保存。')
        if not connection.is_active or connection.needs_reauth:
            raise SubscriptionError('ChatGPT 订阅未连接或需要重新授权。')
        now = timezone.now()
        if connection.access_token_expires_at and connection.access_token_expires_at > now + timedelta(seconds=60):
            return decrypt_secret(connection.encrypted_access_token, 'subscription-access-token')
        if not connection.encrypted_refresh_token:
            raise SubscriptionError('ChatGPT 订阅缺少 refresh token，请重新连接。')
        refresh_token = decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token')
        client_id = get_oauth_client_id()
        discovery = _discovery()
        try:
            response = requests.post(
                discovery['token_endpoint'],
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': refresh_token,
                    'client_id': client_id,
                    'resource': API_RESOURCE,
                },
                timeout=20,
            )
        except Exception as exc:
            raise SubscriptionError('刷新 ChatGPT 订阅令牌失败，请稍后重试。') from exc
        if response.status_code in (400, 401) and 'invalid_grant' in response.text:
            mark_needs_reauth(connection_id, connection.generation)
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
        next_refresh = rotated_refresh if isinstance(rotated_refresh, str) and rotated_refresh else refresh_token
        updated = ChatGPTSubscriptionConnection.objects.filter(
            pk=connection_id, generation=connection.generation, is_active=True, needs_reauth=False,
        ).update(
            encrypted_access_token=encrypt_secret(access_token, 'subscription-access-token'),
            encrypted_refresh_token=encrypt_secret(next_refresh, 'subscription-refresh-token'),
            access_token_expires_at=now + timedelta(seconds=float(expires_in)),
            updated_at=now,
        )
        if not updated:
            raise ConnectionChangedError('订阅账号已切换或断开，翻译没有保存。')
        return access_token


def access_token_for(connection: ChatGPTSubscriptionConnection, expected_generation=None) -> str:
    return _refresh_access_token(connection.pk, expected_generation)


def discover_models(connection: ChatGPTSubscriptionConnection) -> list[dict[str, str]]:
    access_token = access_token_for(connection)
    try:
        response = requests.get(
            MODELS_URL,
            headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'},
            timeout=30,
        )
    except Exception as exc:
        raise SubscriptionError('读取 ChatGPT 订阅模型列表失败。') from exc
    if response.status_code == 401:
        mark_needs_reauth(connection.pk, connection.generation)
        raise SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。')
    if response.status_code == 429:
        raise SubscriptionError('模型列表请求过于频繁（HTTP 429），请稍后重试。')
    if response.status_code < 200 or response.status_code >= 300:
        raise SubscriptionError(f'读取模型列表失败（HTTP {response.status_code}）。')
    try:
        items = response.json().get('data', [])
    except Exception as exc:
        raise SubscriptionError('模型列表响应格式无效。') from exc
    if not isinstance(items, list):
        raise SubscriptionError('模型列表响应格式无效。')
    models = []
    for item in items:
        if not isinstance(item, dict) or item.get('visibility') != 'list':
            continue
        slug = item.get('slug')
        if not isinstance(slug, str) or not slug:
            continue
        display_name = item.get('display_name')
        models.append({'slug': slug, 'display_name': display_name if isinstance(display_name, str) and display_name else slug})
    return sorted(models, key=lambda item: (item['display_name'].casefold(), item['slug']))


def disconnect_connection(user, connection_id) -> bool:
    """Clear local secrets and advance the generation before best-effort revocation."""
    connection = get_user_connection(user, connection_id)
    with _user_lock(user.pk):
        with _connection_lock(connection.pk):
            connection.refresh_from_db()
            try:
                refresh_token = (
                    decrypt_secret(connection.encrypted_refresh_token, 'subscription-refresh-token')
                    if connection.encrypted_refresh_token else ''
                )
            except SubscriptionError:
                # Clear local secrets even if the configured key changed or the
                # ciphertext is damaged; revocation can then be unconfirmed.
                refresh_token = ''
            client_id = ''
            try:
                client_id = get_oauth_client_id()
            except SubscriptionError:
                pass
            connection.encrypted_access_token = ''
            connection.encrypted_refresh_token = ''
            connection.access_token_expires_at = None
            connection.is_active = False
            connection.needs_reauth = True
            connection.generation += 1
            connection.save(update_fields=[
                'encrypted_access_token', 'encrypted_refresh_token', 'access_token_expires_at',
                'is_active', 'needs_reauth', 'generation', 'updated_at',
            ])
    if not refresh_token or not client_id:
        return False
    try:
        discovery = _discovery()
        revocation_endpoint = discovery.get('revocation_endpoint', '')
        parsed = urlparse(revocation_endpoint)
        if parsed.scheme != 'https' or not parsed.netloc:
            return False
        response = requests.post(
            revocation_endpoint,
            data={'token': refresh_token, 'token_type_hint': 'refresh_token', 'client_id': client_id},
            timeout=15,
        )
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


def _api_error(status_code: int) -> SubscriptionError:
    if status_code == 401:
        return SubscriptionError('ChatGPT 订阅授权已失效，请重新连接账号。')
    if status_code == 403:
        return SubscriptionError('订阅未允许此模型请求；请检查授权范围或选择其他可见模型。')
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
    payload = {
        'model': model_slug,
        'input': (
            '请将以下完整 Markdown 文章翻译成中文。保持所有 Markdown 结构、代码块、'
            '行内代码、链接和标识符原样；只返回翻译后的完整 Markdown。\n\n'
            f'{article_markdown}'
        ),
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
            mark_needs_reauth(connection_id, expected_generation)
        response.close()
        raise _api_error(response.status_code)

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
