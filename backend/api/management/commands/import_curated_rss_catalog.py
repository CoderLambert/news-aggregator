"""Explicit local-file import for the shared discovery catalog, not subscriptions."""
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.rss.catalog_import import apply_catalog_plan, plan_catalog_import, rollback_catalog
from api.rss.catalog_opml import MAX_BYTES


class Command(BaseCommand):
    help = 'Preview/apply a curated OPML catalog (5 sections/21 groups); never subscribes users.'

    def add_arguments(self, parser):
        inputs = parser.add_mutually_exclusive_group(required=True)
        inputs.add_argument('--file', help='Explicit path to the complete nested OPML catalogue.')
        inputs.add_argument('--rollback', metavar='CHECKSUM', help='Reactivate a retained snapshot.')
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--dry-run', action='store_true', help='Read/validate only (default).')
        mode.add_argument('--apply', action='store_true', help='Explicitly change the active catalog.')
        parser.add_argument('--input-sha256', help='Required for apply; copy input_checksum from dry-run.')
        parser.add_argument('--plan-sha256', help='Required for apply; copy proposed_checksum from dry-run.')
        parser.add_argument('--expected-active', help='Current snapshot checksum, or none for first import.')
        parser.add_argument('--source-license', default='NOASSERTION',
                            help='Actual metadata license; unknown remains NOASSERTION, never invented CC0.')
        parser.add_argument('--acknowledge-provenance', action='store_true',
                            help='Operator confirms the input provenance was reviewed; not a health check.')

    def handle(self, *args, **options):
        try:
            if options['rollback']:
                if not options['apply'] or not options['expected_active']:
                    raise CommandError('Rollback requires --apply and --expected-active.')
                result = rollback_catalog(options['rollback'], expected_active=options['expected_active'])
            else:
                if options['apply'] and not (
                    options['input_sha256'] and options['plan_sha256'] and options['expected_active']
                    and options['acknowledge_provenance']
                ):
                    raise CommandError('Apply requires --input-sha256, --plan-sha256, --expected-active and --acknowledge-provenance.')
                with Path(options['file']).open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
                if options['input_sha256'] and hashlib.sha256(raw).hexdigest() != options['input_sha256']:
                    raise CommandError('Input checksum mismatch; no changes applied.')
                plan = plan_catalog_import(raw, source_license=options['source_license'])
                if options['plan_sha256'] and plan.checksum != options['plan_sha256']:
                    raise CommandError('Plan checksum mismatch; run dry-run again.')
                result = {**plan.report, 'applied': False}
                if options['apply']:
                    expected = None if options['expected_active'] == 'none' else options['expected_active']
                    result = apply_catalog_plan(plan, expected_active=expected)
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
