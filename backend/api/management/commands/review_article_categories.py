"""No writes by default. An operator must explicitly apply an inspected plan."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from api.services.category_corrections import build_plan, execute_plan


class Command(BaseCommand):
    help = 'Create an inspected source-scoped category plan, or explicitly apply/undo it.'

    def add_arguments(self, parser):
        parser.add_argument('--source-key')
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--output', help='New mode-0600 JSON plan; never overwritten')
        parser.add_argument('--plan', help='Previously inspected plan (max 1 MiB)')
        action = parser.add_mutually_exclusive_group()
        action.add_argument('--apply', action='store_true')
        action.add_argument('--undo', action='store_true')

    def handle(self, *args, **options):
        try:
            if options['apply'] or options['undo']:
                if not options['plan'] or options['output']:
                    raise ValueError('--plan required for apply/undo; --output not accepted')
                path = Path(options['plan'])
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                    raise ValueError('plan must be a small regular JSON file')
                result = execute_plan(json.loads(path.read_text()), undo=options['undo'])
            else:
                if not options['source_key'] or options['plan']:
                    raise ValueError('--source-key required for dry-run')
                result = build_plan(options['source_key'], limit=options['limit'], after_id=options['after_id'])
                if options['output']:
                    fd = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'w') as handle:
                        json.dump(result, handle, ensure_ascii=False, indent=2)
                        handle.write('\n')
            self.stdout.write(json.dumps(result, ensure_ascii=False))
        except (ValueError, KeyError, OSError) as exc:
            raise CommandError(str(exc)) from exc
