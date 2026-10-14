"""Merged read-only registry for code and administrator-maintained sources."""
from dataclasses import dataclass

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
