"""Fair candidate selection and explicit bounds, independent of network execution."""
from urllib.parse import urlsplit
import os

from django.conf import settings


def bounded_setting(name, default, maximum=32):
    return max(1, min(int(getattr(settings, name, os.environ.get(name, default))), maximum))


def fair_candidates(queryset, owner_field, *, limit, served=None, order=('created_at', 'pk'), prune=True):
    """Select across owners BEFORE taking each owner's oldest work.

    A large oldest batch must not fill a global [:limit] before fairness runs.
    The compact served map is only a scheduling hint; DB leases own correctness.
    """
    served = served if served is not None else {}
    owners = list(queryset.values_list(owner_field, flat=True).distinct().order_by(owner_field))
    owners.sort(key=lambda owner: (served.get(owner or 0, 0), owner or 0))
    # A lane/host-filtered window is not the complete set of active owners.
    # Its caller must prune against the full work scope instead.
    if prune:
        live = {owner or 0 for owner in owners}
        for owner in list(served):
            if owner not in live:
                served.pop(owner, None)
    queues = [list(queryset.filter(**{owner_field: owner}).order_by(*order).values_list('pk', flat=True)[:limit])
        for owner in owners[:limit]]
    chosen = []
    for index in range(limit):
        for queue in queues:
            if index < len(queue) and queue[index] not in chosen:
                chosen.append(queue[index])
                if len(chosen) == limit:
                    return chosen
    return chosen


def target_host(operation):
    binding = operation.binding
    url = (binding.effective_feed_url or binding.canonical_feed_url) if binding else operation.safe_input.get('url', '')
    return urlsplit(url).hostname or ''
