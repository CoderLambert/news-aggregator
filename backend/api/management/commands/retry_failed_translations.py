"""Management command to retry failed or network-error translations."""

from django.core.management.base import BaseCommand
from django.utils.timezone import now as tz_now
from api.models import News
from api.services.translator import translate, is_chinese, ERROR_NETWORK, ERROR_TIMEOUT, ERROR_SSL
import time


class Command(BaseCommand):
    help = 'Retry Chinese translation for news articles that previously failed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Max number of articles to translate (0 = all)',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-translate even if translation already exists',
        )
        parser.add_argument(
            '--status', type=str, default='failed,network_error',
            help='Comma-separated statuses to retry (default: failed,network_error)',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be retried without actually translating',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        force = options['force']
        status_filter = [s.strip() for s in options['status'].split(',')]
        dry_run = options['dry_run']

        qs = News.objects.filter(
            translation_status__in=status_filter,
        ).order_by('last_translation_attempt')

        total = qs.count()
        if limit > 0:
            qs = qs[:limit]

        self.stdout.write(
            f'Found {total} articles with status in {status_filter}' +
            (f', processing {limit}' if limit > 0 else '')
        )

        if dry_run:
            for news in qs:
                self.stdout.write(
                    f'  [DRY RUN] {news.id} [{news.translation_status}] '
                    f'retry={news.translation_retry_count}: {news.title[:60]}...'
                )
            self.stdout.write(self.style.SUCCESS(f'Would retry {qs.count()} articles.'))
            return

        count = 0
        success_count = 0
        fail_count = 0
        network_fail_count = 0

        for news in qs:
            if is_chinese(news.title):
                news.translation_status = 'success'
                news.save(update_fields=['translation_status'])
                continue

            # If already has translation and not forcing, skip
            if news.title_zh and not force:
                news.translation_status = 'success'
                news.save(update_fields=['translation_status'])
                continue

            news.translation_retry_count += 1
            news.translation_status = 'translating'
            news.last_translation_attempt = tz_now()
            news.save(update_fields=[
                'translation_retry_count', 'translation_status', 'last_translation_attempt'
            ])

            try:
                title_zh, err_type, err_msg = translate(
                    news.title, src='en', tgt='zh-CN'
                )

                if title_zh:
                    news.title_zh = title_zh
                    if news.content and not is_chinese(news.content):
                        content_zh, c_err, c_msg = translate(
                            news.content, src='en', tgt='zh-CN'
                        )
                        if content_zh:
                            news.content_zh = content_zh

                    news.translation_status = 'success'
                    news.translation_error = ''
                    news.save(update_fields=[
                        'title_zh', 'content_zh', 'translation_status', 'translation_error'
                    ])
                    success_count += 1
                    count += 1
                    self.stdout.write(
                        f'  [{count}] ✓ {news.title[:60]}... -> {title_zh[:30]}'
                    )
                else:
                    # Translation returned empty with error
                    # Map 'unknown' to 'failed' for clarity
                    news.translation_status = 'failed' if err_type == 'unknown' else err_type
                    news.translation_error = err_msg or 'Empty translation result'
                    news.save(update_fields=['translation_status', 'translation_error'])
                    fail_count += 1
                    count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'  [{count}] ✗ [{err_type}] {news.title[:50]}...'
                        )
                    )

            except Exception as e:
                err_str = str(e).lower()
                if any(kw in err_str for kw in ["network is unreachable", "connection refused",
                                                 "no address associated"]):
                    news.translation_status = 'network_error'
                    network_fail_count += 1
                elif "timed out" in err_str or "timeout" in err_str:
                    news.translation_status = 'network_error'
                    network_fail_count += 1
                elif "ssl" in err_str:
                    news.translation_status = 'network_error'
                    network_fail_count += 1
                else:
                    news.translation_status = 'failed'
                    fail_count += 1
                news.translation_error = str(e)
                news.save(update_fields=['translation_status', 'translation_error'])
                count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'  [{count}] ✗ [{news.translation_status}] {news.title[:50]}... - {e}'
                    )
                )

            # Rate limiting
            time.sleep(1)

        summary = f'\nDone! Processed {count} articles: ' \
                  f'{success_count} succeeded, {fail_count} failed, ' \
                  f'{network_fail_count} network errors'
        self.stdout.write(self.style.SUCCESS(summary))
