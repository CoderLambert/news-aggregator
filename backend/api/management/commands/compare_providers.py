from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from api.models import ProviderComparison
from api.services.article_fetcher.comparison import compare_providers


class Command(BaseCommand):
    help = 'Run article-fetch provider comparisons and persist ProviderComparison rows.'

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument('--news-id', type=int, help='Existing News id to compare')
        target.add_argument('--url', help='Standalone URL to compare')
        parser.add_argument('--expected-title', default='', help='Expected title for URL-only runs')
        parser.add_argument('--summary', default='', help='Summary for URL-only runs')
        parser.add_argument(
            '--providers',
            default='',
            help='Comma-separated provider names to run (default: all default providers)',
        )
        parser.add_argument('--json', action='store_true', help='Print machine-readable JSON')

    def handle(self, *args, **options):
        provider_names = [p.strip() for p in (options.get('providers') or '').split(',') if p.strip()]
        try:
            run_id, comparisons = compare_providers(
                news_id=options.get('news_id'),
                url=options.get('url'),
                expected_title=options.get('expected_title') or None,
                summary=options.get('summary') or None,
                provider_names=provider_names or None,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if options.get('json'):
            payload = {
                'run_id': str(run_id),
                'count': len(comparisons),
                'results': [self._row(row) for row in comparisons],
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.SUCCESS(f'Provider comparison run {run_id}: {len(comparisons)} result(s)'))
        for row in comparisons:
            status = 'OK' if row.ok else 'FAIL'
            self.stdout.write(
                f'[{status}] #{row.pk} {row.provider} score={row.quality_score} '
                f'len={row.content_length} elapsed_ms={row.elapsed_ms} error={row.error[:120]}'
            )

    def _row(self, row: ProviderComparison) -> dict:
        return {
            'id': row.pk,
            'run_id': str(row.run_id),
            'news': row.news_id,
            'url': row.url,
            'provider': row.provider,
            'ok': row.ok,
            'quality_score': row.quality_score,
            'content_length': row.content_length,
            'error': row.error,
        }
