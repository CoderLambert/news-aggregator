"""Server-owned feed admission. Names, catalog labels and tokens grant nothing.

No publisher HTTP or DNS. All restrictions apply before engine dispatch; a check
cannot revoke an already dispatched remote request. Content completeness remains
unknown independently of the mode selected here.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
import re
from urllib.parse import urlsplit

from django.conf import settings

from api.services.source_policy import (POLICIES, all_policies, config_for_source, iter_source_configs,
    policy_for_url, policy_for_name, policy_from_config, retired_policy_for_url)

BODY_POLICIES = frozenset({'standard', 'public_feed', 'public_rss', 'official_html', 'regulatory_data'})
SUMMARY_POLICIES = frozenset({'summary_only', 'rss_summary_only'})
ALL = {'version': 1, 'mode': 'all'}
_catalog_snapshot = ContextVar('feed_policy_catalog_snapshot', default=None)


@contextmanager
def catalog_policy_snapshot():
    """Reuse pure URL/policy work only inside one read-only catalog response.

    Never retain admission decisions across requests or use this around writes.
    SourceConfig rows are captured by the caller's source_config_snapshot.
    """
    token = _catalog_snapshot.set(({}, {}))
    try:
        yield
    finally:
        _catalog_snapshot.reset(token)

# T27 public Miniflux feed-mode samples, two entries per exact endpoint (2026-10-16).
# This is a mode decision, NOT proof every entry is complete or a verified badge.
# Evidence: ops/rss/feed-policy/native-samples.json; never inferred from body_fields.
# Additional two-entry feed-mode samples: native-default-samples-20261020.json.
NATIVE_FEEDS = frozenset({'https://jvns.ca/atom.xml', 'https://webkit.org/feed/',
    'https://www.ruanyifeng.com/blog/atom.xml', 'https://v8.dev/blog.atom',
    'https://hacks.mozilla.org/feed/', 'https://github.blog/feed/'})
MIXED_HOSTS = frozenset({'news.ycombinator.com', 'hnrss.org', 'www.hnrss.org'})


@dataclass(frozen=True)
class FeedAdmission:
    desired_mode: str
    reading_policy: str
    content_kind: str
    full_content_allowed: bool
    reason: str


def full_content_enabled():
    from api.rss.operations import OperationError
    enabled = getattr(settings, 'RSS_FULL_CONTENT_ENABLED', False)
    if type(enabled) is not bool:
        raise OperationError('invalid_policy')
    return enabled


def _canonical(value):
    from api.rss.operations import canonicalize_feed_url
    snapshot = _catalog_snapshot.get()
    if snapshot is None:
        return canonicalize_feed_url(value)
    canonical, _ = snapshot
    if value not in canonical:
        canonical[value] = canonicalize_feed_url(value)
    return canonical[value]


def is_wechat_article_url(url):
    """Identify a WeChat publisher URL without granting collection permission."""
    return (urlsplit(url).hostname or '').lower().rstrip('.') == 'mp.weixin.qq.com'


def is_wechat_feed_url(url):
    """Identify WeChat2RSS bridges so their embedded body remains authoritative.

    This selects a more restrictive mode. It grants no source, network, reading,
    or public visibility permission to a matching hostname.
    """
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    return host == 'wechat2rss.com' or host.startswith('wechat2rss.')


def _restricted(policy):
    return (policy.unsupported_reason or not policy.html_allowed or policy.content_kind != 'article'
            or policy.reading_policy not in BODY_POLICIES or policy.keyword_filter)


def _host_matches(host, domain, *, restrictive=False):
    host = host.lower().rstrip('.').encode('idna').decode('ascii')
    domain = domain.lower().rstrip('.').encode('idna').decode('ascii')
    root = domain.removeprefix('www.')
    return host == domain or (restrictive and (host == root or host.endswith('.' + root)))


def known_feed_content_kind(feed_url):
    """Metadata fallback only; no DB, settings or collection permission check.

    A newly restricted source must not make a whole sync page fail during type
    classification. Linked SourceConfig and the existing page fence stay primary.
    """
    host = urlsplit(feed_url).hostname or ''
    if host in MIXED_HOSTS:
        return 'discussion'
    for policy in POLICIES.values():
        if policy.feed_url == feed_url or any(_host_matches(host, domain, restrictive=_restricted(policy))
                                              for domain in policy.domains):
            if policy.content_kind != 'article':
                return policy.content_kind
    policy = policy_for_url(feed_url)
    return policy.content_kind if policy else 'article'


def _policies_for_url(url):
    snapshot = _catalog_snapshot.get()
    if snapshot is None:
        return _read_policies_for_url(url)
    _, policies = snapshot
    if url not in policies:
        policies[url] = tuple(_read_policies_for_url(url))
    # Callers add binding-specific restrictions; never mutate the cached tuple.
    return list(policies[url])


def _read_policies_for_url(url):
    """Exact feed URLs cover separate syndication hosts; host rules add limits."""
    from api.rss.operations import OperationError
    policies = []
    for policy in all_policies():
        host_match = any(_host_matches(urlsplit(url).hostname or '', domain, restrictive=_restricted(policy))
                         for domain in policy.domains)
        exact = False
        if policy.feed_url:
            try:
                exact = _canonical(policy.feed_url) == url
            except OperationError:
                exact = False
        if exact or host_match:
            policies.append(policy)
    for policy in (policy_for_url(url), retired_policy_for_url(url)):
        if policy and policy not in policies:
            policies.append(policy)
    # DB contracts with a built-in source key are omitted from all_policies by
    # the legacy registry. They still restrict direct/token/catalog admission.
    for config in iter_source_configs():
        matched = False
        config_policy = policy_from_config(config)
        for endpoint in config.endpoints.all():
            matched |= any(_host_matches(urlsplit(url).hostname or '', domain,
                restrictive=_restricted(config_policy) or not config.approval_is_current) for domain in endpoint.allowed_domains)
            try:
                matched |= _canonical(endpoint.url) == url
            except OperationError:
                continue
        if matched:
            if config.status not in {'approved', 'enabled'} or not config.approval_is_current:
                raise OperationError('source_collection_not_permitted')
            policies.append(config_policy)
    return policies


def _decide(url, policies, *, publications=()):
    from api.rss.operations import OperationError
    if any(p.unsupported_reason for p in policies):
        raise OperationError('source_collection_not_permitted')
    if any(p.keyword_filter for p in policies):
        # A generic feed cannot silently lose an existing selection contract.
        raise OperationError('unsupported_association_policy')
    if any(p.reading_policy not in BODY_POLICIES | SUMMARY_POLICIES for p in policies):
        raise OperationError('source_collection_not_permitted')
    if any(p.reading_policy not in BODY_POLICIES | SUMMARY_POLICIES for p in publications):
        raise OperationError('source_collection_not_permitted')
    summary = any(p.reading_policy in SUMMARY_POLICIES for p in (*policies, *publications))
    mixed = urlsplit(url).hostname in MIXED_HOSTS
    kinds = [p.content_kind for p in policies if p.content_kind != 'article']
    kind = 'discussion' if mixed else kinds[0] if kinds else 'article'
    allowed = not (summary or mixed or kinds or any(not p.html_allowed for p in policies))
    wechat = is_wechat_feed_url(url)
    native = wechat or url in NATIVE_FEEDS
    reason = ('restricted' if summary else 'mixed_external_links' if mixed else
              'non_article' if kinds else 'html_not_permitted' if not allowed else
              'wechat_feed_only' if wechat else 'observed_native_feed' if native else 'ordinary_public_article')
    # Existing server setting and the admin mode endpoint are the opt-out. No
    # client rule/CSS input and no subscriber may change a shared mode implicitly.
    mode = getattr(settings, 'RSS_DEFAULT_FEED_MODE', 'full_content')
    if mode not in {'feed', 'full_content'}:
        raise OperationError('invalid_policy')
    mode = mode if allowed and not native and full_content_enabled() else 'feed'
    if summary or mixed or kinds:
        reading = 'rss_summary_only'
    elif policies:
        # Preserve explicit known restrictions, even when HTML is disallowed.
        reading = policies[0].reading_policy
    else:
        reading = 'public_feed' if native else 'standard'
    if native and not summary:
        reading = 'public_feed'
    return FeedAdmission(mode, reading, kind, allowed and not wechat, reason)


def _gateway_policy(url,decision):
    from api.rss.rsshub import selection
    chosen=selection(url)
    if chosen is None: return decision
    from api.rss.rsshub_url import metadata
    template,kind,_=metadata(chosen.alias)
    reading=decision.reading_policy if decision.reading_policy in SUMMARY_POLICIES else ('public_feed' if kind=='article' and template else 'rss_summary_only')
    return FeedAdmission('feed',reading,kind,False,'rsshub_feed_only')


def approved_feed_policy(feed_url):
    url = _canonical(feed_url)
    return _gateway_policy(url,_decide(url, _policies_for_url(url)))


def assert_binding_policy(binding, *, desired_mode=None, enabled=True, source_links=None):
    """Intersection of feed URL, every associated source and current publication.

    Disabling an existing physical feed must always remain possible. A disabled
    mutation cannot start collection, regardless of a now-retired source policy.
    """
    from api.rss.operations import OperationError
    if not enabled:
        return None
    url = _canonical(binding.canonical_feed_url)
    policies = _policies_for_url(url)
    publications = []
    # Catalog reads may supply a freshly fetched batch including *all* links,
    # even disabled/private ones. Mutation callers always read current relations.
    if source_links is None:
        source_links = binding.source_links.select_related('source__publication')
    for link in source_links:
        if link.association_policy != ALL:
            raise OperationError('unsupported_association_policy')
        publication = getattr(link.source, 'publication', None)
        if publication is None:
            raise OperationError('source_collection_not_permitted')
        publications.append(publication)
        # The persisted source name may add a restriction, never grant an
        # exception to the URL policy. Random display_name cannot bypass either.
        policies.extend(_policies_for_url(link.source.url))
        named = policy_for_name(link.source.name)
        if named:
            policies.append(named)
        config = config_for_source(link.source_id)
        if config:
            if not config.approval_is_current or config.status not in {'approved', 'enabled'}:
                raise OperationError('source_collection_not_permitted')
            policies.append(policy_from_config(config))
    from api.rss.rsshub import selection
    if binding.rsshub_alias:
        selected=selection(binding.rsshub_alias)
        if selected.url!=binding.canonical_feed_url or selected.version!=binding.rsshub_gateway_version:
            raise OperationError('rsshub_configuration_changed')
    decision = _gateway_policy(url,_decide(url, policies, publications=publications))
    if (desired_mode or binding.desired_mode) == 'full_content':
        if not full_content_enabled():
            raise OperationError('full_content_disabled')
        if not decision.full_content_allowed:
            raise OperationError('full_content_policy_not_permitted')
    return decision


def assert_article_fetch_allowed(url):
    """Explicit repair also needs the target publisher's current permission."""
    from api.rss.operations import OperationError
    from api.services.article_identity import normalize_article_url
    if not full_content_enabled():
        raise OperationError('full_content_disabled')
    # C02 permits public HTTP article identities; only subscriptions require HTTPS.
    url = normalize_article_url(url, require_article=False)
    if is_wechat_article_url(url):
        raise OperationError('wechat_feed_only')
    decision = _decide(url, _policies_for_url(url))
    if not decision.full_content_allowed:
        raise OperationError('full_content_policy_not_permitted')


def required_entry_url_block_rules(*, include_database=False, include_html=False):
    """Pinned Miniflux EntryURL rule. Blocks entire entries, not just bodies.

    Default is pure/static for SDK construction. The main worker thread adds a
    current DB snapshot; the network thread never loads policy models. Direct
    publisher URLs only: Miniflux rewrites and HTTP redirects remain a live gate.
    """
    policies = list(POLICIES.values())
    domains = set(MIXED_HOSTS) if include_html else set()
    if include_database:
        from api.models import SourceConfig
        for config in SourceConfig.objects.prefetch_related('endpoints'):
            policy = policy_from_config(config)
            policies.append(policy)
            denied = (config.status not in {'approved', 'enabled'} or policy.unsupported_reason or not config.approval_is_current or
                (include_html and (not policy.html_allowed or policy.content_kind != 'article'
                                   or policy.reading_policy not in BODY_POLICIES)))
            if denied:
                # A disabled endpoint does not erase a publisher restriction.
                for endpoint in config.endpoints.all():
                    domains.update(endpoint.allowed_domains)
                    domains.add(urlsplit(endpoint.url).hostname)
    for policy in policies:
        if (policy.unsupported_reason or not policy.summary_allowed or (include_html and
                (policy.keyword_filter or not policy.html_allowed or policy.content_kind != 'article'
                 or policy.reading_policy not in BODY_POLICIES))):
            domains.update(policy.domains)
            if policy.feed_url:
                domains.add(urlsplit(policy.feed_url).hostname)
    roots = set()
    for domain in domains:
        if domain:
            roots.add(domain.lower().rstrip('.').removeprefix('www.').encode('idna').decode('ascii'))
    # RE2 supports (?i) and non-capturing groups, but no lookaround. Authority
    # boundaries prevent evilreuters.com/reuters.com.evil/path text false matches.
    hosts = '|'.join(re.escape(domain) for domain in sorted(roots))
    return r'EntryURL=(?i)^https?://(?:[^/?#@]+@)?(?:[a-z0-9-]+\.)*(?:' + hosts + r')\.?(?::[0-9]+)?(?:[/?#]|$)'
