"""Explicit catalog initialization; directory reads never create sources."""
from api.services.source_policy import policy_for_name, all_policies

# Known publisher metadata, not a language/market inference. Unknown countries
# remain empty; country of a Chinese edition is not automatically China.
PUBLISHER_COUNTRIES = {'bbc': 'UK', 'bbc_health': 'UK', 'deepmind': 'UK', 'mistral': 'FR',
                       'leiphone': 'CN', 'jiqizhixin': 'CN', 'sanliu_kr': 'CN',
                       'ithome_energy': 'CN', 'ifanr_energy': 'CN'}


def subscription_status(source):
    publication = getattr(source, 'publication', None)
    if publication is not None and publication.owner != 'legacy':
        if publication.owner == 'paused':
            return 'inactive', publication.pause_reason or 'paused'
        links = source.feed_links.filter(enabled=True)
        if links.filter(binding__connection_state='ready').exists():
            return 'active', ''
        return 'inactive', 'connecting' if links.exists() else 'unconfigured_source'
    policy = policy_for_name(source.name)
    return 'inactive', (policy.unsupported_reason if policy else '') or 'legacy_ingestion_retired'



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
    for policy in all_policies():
        if policy.unsupported_reason and policy.key not in SECTOR_KEYS:
            continue
        # Explicit/manual existing values are never overwritten by a GET or sync.
        Source.objects.get_or_create(name=policy.name, defaults=catalog_defaults(policy))
