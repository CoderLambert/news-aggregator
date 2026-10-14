"""Review-only by default; execute modifies just approved bounded metadata."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from api.services.metadata_corrections import preview, apply, undo, validate_plan


class Command(BaseCommand):
    help = 'Preview or apply/undo a bounded category/country correction. No fetching or AI.'

    def add_arguments(self, parser):
        parser.add_argument('--source-key')
        parser.add_argument('--entity', choices=['news_category', 'source_country'], default='news_category')
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--output')
        parser.add_argument('--plan')
        parser.add_argument('--undo-run')
        parser.add_argument('--operator')
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        try:
            if options['undo_run']:
                if options['plan'] or options['source_key'] or options['output']:
                    raise ValueError('Undo cannot be combined with another selection')
                if not options['execute']:
                    self.stdout.write(json.dumps({'mode': 'undo_dry_run', 'run_id': options['undo_run']})); return
                result = undo(options['undo_run'])
            elif options['plan']:
                path = Path(options['plan'])
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                    raise ValueError('Plan must be a regular file no larger than 1MiB')
                plan = json.loads(path.read_text(encoding='utf-8')); validate_plan(plan)
                result = apply(plan, operator=options['operator']) if options['execute'] else {'mode': 'apply_dry_run', 'plan': plan}
            else:
                if options['execute']:
                    raise ValueError('First generate and review a plan; execute requires --plan')
                result = preview(options['source_key'], options['entity'], after_id=options['after_id'], limit=options['limit'])
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if options['output']:
                path = Path(options['output'])
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(text + '\n')
                self.stdout.write('Preview written; no database values changed.')
            else:
                self.stdout.write(text)
        except (ValueError, TypeError, OSError) as exc:
            raise CommandError(str(exc)) from None
