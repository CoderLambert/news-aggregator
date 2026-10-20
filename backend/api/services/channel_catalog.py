"""RSS-backed channel catalog. Reads never register static collector sources."""
from django.db.models import F

PUBLISHER_COUNTRIES = {'bbc': 'UK', 'bbc_health': 'UK', 'deepmind': 'UK', 'mistral': 'FR',
                       'leiphone': 'CN', 'jiqizhixin': 'CN', 'sanliu_kr': 'CN',
                       'ithome_energy': 'CN', 'ifanr_energy': 'CN'}


def subscription_status(source):
    publication = getattr(source, 'publication', None)
    if publication is None or publication.owner == 'legacy':
        from api.services.source_policy import policy_for_name
        policy = policy_for_name(source.name)
        return 'inactive', (policy.unsupported_reason if policy else '') or 'legacy_ingestion_retired'
    if publication.owner != 'miniflux':
        return 'inactive', publication.pause_reason or 'paused'
    links = source.feed_links.filter(enabled=True, association_policy={'version': 1, 'mode': 'all'})
    verified = links.filter(binding__engine_feed_id__isnull=False,
        binding__connection_state__in=['ready', 'paused'],
        binding__applied_policy_version=F('binding__policy_version'))
    # A paused physical feed remains subscribable: subscribing reconciles its references.
    if verified.exists():
        from api.rss.feed_policy import assert_binding_policy
        from api.rss.operations import OperationError
        for link in verified.select_related('binding'):
            try:
                assert_binding_policy(link.binding)
            except OperationError:
                continue
            return 'active', ''
        return 'inactive', 'source_policy_not_permitted'
    binding = links.select_related('binding').order_by('pk').first()
    if binding:
        if binding.binding.last_error and any(word in binding.binding.last_error for word in ('unknown', 'unproven')):
            return 'inactive', 'feed_outcome_unknown'
        return 'inactive', {'error': 'feed_error', 'unknown': 'feed_outcome_unknown'}.get(
            binding.binding.connection_state, 'feed_verification_pending')
    return 'inactive', 'unconfigured_source'


def rss_status(source):
    active, reason = subscription_status(source)
    if active == 'active':
        return 'ready'
    return {'legacy_ingestion_retired': 'retired', 'unconfigured_source': 'unconfigured',
            'feed_error': 'error', 'feed_outcome_unknown': 'unknown',
            'feed_verification_pending': 'pending'}.get(reason, 'paused')


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
    # Retained command/import compatibility. Initialization is explicit and versioned.
    return 0


def catalog_sources(user, purpose='history'):
    from rest_framework.exceptions import ValidationError
    from api.rss.access import authorized_sources
    if purpose not in {'subscribe', 'history'}:
        raise ValidationError({'purpose': '请选择 subscribe 或 history。'})
    sources = authorized_sources(user)
    if purpose == 'subscribe':
        sources = sources.filter(publication__owner='miniflux', feed_links__enabled=True).distinct()
    return sources
