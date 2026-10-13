import json
from django.db.models import Count, Min, Max
from django.utils import timezone

from django.core.management.base import BaseCommand

from api.models import News, RequestBudget, FeedState, ArticleFetchEvent
from api.services.full_content_status import trimmed_text_expression, filter_readable_full_content, fetch_eligibility


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
        readiness_qs = qs.alias(
            _summary_text=trimmed_text_expression('content'),
            _body_text=trimmed_text_expression('full_content'),
        )
        readable = filter_readable_full_content(qs)
        with_full = readable.count()
        without_body = readiness_qs.exclude(pk__in=readable.values('pk'))
        metadata_only = without_body.filter(_summary_text='').count()
        summary_only = without_body.exclude(_summary_text='').count()
        # Eligibility is the same pure URL/kind contract used by queue admission.
        eligible_ids = [row.pk for row in qs.select_related(None).filter(content_kind='article').only('pk', 'url', 'content_kind').iterator()
                        if not fetch_eligibility(row)]
        eligible_count = len(eligible_ids)
        complete = sum(filter_readable_full_content(qs.filter(pk__in=eligible_ids[i:i + 500], full_content_state='complete')).count()
                       for i in range(0, eligible_count, 500))
        coverage = round(complete / eligible_count, 3) if eligible_count else 0.0
        legacy = readable.filter(full_content_state='legacy').count()
        now = timezone.now()
        queued = qs.filter(full_content_fetch_status__in=('queued', 'rate_limited', 'network_error', 'failed'),
                           full_content_next_attempt_at__isnull=False)
        cooling = RequestBudget.objects.filter(cooldown_until__gt=now)

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
            qs.exclude(full_content_error_code='')
            .values('full_content_error_code')
            .annotate(cnt=Count('full_content_error_code'))
            .order_by('-cnt')[:10]
        )
        top_errors = dict(
            (row['full_content_error_code'], row['cnt']) for row in error_rows
        )

        # Retry count distribution
        retry_rows = (
            qs.values('full_content_retry_count')
            .annotate(cnt=Count('full_content_retry_count'))
            .values_list('full_content_retry_count', 'cnt')
        )
        retry_dist = {str(rc): cnt for rc, cnt in retry_rows}

        data = {
            'coverage_denominator': 'eligible_article',
            'eligible_articles': eligible_count,
            'complete_eligible_articles': complete,
            'legacy_body_count': legacy,
            'content_kinds': dict(qs.values('content_kind').annotate(cnt=Count('pk')).values_list('content_kind', 'cnt')),
            'content_states': dict(qs.values('full_content_state').annotate(cnt=Count('pk')).values_list('full_content_state', 'cnt')),
            'queue': {'pending': queued.count(), 'due': queued.filter(full_content_next_attempt_at__lte=now).count(),
                      'oldest_due_at': queued.aggregate(value=Min('full_content_next_attempt_at'))['value']},
            'budget': {'cooling_scopes': cooling.count(), 'latest_cooldown_until': cooling.aggregate(value=Max('cooldown_until'))['value']},
            'feeds': list(FeedState.objects.order_by('source_key', 'feed_url').values('source_key', 'last_success_at', 'last_checked_at', 'next_poll_at')),
            'attempts': dict(ArticleFetchEvent.objects.values('persistence_outcome').annotate(cnt=Count('pk')).values_list('persistence_outcome', 'cnt')),

            'total': total,
            'with_full_content': with_full,
            'coverage': coverage,
            'content_readiness': {
                'metadata_only': metadata_only,
                'summary_only': summary_only,
                'body_ready': with_full,
            },
            'status': status_dist,
            'sources': source_dist,
            'providers': provider_dist,
            'top_errors': top_errors,
            'retry_counts': retry_dist,
        }

        if as_json:
            self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        else:
            self.stdout.write(f'total: {total}')
            self.stdout.write(f'with_full_content: {with_full}')
            self.stdout.write(f'coverage: {coverage:.3f} (complete / eligible article: {complete}/{eligible_count})')
            self.stdout.write(f'legacy_body_count: {legacy}')
            self.stdout.write('content_readiness:')
            self.stdout.write(f'  metadata_only: {metadata_only}')
            self.stdout.write(f'  summary_only: {summary_only}')
            self.stdout.write(f'  body_ready: {with_full}')
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
