"""Bounded evidence fencing for queued and reviewed channel classification."""
from api.models import Source
from api.services.channel_topics import digest, evidence_for


def evidence_is_current(evidence):
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 40:
        return False
    if any(not isinstance(item, dict) or type(item.get('source_id')) is not int for item in evidence):
        return False
    ids = [item['source_id'] for item in evidence]
    if len(ids) != len(set(ids)):
        return False
    sources = list(Source.objects.filter(pk__in=ids).order_by('pk'))
    if len(sources) != len(ids):
        return False
    live = [evidence_for(source) for source in sources]
    recorded = sorted(evidence, key=lambda item: item['source_id'])
    # Old queued snapshots without the new title/version fields fail closed.
    return digest(live) == digest(recorded)
