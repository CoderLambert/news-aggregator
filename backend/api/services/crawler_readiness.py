"""Read-only, bounded admin snapshot of actual source scheduling and delivery."""
from datetime import timedelta
from django.db.models import Max, Min
from django.utils import timezone

from api.models import CrawlerSettings, CrawlerTarget, CrawlRun, FeedState, SearchIndexSettings
from api.services.crawler_control import ACTIVE_RUN_STATUSES
from api.services.source_policy import policy_for_key
from api.services.source_registry import runtime_registry

_UNHEALTHY = frozenset({
    'failed', 'partial', 'rate_limited', 'blocked', 'network_error', 'http_error',
    'parse_failed', 'deferred',
})


def readiness_snapshot():
    """GET must never sync registries, mutate heartbeat, reserve budget, or fetch a feed."""
    now = timezone.now()
    settings = CrawlerSettings.objects.filter(pk=1).first()
    scheduler_enabled = bool(settings and settings.scheduler_enabled)
    crawler_online = bool(settings and settings.worker_heartbeat_at and
                          settings.worker_heartbeat_at >= now - timedelta(seconds=45))
    index = SearchIndexSettings.objects.filter(pk=1).first()
    index_online = bool(index and index.worker_heartbeat_at and
                        index.worker_heartbeat_at >= now - timedelta(seconds=90))

    names = sorted(runtime_registry(include_unavailable=True))[:100]
    targets = {row.spider_name: row for row in
               CrawlerTarget.objects.filter(spider_name__in=names).only(
                   'spider_name', 'display_name', 'enabled', 'last_status', 'last_finished_at')}
    feed_rows = {
        row['source_key']: row
        for row in FeedState.objects.filter(source_key__in=names).values('source_key').annotate(
            last_success_at=Max('last_success_at'), next_poll_at=Min('next_poll_at'))
    }
    active = set(CrawlRun.objects.filter(
        target_id__in=names, status__in=ACTIVE_RUN_STATUSES
    ).values_list('target_id', flat=True).distinct()[:100])

    sources = []
    for name in names:
        target = targets.get(name)
        policy = policy_for_key(name)
        supported = bool(policy and not policy.unsupported_reason)
        registered = target is not None
        enabled = bool(registered and target.enabled and supported)
        feed = feed_rows.get(name) or {}
        next_poll = feed.get('next_poll_at')
        last_success = feed.get('last_success_at')
        last_result = (target.last_status or '') if target else ''
        if not supported:
            state, remedy = 'unsupported', 'review_source_policy'
        elif not registered:
            state, remedy = 'not_registered', 'sync_registered_targets'
        elif not target.enabled:
            state, remedy = 'disabled', 'review_target_switch'
        elif not crawler_online:
            state, remedy = 'worker_offline', 'check_worker_heartbeat'
        elif name in active:
            state, remedy = 'running', 'observe_active_run'
        elif not scheduler_enabled:
            state, remedy = 'scheduler_paused', 'review_scheduler_switch'
        elif last_result in _UNHEALTHY:
            state, remedy = 'degraded', 'inspect_last_run'
        elif next_poll and next_poll > now and last_success:
            state, remedy = 'waiting_poll', 'wait_until_due'
        elif last_success or last_result in {'succeeded', 'skipped'}:
            state, remedy = 'idle', 'wait_or_start_manual_run'
        else:
            state, remedy = 'no_history', 'inspect_last_run'
        sources.append({
            'source_key': name,
            'display_name': target.display_name if target else name,
            'registered': registered, 'supported': supported,
            'enabled': enabled,
            'state': state, 'suggested_action': remedy,
            'last_result': last_result[:32],
            'last_finished_at': target.last_finished_at if target else None,
            'last_feed_success_at': last_success,
            'next_poll_at': next_poll,
        })
    return {
        'server_time': now,
        'scheduler': {
            'configured': settings is not None, 'enabled': scheduler_enabled,
            'next_run_at': settings.next_run_at if settings else None,
        },
        'workers': {
            'crawler': {'online': crawler_online, 'heartbeat_at': settings.worker_heartbeat_at if settings else None},
            'search_index': {'enabled': bool(index and index.enabled), 'online': index_online,
                             'heartbeat_at': index.worker_heartbeat_at if index else None},
        },
        'sources': sources,
    }
