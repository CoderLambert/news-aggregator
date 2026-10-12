"""Deterministic identity normalization; never invents or resolves a URL."""
import ipaddress
from urllib.parse import urlsplit, urlunsplit, unquote


class InvalidIdentity(ValueError):
    error_code = 'invalid_identity'


TRACKING_KEYS = {'fbclid', 'gclid', 'dclid', 'mc_cid', 'mc_eid'}


def normalize_article_url(value: str, *, max_length: int = 500, require_article: bool = True) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise InvalidIdentity('invalid_url')
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        port = parsed.port
    except ValueError:
        raise InvalidIdentity('invalid_url') from None
    if parsed.scheme.lower() not in {'http', 'https'} or not host or parsed.username or parsed.password:
        raise InvalidIdentity('invalid_url')
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        raise InvalidIdentity('invalid_host')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise InvalidIdentity('invalid_host')
    if require_article and parsed.path.strip('/').lower() in {'', 'search', 'search/news', 'login', 'signin', 'sign-in'}:
        raise InvalidIdentity('not_article_url')
    scheme = parsed.scheme.lower()
    authority = f'[{host}]' if ':' in host else host
    if port is not None and (scheme, port) not in {('http', 80), ('https', 443)}:
        authority += f':{port}'
    # BBC's existing RSS samples explicitly identify at_medium as tracking.
    site_tracking = {'at_medium'} if host in {'bbc.com', 'www.bbc.com', 'bbc.co.uk', 'www.bbc.co.uk'} else set()
    # Keep business queries byte-for-byte, including encoding and ordering.
    query = '&'.join(part for part in parsed.query.split('&') if part and
                     not (unquote(part.split('=', 1)[0]).lower().startswith('utm_') or
                          unquote(part.split('=', 1)[0]).lower() in TRACKING_KEYS | site_tracking))
    normalized = urlunsplit((scheme, authority, parsed.path, query, ''))
    if len(normalized) > max_length:
        raise InvalidIdentity('url_too_long')
    return normalized


def validate_upstream_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise InvalidIdentity('invalid_upstream_id')
    return value  # GUIDs are opaque: never truncate or case-fold them.


def same_article_identity(left: str, right: str, *, allow_host_alias: bool = False) -> bool:
    try:
        left = normalize_article_url(left)
        right = normalize_article_url(right)
    except InvalidIdentity:
        return False
    if left == right:
        return True
    if not allow_host_alias:
        return False
    from api.services.source_policy import policy_for_url
    policy = policy_for_url(left)
    a, b = urlsplit(left), urlsplit(right)
    return bool(policy and b.hostname in policy.domains and a.scheme == b.scheme and
                a.port == b.port and a.path == b.path and a.query == b.query)
