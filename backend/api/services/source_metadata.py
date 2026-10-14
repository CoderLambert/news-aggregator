"""Country is explicit publisher metadata, never a synonym for feed language."""
# Only existing reviewed publisher identities with an explicit country are
# populated. An unknown publisher stays unknown; a Chinese edition is not
# evidence that its publisher is based in China. GB is the ISO country code.
REVIEWED_PUBLISHER_COUNTRIES = {
    'bbc': 'GB', 'bbc_health': 'GB', 'deepmind': 'GB',
    'mistral': 'FR', 'fda_news': 'US', 'nih_news': 'US',
}


def publisher_country(source_key):
    return REVIEWED_PUBLISHER_COUNTRIES.get(source_key, '')


def primary_publication_evidence(news):
    from api.services.source_policy import policy_for_name
    policy = policy_for_name(news.source.name)
    mappings = list(news.source_items.all())
    primary = [item for item in mappings if policy is not None and item.source_key == policy.key]
    # Legacy articles with no source receipt cannot establish whether the date
    # was supplied or synthesized. Preserve the date but label its provenance.
    if not primary:
        return {'inferred': True, 'origin': 'unknown'}
    reliable = any(item.metadata.get('publish_time_inferred') is False
                   and bool(item.metadata.get('source_publish_time')) for item in primary)
    return {'inferred': not reliable, 'origin': 'publisher' if reliable else 'collected'}
