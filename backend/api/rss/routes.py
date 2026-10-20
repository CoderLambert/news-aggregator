"""Reviewed RSSHub parameter schemas, never route code, HTTP, DNS or credentials.

Catalog metadata is not execution approval. No deployed gateway is approved in
this release; native feeds and directory reads do not depend on these helpers.
"""
from dataclasses import dataclass, field
from types import MappingProxyType
import re
from urllib.parse import urlsplit

SOURCE_COMMIT = '8e94b949479ba3295ee9653806f59b2be6559158'
RSSHUB_IMAGE = 'diygod/rsshub@sha256:1945d3162e0a6a38399bed540b623bbb06829ad3dc9160de7e7dfbaac60854ff'
LANGUAGES = ('any', 'python', 'javascript', 'typescript', 'rust', 'go', 'java', 'c',
             'ruby', 'swift', 'kotlin', 'css', 'html', 'dart', 'zig', 'php', 'shell')
SPOKEN_LANGUAGES = ('en', 'zh', 'ja', 'ko', 'de', 'fr', 'es', 'pt', 'ru')
SINCE = ('daily', 'weekly', 'monthly')
STATES = ('open', 'closed', 'all')
ISSUE_TEMPLATE = '/github/issue/:user/:repo/:state?/:labels?'
TRENDING_TEMPLATE = '/github/trending/:since/:language/:spoken_language?'
TEMPLATES = MappingProxyType({
    'twitter.user': {'path': '/twitter/user/:id', 'content_kind': 'article', 'required': ('id',),
                     'capabilities': ('config:TWITTER_AUTH_TOKEN', 'twitter.public_only'), 'parameters': ('id',)},
    'github.issue': {'path': ISSUE_TEMPLATE, 'content_kind': 'issue', 'required': ('user', 'repo'),
                     'capabilities': (), 'parameters': ('user', 'repo', 'state')},
    'github.trending': {'path': TRENDING_TEMPLATE, 'content_kind': 'repository', 'required': ('since', 'language'),
                       'capabilities': ('config:GITHUB_ACCESS_TOKEN',),
                       'parameters': ('since', 'language', 'spoken_language')},
})


class RouteError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never echo input/secret/URL in errors.


def _require(condition, code):
    if not condition:
        raise RouteError(code)


def _text(value):
    _require(isinstance(value, str) and 0 < len(value) <= 1024
        and all(32 < ord(c) < 127 for c in value) and not any(c in value for c in '%\\?#'), 'invalid_route_input')
    return value


def _user(value):
    value = _text(value)
    _require(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', value)
             and '--' not in value, 'invalid_github_user')
    return value


def _repo(value):
    value = _text(value)
    _require(re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', value) and value not in {'.', '..'}, 'invalid_github_repo')
    return value


@dataclass(frozen=True)
class RouteInstance:
    template_id: str
    alias: str
    parameters: tuple

    def public(self):
        spec = TEMPLATES[self.template_id]
        return {'template_id': self.template_id, 'alias': self.alias,
                'parameters': dict(self.parameters), 'content_kind': spec['content_kind'],
                'capability_requirements': list(spec['capabilities']), 'executable': False}


def render_route(template_id, parameters):
    _require(isinstance(template_id, str) and template_id in TEMPLATES, 'unsupported_route')
    _require(isinstance(parameters, dict), 'invalid_route_parameters')
    spec = TEMPLATES[template_id]
    # labels/query/global RSSHub options are deliberately outside this reviewed
    # subset. No parameter is interpreted as a URL, header, proxy or secret.
    _require(set(parameters) <= set(spec['parameters']), 'unsupported_route_parameter')
    _require(all(key in parameters for key in spec['required']), 'missing_route_parameter')
    values = {key: _text(value) for key, value in parameters.items()}
    if template_id == 'twitter.user':
        handle=values['id']
        _require(re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle), 'invalid_twitter_user')
        path='/twitter/user/'+handle.lower()
        canonical={'id':handle.lower()}
    elif template_id == 'github.issue':
        user, repo = _user(values['user']), _repo(values['repo'])
        state = values.get('state', 'open')
        _require(state in STATES, 'invalid_issue_state')
        path = f'/github/issue/{user}/{repo}/{state}'
        canonical = {'user': user, 'repo': repo, 'state': state}
    else:
        _require(values['since'] in SINCE, 'invalid_trending_since')
        _require(values['language'] in LANGUAGES, 'unsupported_trending_language')
        spoken = values.get('spoken_language')
        _require(spoken is None or spoken in SPOKEN_LANGUAGES, 'unsupported_spoken_language')
        path = '/github/trending/' + values['since'] + '/' + values['language']
        canonical = {'since': values['since'], 'language': values['language']}
        if spoken:
            path += '/' + spoken
            canonical['spoken_language'] = spoken
    return RouteInstance(template_id, 'rsshub:/' + path, tuple(canonical.items()))


def parse_alias(value):
    value = _text(value)
    if value.lower().startswith('rsshub://twitter/'):
        parsed=urlsplit(value)
        _require(parsed.netloc=='twitter' and not parsed.query and not parsed.fragment,'invalid_route_alias')
        parts=parsed.path.split('/')
        _require(len(parts)==3 and parts[1]=='user','unsupported_route')
        return render_route('twitter.user',{'id':parts[2]})
    _require(value.startswith('rsshub://github/'), 'unsupported_route')
    parsed = urlsplit(value)
    _require(parsed.scheme == 'rsshub' and parsed.netloc == 'github'
        and not parsed.query and not parsed.fragment, 'invalid_route_alias')
    parts = parsed.path.split('/')
    if len(parts) in {4, 5} and parts[1] == 'issue':
        parameters = dict(user=parts[2], repo=parts[3])
        if len(parts) == 5:
            parameters['state'] = parts[4]
        return render_route('github.issue', parameters)
    if len(parts) in {4, 5} and parts[1] == 'trending':
        parameters = dict(since=parts[2], language=parts[3])
        if len(parts) == 5:
            parameters['spoken_language'] = parts[4]
        return render_route('github.trending', parameters)
    raise RouteError('unsupported_route')


def _origin(value):
    value = _text(value)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        _require(parsed.scheme == 'https' and host and parsed.netloc in {host, host + ':443'}
            and parsed.path in {'', '/'} and parsed.port in {None, 443}
            and parsed.username is None and parsed.password is None, 'invalid_gateway_origin')
        _require(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+', host)
            and not host.rsplit('.', 1)[-1].isdigit()
            and not host.endswith(('.local', '.localhost', '.internal', '.lan', '.arpa', '.test', '.invalid')),
            'invalid_gateway_origin')
    except ValueError:
        raise RouteError('invalid_gateway_origin') from None
    return 'https://' + host


@dataclass(frozen=True)
class GatewayConfig:
    origin: str
    enabled: bool = False
    secret_ref: str = field(default='rsshub_gateway_basic_auth', repr=False)
    # Even a valid repository name is not proof of public access. Service tokens
    # must be public-only and each issue repository explicitly approved.
    approved_repositories: tuple = ()
    image: str = RSSHUB_IMAGE
    runtime_verified: bool = False
    runtime_version: int = 0
    approved_routes: tuple = ()
    verified_capabilities: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, 'origin', _origin(self.origin))
        _require(type(self.enabled) is bool and self.image == RSSHUB_IMAGE, 'invalid_gateway_config')
        _require(isinstance(self.secret_ref, str) and re.fullmatch(r'rsshub_[a-z0-9_]{1,100}', self.secret_ref), 'invalid_gateway_config')
        _require(isinstance(self.approved_repositories, tuple), 'invalid_gateway_config')
        for repository in self.approved_repositories:
            _require(isinstance(repository, tuple) and len(repository) == 2, 'invalid_gateway_config')
            _user(repository[0]); _repo(repository[1])


# A reviewed deployment may populate this only after real DNS/TLS/public hairpin,
# private-network/redirect refusal, secret/log/DTO/OPML isolation, token scope and
# actual route-object evidence exist for this fixed source and image. Empty now.
LIVE_APPROVALS = MappingProxyType({})


def gateway_target(alias, config):
    """Server-only candidate URL; a plan is not permission to fetch it."""
    _require(isinstance(config, GatewayConfig), 'gateway_disabled')
    route = parse_alias(alias)
    if route.template_id == 'github.issue':
        values = dict(route.parameters)
        _require((values['user'], values['repo']) in config.approved_repositories, 'unapproved_repository')
    return config.origin + '/' + route.alias.removeprefix('rsshub://')


def match_gateway_target(url, config):
    """Exact HTTPS origin AND canonical reviewed route/params; no DNS request."""
    _require(isinstance(config, GatewayConfig), 'gateway_disabled')
    url = _text(url)
    parsed = urlsplit(url)
    _require(parsed.scheme == 'https' and parsed.netloc == config.origin.removeprefix('https://')
             and not parsed.query and not parsed.fragment, 'unapproved_gateway_origin')
    route = parse_alias('rsshub:/' + parsed.path)
    _require(gateway_target(route.alias, config) == url, 'noncanonical_gateway_route')
    return route


@dataclass(frozen=True)
class GatewayRequest:
    alias: str
    feed_url: str = field(repr=False)
    secret_ref: str = field(repr=False)
    follow_redirects: bool = False

    def public(self):
        return parse_alias(self.alias).public()


def gateway_request(url, config):
    """Future adapter handoff, no secret loading/network; currently fail closed.

    The privileged adapter must load only this fixed reference, set Feed Basic
    Auth and prohibit publisher redirects. Existing EngineAdapter lacks that
    publisher no-redirect/auth extension, so no approval is shipped in this task.
    """
    route = match_gateway_target(url, config)
    _require(config.enabled, 'gateway_disabled')
    if (config.runtime_verified is True and type(config.runtime_version) is int and config.runtime_version>0
            and route.template_id in config.approved_routes
            and set(route.public()['capability_requirements'])<=set(config.verified_capabilities)):
        return GatewayRequest(route.alias,url,config.secret_ref)
    approved = LIVE_APPROVALS.get((config.origin, route.template_id))
    _require(approved == (SOURCE_COMMIT, config.image), 'gateway_unverified')
    return GatewayRequest(route.alias, url, config.secret_ref)


def template_metadata():
    return [{'template_id': key, 'public_url': spec['path'], 'kind': 'route_template',
             'required_parameters': list(spec['required']),
             'capability_requirements': list(spec['capabilities']),
             'content_kind': spec['content_kind'], 'executable': False}
            for key, spec in TEMPLATES.items()]
