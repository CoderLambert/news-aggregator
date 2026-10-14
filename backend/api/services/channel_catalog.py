"""Explicit catalog initialization; directory reads never create sources."""
from api.services.source_policy import policy_for_key, policy_for_name
from api.services.source_registry import runtime_registry

# Known publisher metadata, not a language/market inference. Unknown countries
# remain empty; country of a Chinese edition is not automatically China.
PUBLISHER_COUNTRIES = {'bbc': 'UK', 'bbc_health': 'UK', 'deepmind': 'UK', 'mistral': 'FR',
                       'leiphone': 'CN', 'jiqizhixin': 'CN', 'sanliu_kr': 'CN',
                       'ithome_energy': 'CN', 'ifanr_energy': 'CN'}


def subscription_status(source):
    policy = policy_for_name(source.name)
    if not policy:
        return 'inactive', 'unregistered_source'
    if policy.unsupported_reason or policy.key not in runtime_registry():
        return 'inactive', policy.unsupported_reason or 'unregistered_source'
    return 'active', ''


def catalog_defaults(policy):
    return {
        'url': {'openai_blog': 'https://openai.com/news', 'github': 'https://github.com/trending', 'venturebeat_ai': 'https://venturebeat.com/category/ai/', 'ars_technica_ai': 'https://arstechnica.com/tag/artificial-intelligence/'}.get(policy.key, 'https://' + policy.domains[0]),
        'language': policy.language,
        'region': policy.region,
        'country': PUBLISHER_COUNTRIES.get(policy.key, ''),
        'source_type': 'discussion' if policy.key in {'hackernews', 'devto'} else (
            'aggregator' if policy.key in {'github', 'arxiv_ai', 'producthunt'} else 'news'),
        'description': policy.description or f'{policy.name} 的资讯频道',
    }


def sync_channel_catalog():
    from api.models import Source
    from api.services.sector_feeds import SECTOR_KEYS
    for key in dict.fromkeys([*runtime_registry(), *sorted(SECTOR_KEYS)]):
        policy = policy_for_key(key)
        # Explicit/manual existing values are never overwritten by a GET or sync.
        Source.objects.get_or_create(name=policy.name, defaults=catalog_defaults(policy))
