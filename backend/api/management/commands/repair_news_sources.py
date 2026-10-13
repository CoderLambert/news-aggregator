"""Preview or apply bounded, explicitly evidenced identity/source repairs."""
import json

from django.core.management.base import BaseCommand, CommandError

from api.services.news_source_repair import (
    RepairInputError, apply_plan, new_audit, plan_operation, plan_undo,
    read_json, validate_mapping, write_audit,
)


class Command(BaseCommand):
    help = 'Default dry-run: review explicit source/URL repairs or CAS undo from an audit; never merge or fetch.'

    def add_arguments(self, parser):
        inputs = parser.add_mutually_exclusive_group(required=True)
        inputs.add_argument('--mapping', help='Strict JSON schema_version=1 mapping with explicit IDs, old values and evidence.')
        inputs.add_argument('--undo-audit', help='Undo only currently matching written values/body revisions from a previous audit.')
        parser.add_argument('--apply', action='store_true', help='Perform CAS writes; requires a new protected --audit-output file.')
        parser.add_argument('--audit-output', help='New absolute audit path, required for --apply; never overwrite another run.')
        parser.add_argument('--limit', type=int, default=100, help='Maximum explicit operations; 1–1000, default 100.')

    def handle(self, *args, **options):
        try:
            if not 1 <= options['limit'] <= 1000:
                raise RepairInputError('limit_must_be_between_1_and_1000')
            if options['apply'] and not options['audit_output']:
                raise RepairInputError('apply_requires_new_audit_output')
            if options['undo_audit']:
                plans = plan_undo(read_json(options['undo_audit']), limit=options['limit'])
            else:
                operations = validate_mapping(read_json(options['mapping']), limit=options['limit'])
                plans = [plan_operation(operation) for operation in operations]
            mode = 'undo' if options['undo_audit'] else 'apply'
            if options['apply']:
                audit = new_audit(plans, mode=mode)
                write_audit(options['audit_output'], audit, new=True)
                results = []
                for index, plan in enumerate(plans):
                    result = apply_plan(plan, undo=bool(options['undo_audit']))
                    results.append(result)
                    audit['operations'][index] = result
                    # A failed outcome update leaves the prepared CAS intent
                    # available for a safe undo; never execute another write.
                    write_audit(options['audit_output'], audit)
            else:
                results = plans
                if options['audit_output']:
                    audit = new_audit(plans, mode='dry-run')
                    write_audit(options['audit_output'], audit, new=True)
            for result in results:
                self.stdout.write(json.dumps({'mode': mode if options['apply'] else 'dry-run', **result}, ensure_ascii=False, sort_keys=True))
            summary = {'operations': len(results), 'proposed': sum(row['outcome'] == 'proposed' for row in results),
                       'applied': sum(row['outcome'] in {'applied', 'undone'} for row in results),
                       'conflicts': sum(row['outcome'] == 'conflict' for row in results),
                       'unchanged': sum(row['outcome'] in {'already_satisfied', 'skipped'} for row in results)}
            self.stdout.write(json.dumps({'summary': summary}, sort_keys=True))
        except (RepairInputError, KeyError, TypeError, ValueError) as error:
            raise CommandError(str(error)) from None
