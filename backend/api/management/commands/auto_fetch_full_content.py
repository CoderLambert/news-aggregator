"""Auto-fetch full article content in a background daemon.

Continuously polls for articles missing ``full_content`` and fetches them
via the Scrapy-only provider chain.  Designed to run as a long-lived
management command (e.g. ``python manage.py auto_fetch_full_content``) or
as a background thread started from ``ApiConfig.ready()``.

Features
--------
- Scrapy-only provider chain (no Jina) to avoid burning external API credits
- Configurable interval, batch size, throttle via env vars / ``settings``
- Graceful shutdown on SIGINT / SIGTERM
- Survives Django dev-server autoreload
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time

from django.utils.timezone import now as tz_now

from api.services.full_content_status import (
    classify_fetch_error,
    mark_failed,
    mark_fetching,
    mark_success,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env → settings → defaults)
# ---------------------------------------------------------------------------

def _cfg(name: str, default):
    """Read from env first, then Django settings, then default."""
    val = os.environ.get(name)
    if val is not None:
        return type(default)(val)
    try:
        from django.conf import settings
        return getattr(settings, name, default)
    except Exception:
        return default


# Poll interval between batches (seconds)
POLL_INTERVAL = _cfg('AUTO_FETCH_INTERVAL', 300)  # 5 min default
# Max articles per batch
BATCH_LIMIT = _cfg('AUTO_FETCH_BATCH', 10)
# Throttle between individual requests (seconds)
THROTTLE = _cfg('AUTO_FETCH_THROTTLE', 2.0)
# Only sources of these types (empty = all)
ALLOWED_SOURCES = _cfg('AUTO_FETCH_SOURCES', '')

_stop_event = threading.Event()


def _signal_handler(signum, frame):
    _stop_event.set()


# ---------------------------------------------------------------------------
# Core loop
# ---------------------------------------------------------------------------

def _get_scrapy_providers():
    """Return a single-provider chain: only ScrapySubprocess."""
    from api.services.article_fetcher.providers import ScrapySubprocessProvider
    return [ScrapySubprocessProvider()]


def _fetch_one(news, providers_chain):
    """Fetch full content for a single News instance. Returns True on success."""
    from api.services.article_fetcher import FetchError, fetch_article_markdown

    mark_fetching(news)
    result = fetch_article_markdown(
        news.url,
        expected_title=news.title,
        summary=news.content,
        providers=providers_chain,
    )
    news.full_content = result.markdown
    news.full_content_fetched_at = tz_now()
    news.full_content_backfill_source = result.provider or 'scrapy_subprocess'
    news.full_content_backfill_at = tz_now()
    news.save(update_fields=[
        'full_content',
        'full_content_fetched_at',
        'full_content_backfill_source',
        'full_content_backfill_at',
    ])
    mark_success(news, result)
    return result


def _get_pending():
    """Return queryset of articles needing full content."""
    from django.db.models import Q

    from api.models import News

    # --- Recover stuck 'fetching' records (from interrupted processes) ---
    from datetime import timedelta
    from django.utils.timezone import now as tz_now
    stuck_cutoff = tz_now() - timedelta(minutes=10)
    stuck = News.objects.filter(
        full_content_fetch_status='fetching',
        last_full_content_attempt__lt=stuck_cutoff,
    )
    recovered = stuck.update(
        full_content_fetch_status='pending',
        last_full_content_attempt=None,
    )
    if recovered:
        logger.info('[auto-fetch] recovered %d stuck "fetching" records', recovered)

    # --- Main query ---
    status_filter = ('pending', 'network_error', 'failed')
    qs = (
        News.objects
        .exclude(url='')
        # Only articles with no full_content at all
        .filter(full_content='')
        .filter(full_content_fetch_status__in=status_filter)
        .filter(full_content_retry_count__lt=5)
    )

    if ALLOWED_SOURCES:
        sources = [s.strip() for s in ALLOWED_SOURCES.split(',') if s.strip()]
        if sources:
            qs = qs.filter(source__name__in=sources)

    # Skip recently-attempted items (cooldown 30 min)
    cutoff = tz_now() - timedelta(minutes=30)
    qs = qs.filter(
        Q(last_full_content_attempt__lt=cutoff) | Q(last_full_content_attempt__isnull=True)
    )

    return qs.order_by('-publish_time')[:BATCH_LIMIT]


def run_loop():
    """Main daemon loop. Blocks until ``_stop_event`` is set."""
    if _stop_event.is_set():
        _stop_event.clear()  # reset in case of reuse

    # Only install signal handlers in the main thread
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(
        '[auto-fetch] daemon started  interval=%ss  batch=%s  throttle=%ss',
        POLL_INTERVAL, BATCH_LIMIT, THROTTLE,
    )

    while not _stop_event.is_set():
        pending = list(_get_pending())
        if not pending:
            # Nothing to do — wait for next poll
            _stop_event.wait(timeout=POLL_INTERVAL)
            continue

        logger.info('[auto-fetch] %d pending articles in this batch', len(pending))
        providers_chain = _get_scrapy_providers()
        ok = 0
        failed = 0

        for idx, news in enumerate(pending):
            if _stop_event.is_set():
                break

            try:
                result = _fetch_one(news, providers_chain)
                ok += 1
                logger.info(
                    '[auto-fetch] OK  news=%s  provider=%s  score=%.2f  len=%d',
                    news.pk, result.provider, result.quality_score, len(result.markdown),
                )
            except Exception as exc:
                failed += 1
                from api.services.article_fetcher import FetchError
                if isinstance(exc, FetchError):
                    status = classify_fetch_error(exc)
                    mark_failed(news, exc, status=status)
                else:
                    mark_failed(news, exc)
                logger.warning(
                    '[auto-fetch] FAIL  news=%s  %s',
                    news.pk, str(exc)[:200],
                )

            # Throttle
            if idx < len(pending) - 1 and THROTTLE > 0:
                # Interruptible sleep
                if _stop_event.wait(timeout=THROTTLE):
                    break

        logger.info(
            '[auto-fetch] batch done: ok=%d  fail=%d  next poll in %ds',
            ok, failed, POLL_INTERVAL,
        )
        _stop_event.wait(timeout=POLL_INTERVAL)

    logger.info('[auto-fetch] daemon stopped')


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run a background daemon that auto-fetches full article content via Scrapy.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--foreground',
            action='store_true',
            help='Run in foreground (default). Without this, forks a daemon thread.',
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS(
                f'[auto-fetch] starting  interval={POLL_INTERVAL}s  '
                f'batch={BATCH_LIMIT}  throttle={THROTTLE}s'
            )
        )
        run_loop()
