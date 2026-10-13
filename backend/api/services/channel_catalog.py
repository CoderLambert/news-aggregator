"""Explicit catalog initialization; directory reads never create sources."""
from api.services.source_policy import POLICIES, policy_for_name


def subscription_status(source):
    from api.management.commands.crawl import SPIDERS
    policy = policy_for_name(source.name)
    if not policy:
        return 'inactive', 'unregistered_source'
    if policy.unsupported_reason or policy.key not in SPIDERS:
        return 'inactive', policy.unsupported_reason or 'unregistered_source'
    return 'active', ''


def catalog_defaults(policy):
    return {
        'url': {'openai_blog': 'https://openai.com/news', 'github': 'https://github.com/trending', 'venturebeat_ai': 'https://venturebeat.com/category/ai/', 'ars_technica_ai': 'https://arstechnica.com/tag/artificial-intelligence/'}.get(policy.key, 'https://' + policy.domains[0]),
        'language': policy.language,
        'region': policy.region,
        'country': 'CN' if policy.region == 'domestic' else 'UK' if policy.key in {'bbc', 'deepmind'} else 'FR' if policy.key == 'mistral' else 'US',
        'source_type': 'discussion' if policy.key in {'hackernews', 'devto'} else (
            'aggregator' if policy.key in {'github', 'arxiv_ai', 'producthunt'} else 'news'),
        'description': policy.description or f'{policy.name} 的资讯频道',
    }


def sync_channel_catalog():
    from api.models import Source
    from api.management.commands.crawl import SPIDERS
    from api.services.sector_feeds import SECTOR_KEYS
    for key in dict.fromkeys([*SPIDERS, *sorted(SECTOR_KEYS)]):
        policy = POLICIES[key]
        Source.objects.get_or_create(name=policy.name, defaults=catalog_defaults(policy))
