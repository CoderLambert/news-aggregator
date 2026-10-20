"""Operator-owned RSSHub gateway resolution. No network or browser credentials."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from django.conf import settings
from api.rss.routes import GatewayConfig, RouteError, parse_alias, gateway_target, match_gateway_target, gateway_request

MESSAGES={
    'rsshub_unconfigured':'RSSHub 尚未配置，请联系管理员配置站点 RSSHub 网关。',
    'rsshub_unverified':'RSSHub 网关尚未完成连接验证，暂不能添加。',
    'rsshub_route_unavailable':'站点尚未开放此 RSSHub 路由。',
    'rsshub_capability_missing':'此 RSSHub 路由所需的认证或公开内容能力尚未配置。',
    'rsshub_invalid_route':'RSSHub 地址或参数无效，请检查路由格式。',
    'rsshub_configuration_changed':'RSSHub 配置已改变，需要管理员重新核验现有连接。',
    'rsshub_route_paused':'此 RSSHub 来源已暂停接入；Twitter 暂未启用。',
    'rsshub_auth_unavailable':'RSSHub 网关认证配置不可用，请联系管理员。',
}

@dataclass(frozen=True)
class Selection:
    url: str
    alias: str = ''
    version: str = ''


def _fail(code):
    from api.rss.operations import OperationError
    raise OperationError(code)


def raw_config():
    if settings.configured: return getattr(settings,'RSSHUB_GATEWAY',{})
    try: return json.loads(os.environ.get('RSSHUB_GATEWAY_CONFIG','{}'))
    except (ValueError,TypeError): return {}


def config():
    raw=raw_config()
    if not isinstance(raw,dict) or raw.get('enabled') is not True: _fail('rsshub_unconfigured')
    if raw.get('verified') is not True or type(raw.get('version')) is not int or raw['version']<1: _fail('rsshub_unverified')
    try:
        for key in ('routes','capabilities'):
            if not isinstance(raw.get(key,[]),list) or any(not isinstance(x,str) or len(x)>128 for x in raw.get(key,[])): raise ValueError
        if type(raw.get('auth_required',True)) is not bool or not isinstance(raw.get('auth_file',''),str): raise ValueError
        proxy=raw.get('proxy_url','')
        if not isinstance(proxy,str): raise ValueError
        if proxy:
            parsed=urlsplit(proxy)
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.path not in {'','/'} or parsed.query or parsed.fragment or not parsed.port or any(ord(c)<=32 for c in proxy): raise ValueError
        if type(raw.get('generic',False)) is not bool: raise ValueError
        if raw.get('generic') and (type(raw.get('generic_version')) is not int or raw['generic_version']<1): raise ValueError
        if not isinstance(raw.get('blocked_namespaces',[]),list) or any(not isinstance(x,str) for x in raw.get('blocked_namespaces',[])): raise ValueError
        cfg=GatewayConfig(raw['origin'],enabled=True,approved_repositories=tuple(tuple(x) for x in raw.get('repositories',[])),
            runtime_verified=True,runtime_version=raw['version'],approved_routes=tuple(raw.get('routes',[])),
            verified_capabilities=tuple(raw.get('capabilities',[])))
    except (KeyError,TypeError,ValueError): _fail('rsshub_unverified')
    return raw,cfg


def selection(value):
    """Return None for ordinary URLs; configured origin is never a bypass."""
    if not isinstance(value,str): return None
    value=value.strip()
    raw=raw_config()
    origin=raw.get('origin') if isinstance(raw,dict) else None
    try:
        parsed=urlsplit(value)
        is_alias=parsed.scheme.lower()=='rsshub'
        is_gateway=bool(origin and parsed.hostname==urlsplit(origin).hostname)
    except ValueError:
        if value.lower().startswith('rsshub:'): _fail('rsshub_invalid_route')
        return None
    if not (is_alias or is_gateway): return None
    raw,cfg=config()
    from api.rss.rsshub_url import normalize_alias,gateway_alias,target
    generic=False
    try:
        # Preserve an already admitted legacy identity/hash; new paths use the
        # generic contract. No per-template allowlist applies in generic mode.
        try:
            route=parse_alias(value) if is_alias else match_gateway_target(value,cfg)
            if route.template_id not in cfg.approved_routes: raise RouteError('legacy_not_admitted')
            if not set(route.public()['capability_requirements'])<=set(cfg.verified_capabilities):
                if not raw.get('generic'): _fail('rsshub_capability_missing')
                raise RouteError('legacy_not_admitted')
            resolved=gateway_target(route.alias,cfg)
            gateway_request(resolved,cfg)
            alias=route.alias
        except RouteError:
            if raw.get('generic') is not True: raise
            alias=normalize_alias(value) if is_alias else gateway_alias(value,cfg.origin)
            resolved=target(alias,cfg.origin)
            generic=True
        if alias.removeprefix('rsshub://').split('/')[0].split('?')[0] in raw.get('blocked_namespaces',[]):
            _fail('rsshub_route_paused')
    except RouteError: _fail('rsshub_invalid_route')
    # A declared version covers credential rotation; raw secret bytes never enter web state.
    version=sha256(json.dumps({'origin':cfg.origin,'version':cfg.runtime_version,'routes':sorted(cfg.approved_routes),
        'capabilities':sorted(cfg.verified_capabilities),'repositories':cfg.approved_repositories,
        'auth_required':raw.get('auth_required',True),'auth_file':raw.get('auth_file',''),'proxy_url':raw.get('proxy_url','')},sort_keys=True).encode()).hexdigest()
    if generic:
        version=sha256(json.dumps({'base':version,'generic_version':raw['generic_version'],
            'blocked_namespaces':sorted(raw.get('blocked_namespaces',[]))},sort_keys=True).encode()).hexdigest()
    return Selection(resolved,alias,version)


def credentials(url):
    """Worker-only gateway transport. Secrets stay out of operations, DTOs and URLs."""
    chosen=selection(url)
    if chosen is None: return {}
    raw,_=config()
    transport={'proxy_url':raw['proxy_url']} if raw.get('proxy_url') else {}
    path=raw.get('auth_file')
    if not path:
        if raw.get('auth_required',True): _fail('rsshub_auth_unavailable')
        return transport
    try:
        content=Path(path).read_bytes()
        if len(content)>4096: raise ValueError
        auth=json.loads(content)
        if not isinstance(auth,dict) or set(auth)!={'username','password'} or any(not isinstance(v,str) or not 1<=len(v)<=1024 or any(ord(c)<32 for c in v) for v in auth.values()): raise ValueError
        return {**transport,**auth}
    except (OSError,ValueError,TypeError): _fail('rsshub_auth_unavailable')


def assert_binding(binding):
    if not binding.rsshub_alias: return
    chosen=selection(binding.rsshub_alias)
    if chosen is None or chosen.url!=binding.canonical_feed_url or chosen.version!=binding.rsshub_gateway_version:
        _fail('rsshub_configuration_changed')
