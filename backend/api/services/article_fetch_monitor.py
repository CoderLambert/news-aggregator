from __future__ import annotations

from collections import Counter
from datetime import timedelta
import ipaddress
import json
import logging
import re
import threading
import time

from django.db import DatabaseError
from django.db.models import Count, F, Q
from django.utils import timezone

from api.models import ArticleFetchEvent, JinaFallbackPolicy, News

from .article_fetcher.site_rules import normalize_domain
from .article_fetcher.types import FetchResult, fetch_failure_code


logger = logging.getLogger(__name__)

EVENT_RETENTION_DAYS = 30
_PRUNE_INTERVAL_SECONDS = 3600
_DOMAIN_LABEL = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
_prune_lock = threading.Lock()
_last_prune_at = 0.0


def validate_policy_domain(value: str) -> str:
    """Return one normalized public DNS name, rejecting URLs and IP literals."""
    if not isinstance(value, str):
        raise ValueError('域名必须是字符串。')
    raw = value.strip().lower().rstrip('.')
    if not raw or any(token in raw for token in ('://', '/', '\\', '@', ':')):
        raise ValueError('请输入不含协议、路径、端口或凭据的域名。')
    domain = normalize_domain(raw)
    if not domain or len(domain) > 253 or '.' not in domain:
        raise ValueError('域名格式无效。')
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError('不允许使用 IP 地址作为 Jina 策略。')
    if domain == 'localhost' or not all(_DOMAIN_LABEL.fullmatch(label) for label in domain.split('.')):
        raise ValueError('域名格式无效。')
    return domain


def observe_jina_candidate(domain: str) -> bool:
    """Register an exact-domain candidate and return its current enabled state."""
    try:
        normalized = validate_policy_domain(domain)
    except ValueError:
        return False
    now = timezone.now()
    try:
        policy, created = JinaFallbackPolicy.objects.get_or_create(
            domain=normalized,
            defaults={
                'enabled': False,
                'auto_discovered': True,
                'failure_count': 1,
                'last_seen_at': now,
            },
        )
        if not created:
            JinaFallbackPolicy.objects.filter(pk=normalized).update(
                failure_count=F('failure_count') + 1,
                last_seen_at=now,
            )
            policy.refresh_from_db(fields=['enabled'])
        return policy.enabled
    except DatabaseError:
        logger.exception('article_fetch_monitor policy_lookup_failed domain=%s', normalized)
        return False


def _failure_entries(failures: list[FetchResult]) -> list[dict[str, str]]:
    return [
        {
            'provider': re.sub(r'[^a-z0-9_.-]+', '_', (failure.provider or 'provider').lower())[:64],
            'code': fetch_failure_code(failure),
        }
        for failure in failures
    ]


def _safe_provider(value: str) -> str:
    return re.sub(r'[^a-z0-9_.-]+', '_', (value or 'provider').lower()).strip('_.-')[:64] or 'provider'


def _prune_old_events() -> None:
    global _last_prune_at
    now_monotonic = time.monotonic()
    if now_monotonic - _last_prune_at < _PRUNE_INTERVAL_SECONDS:
        return
    if not _prune_lock.acquire(blocking=False):
        return
    try:
        now_monotonic = time.monotonic()
        if now_monotonic - _last_prune_at < _PRUNE_INTERVAL_SECONDS:
            return
        cutoff = timezone.now() - timedelta(days=EVENT_RETENTION_DAYS)
        ArticleFetchEvent.objects.filter(created_at__lt=cutoff).delete()
        _last_prune_at = now_monotonic
    finally:
        _prune_lock.release()


def record_fetch_event(
    *,
    url: str,
    news_id: int | None,
    result: FetchResult | None,
    failures: list[FetchResult],
    elapsed_ms: int,
) -> None:
    """Persist and emit one sanitized provider-chain outcome without blocking fetches."""
    domain = normalize_domain(url) or 'invalid-domain'
    failure_codes = _failure_entries(failures)
    outcome = 'success' if result is not None and result.ok else 'failed'
    raw_provider = result.provider if result is not None else (failures[-1].provider if failures else '')
    provider = _safe_provider(raw_provider) if raw_provider else ''
    content_length = len(result.markdown or '') if result is not None else 0
    quality_score = result.quality_score if result is not None and result.quality_score > 0 else None
    payload = {
        'event': 'article_fetch',
        'news_id': news_id,
        'domain': domain,
        'outcome': outcome,
        'provider': provider,
        'failure_codes': failure_codes,
        'quality_score': quality_score,
        'content_length': content_length,
        'elapsed_ms': max(0, elapsed_ms),
    }
    log = logger.info if outcome == 'success' else logger.warning
    log('article_fetch_event %s', json.dumps(payload, ensure_ascii=True, separators=(',', ':')))

    try:
        ArticleFetchEvent.objects.create(
            news_id=news_id,
            domain=domain,
            outcome=outcome,
            provider=provider,
            failure_codes=failure_codes,
            quality_score=quality_score,
            content_length=max(0, content_length),
            elapsed_ms=max(0, elapsed_ms),
        )
        if outcome == 'failed':
            JinaFallbackPolicy.objects.filter(pk=domain).update(
                last_failure_codes=failure_codes,
                last_seen_at=timezone.now(),
            )
        _prune_old_events()
    except DatabaseError:
        logger.exception('article_fetch_monitor event_persist_failed domain=%s', domain)


def policy_payload(policy: JinaFallbackPolicy) -> dict:
    return {
        'domain': policy.domain,
        'enabled': policy.enabled,
        'auto_discovered': policy.auto_discovered,
        'failure_count': policy.failure_count,
        'last_failure_codes': policy.last_failure_codes,
        'last_seen_at': policy.last_seen_at,
        'updated_at': policy.updated_at,
    }


def monitor_dashboard(*, days: int = 7, recent_limit: int = 100) -> dict:
    since = timezone.now() - timedelta(days=days)
    events = ArticleFetchEvent.objects.filter(created_at__gte=since)
    total = events.count()
    successes = events.filter(outcome='success').count()
    domain_rows = list(
        events.values('domain')
        .annotate(
            total=Count('id'),
            failed=Count('id', filter=Q(outcome='failed')),
            succeeded=Count('id', filter=Q(outcome='success')),
        )
        .order_by('-failed', '-total', 'domain')[:50]
    )
    provider_rows = list(
        events.values('provider', 'outcome')
        .annotate(count=Count('id'))
        .order_by('-count', 'provider')
    )
    reasons: Counter[str] = Counter()
    for entries in events.order_by('-created_at').values_list('failure_codes', flat=True)[:5000]:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get('code'), str):
                reasons[entry['code']] += 1
    recent_events = list(
        events.order_by('-created_at', '-id').values(
            'id', 'news_id', 'domain', 'outcome', 'provider', 'failure_codes',
            'quality_score', 'content_length', 'elapsed_ms', 'created_at',
        )[:recent_limit]
    )
    policies = [
        policy_payload(policy)
        for policy in JinaFallbackPolicy.objects.order_by('-enabled', '-last_seen_at', 'domain')
    ]
    unresolved = News.objects.filter(
        full_content='',
        full_content_fetch_status__in=['failed', 'network_error', 'validation_failed'],
    ).count()
    return {
        'window_days': days,
        'retention_days': EVENT_RETENTION_DAYS,
        'summary': {
            'total': total,
            'success': successes,
            'failed': total - successes,
            'success_rate': round(successes / total, 4) if total else 0.0,
            'unresolved_articles': unresolved,
        },
        'domains': domain_rows,
        'providers': provider_rows,
        'top_failure_codes': [
            {'code': code, 'count': count}
            for code, count in reasons.most_common(20)
        ],
        'policies': policies,
        'recent_events': recent_events,
        'server_time': timezone.now(),
    }
