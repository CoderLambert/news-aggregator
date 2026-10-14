"""Bounded evidence snapshots for both public and personal classification."""
from api.models import Source
from api.services.channel_topics import evidence_for, digest


def current_evidence(source_ids):
    ids = sorted(set(source_ids))
    if len(ids) > 200:
        raise ValueError('too_many_sources')
    sources = list(Source.objects.filter(pk__in=ids).order_by('pk'))
    if len(sources) != len(ids):
        return None
    return [evidence_for(source) for source in sources]


def evidence_is_current(proposal):
    """Compare actual model input, including titles, not just catalog metadata."""
    current = current_evidence(proposal.source_ids)
    if current is None or len(current) != len(proposal.evidence):
        return False
    # Normalize order only, never discard unknown input fields or stale text.
    return digest(current) == digest(sorted(proposal.evidence, key=lambda item: item['source_id']))
