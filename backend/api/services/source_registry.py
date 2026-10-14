"""Merged read-only registry for code and administrator-maintained sources."""
from dataclasses import asdict, dataclass

from api.services.source_policy import POLICIES, policy_for_key


CODE_SPIDERS = {
    'bbc': 'bbc', 'reuters': 'reuters', 'hackernews': 'hackernews', 'github': 'github',
    'devto': 'devto', 'techcrunch': 'techcrunch', 'producthunt': 'producthunt', 'infoq': 'infoq',
    'css_tricks': 'css_tricks', 'webdev': 'webdev', 'chrome_dev': 'chrome_dev',
    'smashing_magazine': 'smashing_magazine', 'react_blog': 'react_blog', 'svelte_blog': 'svelte_blog',
    'angular_blog': 'angular_blog', 'webkit': 'webkit', 'v8': 'v8', 'mozilla_hacks': 'mozilla_hacks',
    'frontend_focus': 'frontend_focus', 'openai_blog': 'openai_blog', 'anthropic': 'anthropic',
    'deepmind': 'deepmind', 'meta_ai': 'meta_ai', 'mistral': 'mistral',
    'venturebeat_ai': 'venturebeat_ai', 'ars_technica_ai': 'ars_technica_ai',
    'mit_tech_review_ai': 'mit_tech_review_ai', 'arxiv_ai': 'arxiv_ai',
    'jiqizhixin': 'jiqizhixin', 'leiphone': 'leiphone', 'sanliu_kr': 'sanliu_kr',
}
from api.services.sector_feeds import SECTOR_KEYS
CODE_SPIDERS.update({key: key for key in SECTOR_KEYS})
CODE_SPIDERS = {
    key: spider for key, spider in CODE_SPIDERS.items()
    if key in POLICIES and not POLICIES[key].unsupported_reason
}


@dataclass(frozen=True)
class RuntimeSource:
    source_key: str
    spider: str
    maintenance: str
    display_name: str
    config_version: int
    status: str

    @property
    def runnable(self):
        return self.maintenance == 'code' or self.status in {'approved', 'enabled'}


def runtime_registry(*, include_unavailable=False):
    registry = {
        key: RuntimeSource(key, spider, 'code', POLICIES[key].name, 1, 'enabled')
        for key, spider in CODE_SPIDERS.items()
    }
    try:
        from api.models import SourceConfig
        configs = SourceConfig.objects.all()
        if not include_unavailable:
            configs = configs.filter(status__in=['approved', 'enabled'])
        for config in configs:
            # Database configuration can never shadow a reviewed code source.
            if config.source_key in registry or config.source_key in POLICIES:
                continue
            registry[config.source_key] = RuntimeSource(
                config.source_key, 'dynamic_source', 'database', config.channel_name,
                config.config_version, config.status,
            )
    except Exception as error:
        from django.core.exceptions import AppRegistryNotReady
        from django.db import OperationalError, ProgrammingError
        if not isinstance(error, (AppRegistryNotReady, OperationalError, ProgrammingError)):
            raise
    return registry


def registered_source_keys(*, include_unavailable=False):
    return tuple(runtime_registry(include_unavailable=include_unavailable))


def runtime_source(source_key, *, include_unavailable=False):
    return runtime_registry(include_unavailable=include_unavailable).get(source_key)


def source_is_supported(source_key):
    entry = runtime_source(source_key, include_unavailable=True)
    policy = policy_for_key(source_key)
    return bool(entry and entry.runnable and policy and not policy.unsupported_reason)


def source_snapshot(source_key):
    entry = runtime_source(source_key)
    if entry is None:
        raise ValueError('unknown_source')
    if entry.maintenance == 'code':
        return {}
    from api.models import SourceConfig
    config = SourceConfig.objects.select_related('category').prefetch_related('endpoints').get(pk=source_key)
    if not config.probe_is_current or not config.approval_is_current or config.status not in {'approved', 'enabled'}:
        raise ValueError('source_not_approved')
    endpoint = config.endpoints.filter(enabled=True).order_by('priority', 'id').first()
    if endpoint is None:
        raise ValueError('missing_endpoint')
    policy = policy_for_key(source_key)
    return {
        'schema_version': 1,
        'source_key': source_key,
        'config_version': config.config_version,
        'policy': asdict(policy),
        'endpoint': {
            'kind': endpoint.kind, 'url': endpoint.url,
            'allowed_domains': endpoint.allowed_domains, 'priority': endpoint.priority,
            'parser_config': endpoint.parser_config,
            'conditional_requests': endpoint.conditional_requests,
            'request_interval_seconds': endpoint.request_interval_seconds,
            'max_response_bytes': endpoint.max_response_bytes,
            'max_pages': endpoint.max_pages, 'max_items': endpoint.max_items,
        },
    }
