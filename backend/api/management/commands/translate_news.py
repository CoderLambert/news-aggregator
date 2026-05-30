"""Management command to backfill Chinese translations for English news articles."""

from django.core.management.base import BaseCommand
from django.utils.timezone import now as tz_now
from api.models import News, Source
from api.services.translator import translate, is_chinese
import time


class Command(BaseCommand):
    help = 'Backfill Chinese translations for English news articles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Max number of articles to translate (0 = all)',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Re-translate even if translation already exists',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        force = options['force']

        # Find English sources
        en_sources = Source.objects.filter(language='en')
        en_source_ids = list(en_sources.values_list('id', flat=True))

        if not en_source_ids:
            self.stdout.write(self.style.WARNING('No English sources found.'))
            return

        qs = News.objects.filter(
            source_id__in=en_source_ids,
        ).exclude(
            title=''
        ).order_by('-publish_time')

        if not force:
            qs = qs.filter(title_zh='')

        total = qs.count()
        if limit > 0:
            qs = qs[:limit]

        self.stdout.write(f'Found {total} untranslated English articles' +
                          (f', processing {limit}' if limit > 0 else ''))

        count = 0
        for news in qs:
            if is_chinese(news.title):
                news.translation_status = 'success'
                news.save(update_fields=['translation_status'])
                continue

            news.translation_status = 'translating'
            news.last_translation_attempt = tz_now()
            news.save(update_fields=['translation_status', 'last_translation_attempt'])

            try:
                title_zh, err_type, err_msg = translate(news.title, src='en', tgt='zh-CN')
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
                    count += 1
                    self.stdout.write(
                        f'  [{count}] {news.title[:60]}... -> {title_zh[:30]}'
                    )
                else:
                    news.translation_status = 'failed' if err_type == 'unknown' else err_type
                    news.translation_error = err_msg or 'Empty translation'
                    news.save(update_fields=['translation_status', 'translation_error'])
                    self.stdout.write(
                        self.style.WARNING(
                            f'  ✗ [{err_type}] {news.title[:50]}...'
                        )
                    )
            except Exception as e:
                err_str = str(e).lower()
                if any(kw in err_str for kw in ["network is unreachable", "connection refused",
                                                 "no address associated", "timed out", "timeout", "ssl"]):
                    news.translation_status = 'network_error'
                else:
                    news.translation_status = 'failed'
                news.translation_error = str(e)
                news.save(update_fields=['translation_status', 'translation_error'])
                self.stdout.write(
                    self.style.ERROR(f'  Failed: {news.title[:50]}... - {e}')
                )

            # Rate limiting
            time.sleep(1)

        self.stdout.write(self.style.SUCCESS(f'\nDone! Translated {count} articles.'))
