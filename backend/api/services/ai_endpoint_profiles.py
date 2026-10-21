"""Pure, shared administrator endpoint contract; no Django or network side effects.

The Proxy mounts this same module. Parsing is admission, not proof that the
deployment's egress/terminal adapter is active; those gates remain separate.
"""
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


SERVICE_PRESETS = {
    'ollama': 'Ollama', 'lm_studio': 'LM Studio', 'vllm': 'vLLM',
    'siliconflow': '硅基流动', 'openrouter': 'OpenRouter',
    'openai_compatible': 'OpenAI 兼容服务', 'openai': 'OpenAI',
    'qwen': '百炼', 'deepseek': 'DeepSeek',
}
ADAPTER_VERSION = 'chat-terminal-egress-v1'
_IDENTIFIER = re.compile(r'^[a-z][a-z0-9_]{0,47}$')
_HOSTNAME = re.compile(r'^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$')
_MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$')
_FIELDS = frozenset((
    'profile_id', 'version', 'provider_id', 'display_name', 'protocol_family',
    'api_base', 'network_zone', 'allowed_ips', 'auth_modes', 'allowed_user_ids', 'enabled',
))


class EndpointManifestError(ValueError):
    def __init__(self):
        super().__init__('invalid_endpoint_manifest')


def valid_upstream_model_id(value):
    return bool(type(value) is str and _MODEL_ID.fullmatch(value)
                and '://' not in value and '..' not in value and '//' not in value
                and not value.lower().startswith(('sk-', 'ark-', 'aiza')))


def _require(condition):
    if not condition:
        raise EndpointManifestError()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _address(value):
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise EndpointManifestError() from None
    _require(str(address) == value and not (
        address.is_unspecified or address.is_link_local or address.is_multicast
        or getattr(address, 'ipv4_mapped', None) is not None
        or (address.is_reserved and not address.is_loopback)
    ))
    return address


def validate_endpoint_profiles(raw):
    """Validate a complete manifest atomically; never accept a partial prefix."""
    _require(type(raw) is list and len(raw) <= 64)
    result, identities = [], set()
    for item in raw:
        _require(type(item) is dict and set(item) == _FIELDS)
        item = dict(item)
        identity = item['profile_id']
        _require(type(identity) is str and _IDENTIFIER.fullmatch(identity)
                 and not identity.endswith('_default') and identity not in identities)
        identities.add(identity)
        _require(type(item['version']) is int and 1 <= item['version'] <= 32767)
        _require(type(item['provider_id']) is str and item['provider_id'] in SERVICE_PRESETS)
        label = item['display_name']
        _require(type(label) is str and 1 <= len(label) <= 64
                 and not any(ord(c) < 32 or ord(c) == 127 for c in label))
        _require(item['protocol_family'] == 'chat_completions_v1')
        _require(type(item['enabled']) is bool)
        modes = item['auth_modes']
        _require(type(modes) is list and 1 <= len(modes) <= 2
                 and all(type(mode) is str and mode in ('api_key', 'none') for mode in modes)
                 and len(set(modes)) == len(modes))
        owners = item['allowed_user_ids']
        _require(type(owners) is list and len(owners) <= 10000
                 and all(type(owner) is int and owner > 0 for owner in owners)
                 and len(set(owners)) == len(owners))
        zone = item['network_zone']
        _require(zone in ('public_https', 'trusted_private', 'same_host'))
        if zone != 'public_https' or 'none' in modes:
            _require(bool(owners))
        ips = item['allowed_ips']
        _require(type(ips) is list and 1 <= len(ips) <= 32)
        addresses = [_address(ip) for ip in ips]
        _require(len(set(ips)) == len(ips))
        if zone == 'public_https':
            _require(all(ip.is_global for ip in addresses))
        elif zone == 'same_host':
            _require(all(ip.is_loopback for ip in addresses))
        else:
            _require(all(ip.is_private and not ip.is_loopback for ip in addresses))
        url = item['api_base']
        _require(type(url) is str and len(url) <= 512 and not any(c.isspace() for c in url))
        try:
            parsed = urlsplit(url)
            port, host = parsed.port, parsed.hostname
        except ValueError:
            raise EndpointManifestError() from None
        _require(parsed.scheme in ('https', 'http') and host and parsed.username is None
                 and parsed.password is None and not parsed.query and not parsed.fragment
                 and parsed.path in ('/v1', '/v1/') and (port is None or 1 <= port <= 65535)
                 and '%' not in url and '\\' not in url)
        if zone == 'public_https':
            _require(parsed.scheme == 'https')
        try:
            numeric = ipaddress.ip_address(host)
        except ValueError:
            # Numeric shortcuts (127.1, decimal, octal) must not reach DNS.
            _require(bool(_HOSTNAME.fullmatch(host)) and '.' in host
                     and any('a' <= char <= 'z' for char in host)
                     and not host.endswith('.') and '..' not in host)
            numeric = None
        if numeric is not None:
            _require(str(numeric) == host and host in ips)
        elif zone == 'same_host':
            raise EndpointManifestError()
        semantic = {key: item[key] for key in sorted(_FIELDS - {'display_name', 'enabled'})}
        semantic.update(adapter_version=ADAPTER_VERSION)
        # Order of administrator allowlists is not an identity change.
        for key in ('allowed_ips', 'allowed_user_ids', 'auth_modes'):
            semantic[key] = sorted(semantic[key])
        digest = hashlib.sha256(json.dumps(semantic, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:20]
        item.update(route_prefix=f'newshub/{identity}-v{item["version"]}-{digest}',
                    policy_digest=digest, adapter_version=ADAPTER_VERSION)
        result.append(item)
    return tuple(result)


def load_endpoint_profiles(path):
    """No cache: revocation must be observed on every authorization check."""
    if not path:
        return ()
    try:
        with Path(path).open('rb') as handle:
            data = handle.read(65537)
        _require(len(data) <= 65536)
        return validate_endpoint_profiles(json.loads(data, object_pairs_hook=_unique_object))
    except (OSError, ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise EndpointManifestError() from None


def profile_allows_user(profile, user_id):
    owners = profile.get('allowed_user_ids', [])
    return bool(profile.get('enabled', True) and (
        not owners or (type(user_id) is int and user_id in owners)
    ))
