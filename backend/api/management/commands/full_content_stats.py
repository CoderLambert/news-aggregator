import json
from collections import Counter

from django.core.management.base import BaseCommand

from api.models import News


class Command(BaseCommand):
    help = 'Show full-content fetch statistics: coverage, status distribution, provider stats, etc.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default='',
            help='Filter by Source.name (case-insensitive)',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output as JSON instead of human-readable text',
        )

    def handle(self, *args, **options):
        source_filter = options['source']
        as_json = options['json']

        qs = News.objects.select_related('source').all()
        if source_filter:
            qs = qs.filter(source__name__iexact=source_filter)

        total = qs.count()
        with_full = qs.exclude(full_content='').count()
        coverage = round(with_full / total, 3) if total else 0.0

        # Status distribution
        status_dist = dict(
            qs.values_list('full_content_fetch_status').annotate(
                __import__('django.db.models').db.models.Count('full_content_fetch_status')
            ).values_list('full_content_fetch_status', 'full_content_fetch_status__count')
        )
        # Simpler approach
        from django.db.models import Count
        status_dist = dict(
            qs.values('full_content_fetch_status')
            .annotate(cnt=Count('full_content_fetch_status'))
            .values_list('full_content_fetch_status', 'cnt')
        )

        # Source distribution
        source_dist = dict(
            qs.values('source__name')
            .annotate(cnt=Count('source__name'))
            .values_list('source__name', 'cnt')
        )

        # Provider distribution (only non-empty)
        provider_dist = dict(
            qs.exclude(full_content_fetch_provider='')
            .values('full_content_fetch_provider')
            .annotate(cnt=Count('full_content_fetch_provider'))
            .values_list('full_content_fetch_provider', 'cnt')
        )

        # Top errors
        error_rows = (
            qs.exclude(full_content_fetch_error='')
            .values('full_content_fetch_error')
            .annotate(cnt=Count('full_content_fetch_error'))
            .order_by('-cnt')[:10]
        )
        top_errors = dict(
            (row['full_content_fetch_error'], row['cnt']) for row in error_rows
        )

        # Retry count distribution
        retry_rows = (
            qs.values('full_content_retry_count')
            .annotate(cnt=Count('full_content_retry_count'))
            .values_list('full_content_retry_count', 'cnt')
        )
        retry_dist = {str(rc): cnt for rc, cnt in retry_rows}

        data = {
            'total': total,
            'with_full_content': with_full,
            'coverage': coverage,
            'status': status_dist,
            'sources': source_dist,
            'providers': provider_dist,
            'top_errors': top_errors,
            'retry_counts': retry_dist,
        }

        if as_json:
            self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(f'total: {total}')
            self.stdout.write(f'with_full_content: {with_full}')
            self.stdout.write(f'coverage: {coverage:.3f}')
            self.stdout.write('')
            self.stdout.write('status:')
            for k, v in sorted(status_dist.items(), key=lambda x: -x[1]):
                self.stdout.write(f'  {k}: {v}')
            self.stdout.write('')
            self.stdout.write('sources:')
            for k, v in sorted(source_dist.items(), key=lambda x: -x[1])[:10]:
                self.stdout.write(f'  {k}: {v}')
            self.stdout.write('')
            self.stdout.write('providers:')
            for k, v in sorted(provider_dist.items(), key=lambda x: -x[1]):
                self.stdout.write(f'  {k}: {v}')
            self.stdout.write('')
            self.stdout.write('top_errors:')
            for k, v in top_errors.items():
                self.stdout.write(f'  {k}: {v}')
            if not top_errors:
                self.stdout.write('  (none)')
            self.stdout.write('')
            self.stdout.write('retry_counts:')
            for k, v in sorted(retry_dist.items()):
                self.stdout.write(f'  {k}: {v}')
