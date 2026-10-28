"""RSS-backed channel catalog. Reads never register static collector sources."""
PUBLISHER_COUNTRIES = {'bbc': 'UK', 'bbc_health': 'UK', 'deepmind': 'UK', 'mistral': 'FR',
                       'leiphone': 'CN', 'jiqizhixin': 'CN', 'sanliu_kr': 'CN',
                       'ithome_energy': 'CN', 'ifanr_energy': 'CN'}


def current_feed_links(source):
    from api.rss.subscriptions import engine_identity
    instance, account = engine_identity()
    return source.feed_links.filter(enabled=True, association_policy={'version': 1, 'mode': 'all'},
        binding__engine_instance_uuid=instance, binding__account_id=account)


def _publication_status(source):
    publication = getattr(source, 'publication', None)
    if publication is None or publication.owner == 'legacy':
        from api.services.source_policy import policy_for_name
        policy = policy_for_name(source.name)
        return 'inactive', (policy.unsupported_reason if policy else '') or 'legacy_ingestion_retired'
    if publication.owner != 'miniflux':
        return 'inactive', publication.pause_reason or 'paused'
    return None


def _link_verified(link):
    binding = link.binding
    return (binding.engine_feed_id is not None and binding.connection_state in ('ready', 'paused')
            and binding.applied_policy_version == binding.policy_version)


def _status_from_links(links, blocked):
    from api.rss.feed_policy import assert_binding_policy
    from api.rss.operations import OperationError
    # A paused physical feed remains subscribable: subscribing reconciles its references.
    verified = [link for link in links if _link_verified(link)]
    if verified:
        for link in verified:
            if link.binding_id in blocked:
                continue
            try:
                assert_binding_policy(link.binding)
            except OperationError:
                continue
            return 'active', ''
        return 'inactive', 'source_policy_not_permitted'
    if links:
        binding = links[0].binding
        if binding.last_error and any(word in binding.last_error for word in ('unknown', 'unproven')):
            return 'inactive', 'feed_outcome_unknown'
        return 'inactive', {'error': 'feed_error', 'unknown': 'feed_outcome_unknown'}.get(
            binding.connection_state, 'feed_verification_pending')
    return 'inactive', 'unconfigured_source'


def _compute_subscription_status(source):
    early = _publication_status(source)
    if early is not None:
        return early
    from api.rss.operations import unresolved_control_binding_ids
    from api.rss.subscriptions import EngineUnavailable
    try:
        links = list(current_feed_links(source).select_related('binding').order_by('pk'))
    except EngineUnavailable:
        return 'inactive', 'engine_unavailable'
    verified_ids = [link.binding_id for link in links if _link_verified(link)]
    blocked = unresolved_control_binding_ids(verified_ids) if verified_ids else set()
    return _status_from_links(links, blocked)


def subscription_status(source):
    cached = getattr(source, '_rss_subscription_status', None)
    if cached is not None:
        return cached
    return _compute_subscription_status(source)


def prime_subscription_status(sources):
    """Attach catalog status for one response without a per-source link scan.

    The tuple is stored on these instances only. ``subscription_status`` still
    re-reads the database when a caller has not primed the instance.
    """
    if not sources:
        return
    pending = []
    for source in sources:
        if getattr(source, '_rss_subscription_status', None) is not None:
            continue
        early = _publication_status(source)
        if early is not None:
            source._rss_subscription_status = early
        else:
            pending.append(source)
    if not pending:
        return
    from api.rss.models import SourceFeedLink
    from api.rss.operations import unresolved_control_binding_ids
    from api.rss.subscriptions import EngineUnavailable, engine_identity
    try:
        instance, account = engine_identity()
    except EngineUnavailable:
        for source in pending:
            source._rss_subscription_status = ('inactive', 'engine_unavailable')
        return
    grouped = {}
    verified_ids = []
    links = SourceFeedLink.objects.filter(
        source_id__in=[source.pk for source in pending], enabled=True,
        association_policy={'version': 1, 'mode': 'all'},
        binding__engine_instance_uuid=instance, binding__account_id=account,
    ).select_related('binding').order_by('pk')
    for link in links:
        grouped.setdefault(link.source_id, []).append(link)
        if _link_verified(link):
            verified_ids.append(link.binding_id)
    blocked = unresolved_control_binding_ids(verified_ids)
    from api.services.source_policy import source_config_snapshot
    with source_config_snapshot():
        for source in pending:
            source._rss_subscription_status = _status_from_links(grouped.get(source.pk, []), blocked)


def rss_status(source):
    active, reason = subscription_status(source)
    if active == 'active':
        return 'ready'
    return {'legacy_ingestion_retired': 'retired', 'unconfigured_source': 'unconfigured', 'engine_unavailable': 'unconfigured',
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
