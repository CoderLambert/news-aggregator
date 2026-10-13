"""Bounded operator enqueue command; HTTP execution belongs to the Worker."""
from collections import Counter
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from api.models import News
from api.services.full_content_status import enqueue_fetch, has_full_content, fetch_eligibility, filter_readable_full_content
from api.services.source_policy import POLICIES


class Command(BaseCommand):
    help = 'Queue a bounded explicit selection of full-content tasks; never fetch HTTP in this command.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--source', default='', help='Reviewed source_key or existing Source.name')
        parser.add_argument('--force', action='store_true', help='Refresh intent; preserve active leases and cooldowns')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--status', default='pending,network_error,failed,validation_failed,success,queued,rate_limited')
        parser.add_argument('--max-retries', type=int, default=5)
        parser.add_argument('--older-than-minutes', type=int, default=0)
        parser.add_argument('--provider-report', action='store_true', help='Compatibility: report enqueue outcomes')
        parser.add_argument('--since', help='Inclusive ISO timestamp with timezone')
        parser.add_argument('--until', help='Exclusive ISO timestamp with timezone')
        parser.add_argument('--recent-only', action='store_true', help='Reliable recent seven-day discoveries under automatic source admission')
        parser.add_argument('--after-id', type=int, default=0, help='Resume the bounded selection after this database ID')

    def handle(self, *args, **options):
        from django.conf import settings
        from api.services.source_dates import parse_source_datetime
        limit = options['limit']
        if not 1 <= limit <= 500 or options['after_id'] < 0:
            raise CommandError('--limit must be between 1 and 500')
        if not 1 <= options['max_retries'] <= 5 or options['older_than_minutes'] < 0:
            raise CommandError('invalid retry or age limit')
        query = News.objects.select_related('source', 'category').prefetch_related('source_items')
        query = query.filter(pk__gt=options['after_id'])
        query = query.filter(full_content_fetch_status__in=[s.strip() for s in options['status'].split(',')],
                             full_content_retry_count__lt=options['max_retries'])
        source = options['source']
        if source:
            source_name = POLICIES[source].name if source in POLICIES else source
            query = query.filter(source__name__iexact=source_name)
        for flag, lookup in [('since', 'publish_time__gte'), ('until', 'publish_time__lt')]:
            if options[flag]:
                stamp = parse_source_datetime(options[flag])
                if stamp is None:
                    raise CommandError(f'--{flag} must be an ISO timestamp with timezone')
                query = query.filter(**{lookup: stamp})
        if options['older_than_minutes']:
            cutoff = timezone.now() - timedelta(minutes=options['older_than_minutes'])
            query = query.filter(Q(last_full_content_attempt__lt=cutoff) | Q(last_full_content_attempt__isnull=True))
        if options['recent_only']:
            now = timezone.now()
            query = query.filter(publish_time__gte=now - timedelta(days=7), publish_time__lte=now,
                full_content_next_attempt_at__isnull=True, content_kind='article',
                source_items__source_key__in=settings.FULL_CONTENT_AUTO_SOURCE_KEYS,
                source_items__metadata__publish_time_inferred=False).exclude(full_content_fetch_status='fetching').distinct()
        if not options['force']:
            query = query.exclude(pk__in=filter_readable_full_content(News.objects.all()).values('pk'))
        counts = Counter()
        # Both query and mutations are bounded even when most rows are skipped.
        candidates = list(query.order_by('pk')[:limit])
        self.stdout.write(f'Candidates: {len(candidates)}; mode=enqueue')
        for news in candidates:
            if has_full_content(news) and not options['force']:
                counts['cached'] += 1
                continue
            if fetch_eligibility(news) or news.full_content_fetch_status in {'blocked', 'unsupported'}:
                counts['rejected'] += 1
                continue
            if options['recent_only']:
                reliable = any(mapping.source_key in settings.FULL_CONTENT_AUTO_SOURCE_KEYS and
                               mapping.metadata.get('publish_time_inferred') is False
                               for mapping in news.source_items.all())
                if news.content_kind != 'article' or not reliable or news.full_content_next_attempt_at is not None or news.full_content_fetch_status == 'fetching':
                    counts['policy_skip'] += 1
                    continue
            if options['dry_run']:
                self.stdout.write(f'DRY-RUN news={news.pk} source={news.source.name} status={news.full_content_fetch_status} action=enqueue')
                counts['dry_run'] += 1
                continue
            outcome = enqueue_fetch(news, force=options['force'], priority=10 if options['force'] else 0)
            counts[outcome] += 1
            self.stdout.write(f'{outcome.upper()} news={news.pk}')
        self.stdout.write('Done. ' + ' '.join(f'{key}={value}' for key, value in sorted(counts.items())))
        if candidates:
            self.stdout.write(f'next_after_id={candidates[-1].pk}')
