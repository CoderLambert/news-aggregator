"""Generic fixed-origin RSSHub identities; never an execution/health approval."""
import re
from urllib.parse import urlsplit,urlunsplit,quote,unquote,parse_qsl,urlencode
from api.rss.routes import RouteError,parse_alias

# Service endpoints are not subscription routes. This is not a route catalog.
RESERVED=frozenset({'api','healthz','metrics','robots.txt','favicon.ico','logo.png','build','debug','config'})
SENSITIVE=re.compile(r'(?i)token|secret|password|cookie|signature|api.?key|(?:^|[_-])auth(?:entication|orization)?(?:$|[_-])')

def _require(value):
    if not value:raise RouteError('invalid_route_input')

def _decoded(value):
    _require(not re.search(r'%(?![0-9a-fA-F]{2})',value))
    decoded=unquote(value,encoding='utf-8',errors='strict')
    probe=decoded
    for _ in range(4):
        _require(not any(ord(c)<32 or ord(c)==127 for c in probe) and '\\' not in probe)
        _require(not any(p in {'.','..'} for p in probe.split('/')))
        try:
            if '://' in probe:
                url=urlsplit(probe)
                _require(url.username is None and url.password is None)
        except ValueError:raise RouteError('invalid_route_input') from None
        again=unquote(probe,encoding='utf-8',errors='strict')
        if again==probe:break
        probe=again
    else:raise RouteError('invalid_route_input')
    return decoded

def normalize_alias(value):
    try:
        _require(isinstance(value,str) and 0<len(value)<=1024 and value==value.strip())
        _require(not any(ord(c)<33 or ord(c)==127 for c in value) and '\\' not in value)
        parsed=urlsplit(value)
        namespace=parsed.netloc.lower()
        _require(parsed.scheme.lower()=='rsshub' and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',namespace))
        _require(namespace not in RESERVED and namespace not in {'localhost','local','internal'})
        _require(not parsed.fragment and not value.endswith('#'))
        parts=parsed.path.split('/')[1:]
        while parts and parts[-1]=='':parts.pop()
        path='/'.join(quote(_decoded(p),safe="!$&'()*+,-.;=_~") for p in parts)
        query=parse_qsl(parsed.query,keep_blank_values=True,encoding='utf-8',errors='strict',max_num_fields=40)
        _require(not re.search(r'%(?![0-9a-fA-F]{2})',parsed.query))
        for key,val in query:
            key=_decoded(key);_decoded(val)
            _require(not SENSITIVE.search(key) and key.lower() not in {'key','k','sig','jwt','credential','access_key','feedkey','proxy','proxy_url','headers'})
            _require(not (key.lower()=='mode' and val.lower()=='fulltext'))
        suffix=('?'+urlencode(query,quote_via=quote)) if query else ''
        alias='rsshub://'+namespace+('/'+path if path else '')+suffix
        _require(len(alias)<=1024)
        return alias
    except (ValueError,UnicodeError,TypeError):raise RouteError('invalid_route_input') from None

def metadata(alias):
    try:
        route=parse_alias(alias)
        return route.template_id,route.public()['content_kind'],dict(route.parameters)
    except RouteError:return '', 'article',{}

def gateway_alias(value,origin):
    parsed=urlsplit(value);base=urlsplit(origin)
    _require(parsed.scheme=='https' and parsed.netloc==base.netloc and not parsed.fragment)
    _require(parsed.path.startswith('/') and not parsed.path.startswith('//'))
    return normalize_alias('rsshub:/'+parsed.path+('?' + parsed.query if parsed.query else ''))

def target(alias,origin):
    return origin+'/'+alias.removeprefix('rsshub://')
