"""Fail-closed SIWC deployment configuration.

The website mode is usable only after explicit partner approval for remotely
hosted, per-user ChatGPT plan inference and credential handling. A regular
identity-only SIWC client does not enable ChatGPT plan usage.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

API_RESOURCE = 'https://api.openai.com/v1'
LOCAL_REDIRECT_URI = 'http://127.0.0.1:9527/api/chatgpt-subscription/callback/'
LOCAL_HANDOFF_URI = 'http://127.0.0.1:9527/api/chatgpt-subscription/handoff/'
REQUIRED_DIRECT_SCOPE = 'chatgpt.tokens.use.direct'
CALLBACK_PATH = '/api/chatgpt-subscription/callback/'
HANDOFF_PATH = '/api/chatgpt-subscription/handoff/'


class SiwcConfigError(ValueError):
    """Operator-safe configuration failure: no OAuth or model calls are allowed."""


@dataclass(frozen=True)
class SiwcConfig:
    mode: str
    client_id: str
    redirect_uri: str
    handoff_uri: str
    scopes: str
    token_auth_method: str
    resource: str = API_RESOURCE
    client_secret: str = ''

    @property
    def website(self) -> bool:
        return self.mode == 'website'


def load_siwc_config() -> SiwcConfig:
    mode = str(getattr(settings, 'CHATGPT_SIWC_MODE', 'local'))
    if mode == 'local':
        return SiwcConfig(
            mode='local', client_id='dynamic_agent_client',
            redirect_uri=LOCAL_REDIRECT_URI, handoff_uri=LOCAL_HANDOFF_URI,
            scopes='openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',
            token_auth_method='none',
        )
    if mode != 'website':
        raise SiwcConfigError('CHATGPT_SIWC_MODE 只允许 local 或 website。')

    if not getattr(settings, 'CHATGPT_WEBSITE_PARTNER_APPROVED', False) or not str(
        getattr(settings, 'CHATGPT_WEBSITE_APPROVAL_REFERENCE', '')
    ).strip():
        raise SiwcConfigError('公网 ChatGPT 订阅调用尚未取得并登记 OpenAI 的明确托管授权。')
    if getattr(settings, 'DEBUG', False):
        raise SiwcConfigError('公网 SIWC 模式不允许 DJANGO_DEBUG=1。')

    client_id = str(getattr(settings, 'CHATGPT_WEBSITE_CLIENT_ID', '')).strip()
    redirect_uri = str(getattr(settings, 'CHATGPT_WEBSITE_REDIRECT_URI', '')).strip()
    scopes = str(getattr(settings, 'CHATGPT_WEBSITE_SCOPES', '')).strip()
    method = str(getattr(settings, 'CHATGPT_WEBSITE_TOKEN_AUTH_METHOD', '')).strip()
    secret = str(getattr(settings, 'CHATGPT_WEBSITE_CLIENT_SECRET', ''))
    if (not client_id or client_id == 'dynamic_agent_client'
            or len(client_id) > 255 or any(c.isspace() for c in client_id)):
        raise SiwcConfigError('必须配置 OpenAI 正式签发的网站 Client ID。')
    parsed = urlsplit(redirect_uri)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment
            or parsed.path != CALLBACK_PATH):
        raise SiwcConfigError('网站回调必须是登记过的完整 HTTPS URL，且使用固定 callback 路径。')
    origin = f'https://{parsed.hostname}'
    if str(getattr(settings, 'CHATGPT_WEBSITE_ORIGIN', '')).strip() != origin:
        raise SiwcConfigError('网站来源必须与 OAuth 回调来源完全一致。')
    if parsed.hostname not in getattr(settings, 'ALLOWED_HOSTS', ()):
        raise SiwcConfigError('网站域名未加入 DJANGO_ALLOWED_HOSTS。')
    if '*' in getattr(settings, 'ALLOWED_HOSTS', ()):
        raise SiwcConfigError('公网模式禁止 ALLOWED_HOSTS=*。')
    if getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):
        raise SiwcConfigError('公网模式禁止 CORS_ALLOW_ALL_ORIGINS。')
    if not getattr(settings, 'SESSION_COOKIE_SECURE', False) or not getattr(settings, 'CSRF_COOKIE_SECURE', False):
        raise SiwcConfigError('公网模式必须启用 Session 与 CSRF Secure Cookie。')
    if origin not in getattr(settings, 'CHATGPT_HANDOFF_ALLOWED_ORIGINS', ()):
        raise SiwcConfigError('网站来源未加入 ChatGPT handoff 来源白名单。')
    if origin not in getattr(settings, 'CSRF_TRUSTED_ORIGINS', ()):
        raise SiwcConfigError('网站来源未加入 CSRF 来源白名单。')

    granted = set(scopes.split())
    required = {'openid', 'offline_access', 'resource.invoke', REQUIRED_DIRECT_SCOPE}
    if not required.issubset(granted):
        raise SiwcConfigError('网站 Client 必须被明确授权使用 ChatGPT 订阅模型及刷新所需的 scopes。')
    if method not in ('none', 'client_secret_basic'):
        raise SiwcConfigError('网站客户端认证方式仅支持 none 或 client_secret_basic。')
    if (method == 'none' and secret) or (method == 'client_secret_basic' and not secret):
        raise SiwcConfigError('网站 OAuth Client Secret 与认证方式不匹配。')

    return SiwcConfig(
        mode='website', client_id=client_id,
        redirect_uri=redirect_uri, handoff_uri=origin + HANDOFF_PATH,
        scopes=scopes, token_auth_method=method, client_secret=secret,
    )
