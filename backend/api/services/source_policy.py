"""Reviewed source contracts. Enabling flags never grants an unknown contract."""
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SourcePolicy:
    key: str
    name: str
    domains: tuple[str, ...]
    feed_url: str = ''
    body_fields: tuple[str, ...] = ()
    summary_allowed: bool = True
    content_kind: str = 'article'
    html_allowed: bool = True
    unsupported_reason: str = ''
    contract_version: str = '1'
    poll_seconds: int = 3600
    request_interval: float = 3.0
    region: str = 'international'
    language: str = 'en'
    description: str = ''
    default_category: str = ''
    reading_policy: str = 'standard'
    keyword_filter: str = ''
    date_format: str = ''
    date_timezone: str = ''


# Body fields are explicitly approved per source, never inferred from their name.
POLICIES = {
    p.key: p for p in (
        SourcePolicy('devto', 'Dev.to', ('dev.to',), body_fields=('body_markdown', 'body_html'), request_interval=1.0),
        SourcePolicy('leiphone', '雷峰网', ('www.leiphone.com', 'leiphone.com'), 'https://www.leiphone.com/feed', ('description',), poll_seconds=1800, html_allowed=False, unsupported_reason='public_access_denied'),
        SourcePolicy('webkit', 'WebKit', ('webkit.org',), 'https://webkit.org/feed/', ('content:encoded',)),
        SourcePolicy('smashing_magazine', 'Smashing Magazine', ('www.smashingmagazine.com', 'smashingmagazine.com'), 'https://www.smashingmagazine.com/feed/', ('content:encoded',)),
        SourcePolicy('v8', 'V8', ('v8.dev',), 'https://v8.dev/blog.atom', ('atom:content',)),
        SourcePolicy('mozilla_hacks', 'Mozilla Hacks', ('hacks.mozilla.org',), 'https://hacks.mozilla.org/feed/', ('content:encoded',)),
        SourcePolicy('svelte_blog', 'Svelte Blog', ('svelte.dev',), 'https://svelte.dev/blog/rss.xml', ('description',)),
        SourcePolicy('angular_blog', 'Angular Blog', ('blog.angular.dev',), 'https://blog.angular.dev/feed', ('content:encoded',)),
        SourcePolicy('bbc', 'BBC', ('www.bbc.com', 'www.bbc.co.uk', 'bbc.com', 'bbc.co.uk'), 'https://feeds.bbci.co.uk/news/world/rss.xml', poll_seconds=1800),
        SourcePolicy('techcrunch', 'TechCrunch', ('techcrunch.com',), 'https://techcrunch.com/feed/', ('content.rendered',), poll_seconds=1800),
        SourcePolicy('css_tricks', 'CSS-Tricks', ('css-tricks.com',), 'https://css-tricks.com/feed/'),
        SourcePolicy('webdev', 'web.dev', ('web.dev',), 'https://web.dev/blog/feed.xml'),
        SourcePolicy('chrome_dev', 'Chrome Developers', ('developer.chrome.com',), 'https://developer.chrome.com/static/blog/feed.xml'),
        SourcePolicy('react_blog', 'React Blog', ('react.dev',), 'https://react.dev/rss.xml'),
        SourcePolicy('openai_blog', 'OpenAI Blog', ('openai.com',), 'https://openai.com/news/rss.xml'),
        SourcePolicy('deepmind', 'DeepMind', ('deepmind.google',), 'https://deepmind.google/blog/rss.xml'),
        SourcePolicy('infoq', 'InfoQ', ('www.infoq.com', 'infoq.com'), 'https://feed.infoq.com/news/', contract_version='2'),
        SourcePolicy('ars_technica_ai', 'Ars Technica AI', ('arstechnica.com',), 'https://arstechnica.com/tag/artificial-intelligence/feed/'),
        SourcePolicy('mit_tech_review_ai', 'MIT Tech Review AI', ('www.technologyreview.com', 'technologyreview.com'), 'https://www.technologyreview.com/feed/'),
        SourcePolicy('hackernews', 'Hacker News', ('news.ycombinator.com',), body_fields=('text',), content_kind='discussion', request_interval=0.5),
        SourcePolicy('github', 'GitHub Trending', ('github.com',), body_fields=('readme',), content_kind='readme'),
        SourcePolicy('arxiv_ai', 'arXiv', ('arxiv.org', 'export.arxiv.org'), 'https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL', content_kind='abstract', html_allowed=False, contract_version='2'),
        SourcePolicy('producthunt', 'ProductHunt', ('www.producthunt.com', 'producthunt.com'), 'https://www.producthunt.com/feed', content_kind='product', html_allowed=False),
        SourcePolicy('frontend_focus', 'Frontend Focus', ('frontendfoc.us',), 'https://frontendfoc.us/rss', ('content:encoded',), content_kind='newsletter'),
        SourcePolicy('anthropic', 'Anthropic', ('www.anthropic.com', 'anthropic.com')),
        SourcePolicy('meta_ai', 'Meta AI', ('ai.meta.com',), html_allowed=False, unsupported_reason='publisher_permission_required'),
        SourcePolicy('mistral', 'Mistral', ('mistral.ai',), 'https://mistral.ai/news/rss', contract_version='2'),
        SourcePolicy('venturebeat_ai', 'VentureBeat AI', ('venturebeat.com', 'www.venturebeat.com'), 'https://venturebeat.com/category/ai/feed/'),
        SourcePolicy('reuters', 'Reuters', ('www.reuters.com', 'reuters.com'), html_allowed=False, unsupported_reason='authorized_delivery_required'),
        SourcePolicy('jiqizhixin', '机器之心', ('www.jiqizhixin.com',), html_allowed=False, unsupported_reason='publisher_identity_unavailable'),
        SourcePolicy('sanliu_kr', '36氪', ('36kr.com',), html_allowed=False, unsupported_reason='invalid_feed_endpoint'),
    )
}


# Channel metadata is explicit: a Chinese edition can serve the domestic market.
from dataclasses import replace
for _key in ('leiphone', 'jiqizhixin', 'sanliu_kr'):
    POLICIES[_key] = replace(POLICIES[_key], region='domestic', language='zh')
from api.services.sector_feeds import sector_policies
POLICIES.update({policy.key: policy for policy in sector_policies(SourcePolicy)})

_RUNTIME_POLICIES = {}


def policy_for_url(url: str):
    host = (urlsplit(url).hostname or '').lower()
    return next((p for p in (*POLICIES.values(), *_RUNTIME_POLICIES.values()) if host in p.domains), None)


def policy_for_name(name: str):
    return next((p for p in (*POLICIES.values(), *_RUNTIME_POLICIES.values()) if p.name == name), None)


def policy_for_key(source_key: str):
    if source_key in _RUNTIME_POLICIES:
        return _RUNTIME_POLICIES[source_key]
    policy = POLICIES.get(source_key)
    if policy is not None:
        return policy
    try:
        from api.models import SourceConfig
        config = SourceConfig.objects.prefetch_related('endpoints').get(pk=source_key)
    except Exception as error:
        # Registry reads also happen during migration/bootstrap. Only suppress
        # database/app readiness failures; an absent row is simply unknown.
        from django.core.exceptions import AppRegistryNotReady
        from django.db import OperationalError, ProgrammingError
        from api.models import SourceConfig
        if isinstance(error, SourceConfig.DoesNotExist):
            return None
        if isinstance(error, (AppRegistryNotReady, OperationalError, ProgrammingError)):
            return None
        raise
    return policy_from_config(config)


def policy_from_config(config):
    endpoints = [endpoint for endpoint in config.endpoints.all() if endpoint.enabled]
    endpoint = min(endpoints, key=lambda value: (value.priority, value.pk)) if endpoints else None
    domains = tuple(dict.fromkeys(
        domain.lower().rstrip('.')
        for current in endpoints
        for domain in current.allowed_domains
        if isinstance(domain, str) and domain
    ))
    body_fields = ()
    if endpoint and endpoint.kind in {'rss', 'atom'} and config.feed_full_content_allowed:
        allowed = endpoint.parser_config.get('full_content_fields', [])
        body_fields = tuple(value for value in allowed if value in {'description', 'content:encoded', 'atom:content'})
    unavailable = config.unavailable_reason if config.status in {'blocked', 'unsupported'} else ''
    if config.status not in {'approved', 'enabled', 'blocked', 'unsupported'}:
        unavailable = 'source_not_approved'
    return SourcePolicy(
        key=config.source_key,
        name=config.channel_name,
        domains=domains,
        feed_url=endpoint.url if endpoint else '',
        body_fields=body_fields,
        summary_allowed=config.summary_allowed,
        content_kind=config.content_kind,
        html_allowed=bool(config.official_html_full_content_allowed and config.approval_is_current),
        unsupported_reason=unavailable,
        contract_version=str(config.config_version),
        poll_seconds=max(60, endpoint.request_interval_seconds if endpoint else 3600),
        request_interval=max(3.0, float(endpoint.request_interval_seconds if endpoint else 10)),
        region=config.region,
        language=config.language,
        description=f'{config.publisher_name} · {config.channel_name}',
        default_category=config.category.name,
        reading_policy='rss_summary_only' if config.reading_policy == 'summary_only' else config.reading_policy,
    )


def _database_policies(*, include_unavailable=True):
    policies = []
    try:
        from api.models import SourceConfig
        configs = SourceConfig.objects.select_related('category').prefetch_related('endpoints')
        if not include_unavailable:
            configs = configs.filter(status__in=['approved', 'enabled'])
        for config in configs:
            if config.source_key not in POLICIES and config.source_key not in _RUNTIME_POLICIES:
                policies.append(policy_from_config(config))
    except Exception as error:
        from django.core.exceptions import AppRegistryNotReady
        from django.db import OperationalError, ProgrammingError
        if not isinstance(error, (AppRegistryNotReady, OperationalError, ProgrammingError)):
            raise
    return tuple(policies)


def all_policies(*, include_unavailable=True):
    return (*POLICIES.values(), *_RUNTIME_POLICIES.values(),
            *_database_policies(include_unavailable=include_unavailable))


def retired_policy_for_url(url: str):
    """Reject retired publishers' aliases without granting new domain contracts."""
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    return next((p for p in POLICIES.values() if p.unsupported_reason and any(
        host == domain.removeprefix('www.') or host.endswith('.' + domain.removeprefix('www.'))
        for domain in p.domains
    )), None)
