"""Backfill full_content via Scrapy-only provider chain.

This management command exists to validate Scrapy provider quality
independently from the default chain (which prioritises Jina). It rewrites
`full_content` only when Scrapy succeeds, and stamps a separate
`full_content_backfill_source` / `full_content_backfill_at` pair so the user
can identify which rows came from this backfill batch.

Design:
  - ONLY uses ScrapySubprocessProvider (no Jina, no ScrapyHTTP fallback)
  - Serial execution + --sleep throttling (anti-anti-bot)
  - Skips validation_failed (Phase 2 plan: rule problem, retrying same content is wasteful)
  - Failures update status fields but do NOT stamp backfill_* fields
    (so the user can distinguish "tried Scrapy, succeeded" vs "Scrapy couldn't handle it")
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.utils.timezone import now as tz_now

from api.models import News
from api.services.article_fetcher import FetchError, fetch_article_markdown
from api.services.article_fetcher.providers import ScrapySubprocessProvider
from api.services.full_content_status import (
    classify_fetch_error,
    mark_failed,
    mark_fetching,
    mark_success,
)


def _scrapy_only_providers():
    """Single-provider chain: only ScrapySubprocess."""
    return [ScrapySubprocessProvider()]


class Command(BaseCommand):
    help = (
        'Backfill News.full_content using the Scrapy-only chain (no Jina). '
        'Stamps full_content_backfill_source/at on success so results can be '
        'audited and re-tested separately from Jina-fetched rows.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50, help='Maximum articles to process (0 = no limit)')
        parser.add_argument('--source', type=str, default='', help='Filter by Source.name (case-insensitive)')
        parser.add_argument('--dry-run', action='store_true', help='Show candidates without fetching or saving')
        parser.add_argument(
            '--status',
            type=str,
            default='pending,network_error,failed',
            help='Comma-separated status values to include (default: pending,network_error,failed). '
                 'validation_failed is always skipped — rule problem, not a fetch problem.',
        )
        parser.add_argument(
            '--max-retries',
            type=int,
            default=5,
            help='Skip articles with retry_count >= this value (default: 5)',
        )
        parser.add_argument(
            '--sleep',
            type=float,
            default=2.0,
            help='Seconds to sleep between requests to avoid triggering anti-bot (default: 2.0)',
        )
        parser.add_argument(
            '--progress-every',
            type=int,
            default=10,
            help='Print a running summary every N items (default: 10)',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']
        source = options['source']
        status_filter = [s.strip() for s in options['status'].split(',') if s.strip()]
        # Always exclude validation_failed regardless of user input
        status_filter = [s for s in status_filter if s != 'validation_failed']
        max_retries = options['max_retries']
        sleep_sec = options['sleep']
        progress_every = options['progress_every']

        qs = (
            News.objects.select_related('source', 'category')
            .exclude(url='')
            .filter(full_content='')
            .filter(full_content_fetch_status__in=status_filter)
            .filter(full_content_retry_count__lt=max_retries)
        )
        if source:
            qs = qs.filter(source__name__iexact=source)

        qs = qs.order_by('-publish_time')
        if limit and limit > 0:
            qs = qs[:limit]

        candidates = list(qs)
        total = len(candidates)
        self.stdout.write(f'Backfill candidates: {total}')
        self.stdout.write(f'Provider chain: scrapy_subprocess (only)')
        self.stdout.write(f'Throttle: {sleep_sec}s between items')

        if dry_run:
            for news in candidates[:20]:
                self.stdout.write(
                    f'DRY-RUN news={news.pk} source={news.source.name} '
                    f'status={news.full_content_fetch_status} '
                    f'retry={news.full_content_retry_count} url={news.url}'
                )
            if total > 20:
                self.stdout.write(f'  ... and {total - 20} more')
            return

        ok = 0
        failed = 0
        providers_chain = _scrapy_only_providers()

        for idx, news in enumerate(candidates, start=1):
            try:
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
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f'[{idx}/{total}] OK news={news.pk} '
                    f'provider={result.provider} score={result.quality_score:.2f} '
                    f'len={len(result.markdown)}'
                ))
            except FetchError as exc:
                failed += 1
                status = classify_fetch_error(exc)
                mark_failed(news, exc, status=status)
                self.stdout.write(self.style.WARNING(
                    f'[{idx}/{total}] FAIL news={news.pk} [{status}]: {str(exc)[:120]}'
                ))
            except Exception as exc:
                failed += 1
                mark_failed(news, exc)
                self.stdout.write(self.style.ERROR(
                    f'[{idx}/{total}] ERROR news={news.pk}: {str(exc)[:120]}'
                ))

            # Progress summary
            if progress_every > 0 and idx % progress_every == 0:
                rate = ok / idx * 100
                self.stdout.write(
                    self.style.HTTP_INFO(
                        f'--- Progress: {idx}/{total} | ok={ok} fail={failed} | success_rate={rate:.1f}%'
                    )
                )

            # Throttle between requests (skip after the last one)
            if idx < total and sleep_sec > 0:
                time.sleep(sleep_sec)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done. ok={ok} failed={failed} of {total}'))
        if total > 0:
            self.stdout.write(f'Success rate: {ok / total * 100:.1f}%')
