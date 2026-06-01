from django.core.management.base import BaseCommand
from django.utils.timezone import now as tz_now

from api.models import News
from api.services.article_fetcher import FetchError, fetch_article_markdown
from api.services.full_content_status import classify_fetch_error, mark_failed, mark_fetching, mark_success


class Command(BaseCommand):
    help = 'Backfill verified full article Markdown for News rows missing full_content.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20, help='Maximum articles to process')
        parser.add_argument('--source', type=str, default='', help='Filter by Source.name (case-insensitive)')
        parser.add_argument('--force', action='store_true', help='Refetch even when full_content already exists')
        parser.add_argument('--dry-run', action='store_true', help='Show candidates without fetching or saving')
        # Task 5: status filter, retry limit, age filter, provider report
        parser.add_argument(
            '--status',
            type=str,
            default='pending,network_error,failed',
            help='Comma-separated status values to include (default: pending,network_error,failed)',
        )
        parser.add_argument(
            '--max-retries',
            type=int,
            default=3,
            help='Skip articles with retry_count >= this value (default: 3)',
        )
        parser.add_argument(
            '--older-than-minutes',
            type=int,
            default=30,
            help='Only process articles last attempted more than N minutes ago (default: 30, 0=disabled)',
        )
        parser.add_argument(
            '--provider-report',
            action='store_true',
            help='After processing, show per-provider success/failure summary',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']
        force = options['force']
        source = options['source']
        status_filter = [s.strip() for s in options['status'].split(',') if s.strip()]
        max_retries = options['max_retries']
        older_than_minutes = options['older_than_minutes']
        provider_report = options['provider_report']

        qs = News.objects.select_related('source', 'category').exclude(url='')
        if not force:
            qs = qs.filter(full_content='')
        if source:
            qs = qs.filter(source__name__iexact=source)
        # Task 5: status filter
        qs = qs.filter(full_content_fetch_status__in=status_filter)
        # Task 5: max-retries filter
        qs = qs.filter(full_content_retry_count__lt=max_retries)
        # Task 5: older-than filter
        if older_than_minutes and older_than_minutes > 0:
            from datetime import timedelta
            from django.db.models import Q

            cutoff = tz_now() - timedelta(minutes=older_than_minutes)
            qs = qs.filter(
                Q(last_full_content_attempt__lt=cutoff) | Q(last_full_content_attempt__isnull=True)
            )

        qs = qs.order_by('-publish_time')
        if limit:
            qs = qs[:limit]

        candidates = list(qs)
        self.stdout.write(f'Candidates: {len(candidates)}')
        if dry_run:
            for news in candidates:
                self.stdout.write(
                    f'DRY-RUN news={news.pk} source={news.source.name} '
                    f'url={news.url} status={news.full_content_fetch_status} '
                    f'retry={news.full_content_retry_count}'
                )
            return

        ok = 0
        failed = 0
        provider_stats: dict[str, dict] = {}

        for news in candidates:
            try:
                mark_fetching(news)
                result = fetch_article_markdown(
                    news.url,
                    expected_title=news.title,
                    summary=news.content,
                )
                news.full_content = result.markdown
                news.full_content_fetched_at = tz_now()
                news.save(update_fields=['full_content', 'full_content_fetched_at'])
                mark_success(news, result)
                ok += 1
                self.stdout.write(self.style.SUCCESS(
                    f'OK news={news.pk} provider={result.provider} score={result.quality_score:.2f}'
                ))
                self._track_provider(provider_stats, result.provider, True)
            except FetchError as exc:
                failed += 1
                status = classify_fetch_error(exc)
                mark_failed(news, exc, status=status)
                self.stdout.write(self.style.WARNING(f'FAIL news={news.pk}: {exc}'))
                self._track_provider(provider_stats, '', False, str(exc))
            except Exception as exc:
                failed += 1
                mark_failed(news, exc)
                self.stdout.write(self.style.ERROR(f'ERROR news={news.pk}: {exc}'))
                self._track_provider(provider_stats, '', False, str(exc))

        self.stdout.write(f'Done. ok={ok} failed={failed}')

        if provider_report and provider_stats:
            self.stdout.write('\nProvider report:')
            for provider, stats in sorted(provider_stats.items()):
                self.stdout.write(
                    f'  {provider}: ok={stats["ok"]} fail={stats["fail"]}'
                )
                if stats['errors']:
                    for err, count in sorted(stats['errors'].items(), key=lambda x: -x[1])[:3]:
                        self.stdout.write(f'    top error: {err} (x{count})')

    @staticmethod
    def _track_provider(stats, provider, success, error=''):
        key = provider or 'unknown'
        if key not in stats:
            stats[key] = {'ok': 0, 'fail': 0, 'errors': {}}
        if success:
            stats[key]['ok'] += 1
        else:
            stats[key]['fail'] += 1
            if error:
                short = error[:80]
                stats[key]['errors'][short] = stats[key]['errors'].get(short, 0) + 1
