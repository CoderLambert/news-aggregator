"""Record an externally observed local engine restart; never resets content."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from api.rss.admin_verification import record_restart_boundary
from api.rss.subscriptions import engine_identity


class Command(BaseCommand):
    help = 'Record a proven local control-stop/engine-restart boundary from a maintenance receipt.'
    def add_arguments(self, parser):
        parser.add_argument('--local-instance', required=True)
        parser.add_argument('--evidence-file', required=True)
    def handle(self, *args, **options):
        instance, account = engine_identity()
        if options['local_instance'] != str(instance) or os.environ.get('NEWSHUB_LOCAL_INSTANCE') != str(instance):
            raise CommandError('Requires the explicitly marked local instance.')
        try:
            raw = Path(options['evidence_file']).read_bytes()
            if len(raw) > 8192: raise ValueError
            evidence = json.loads(raw)
            count = record_restart_boundary(instance, account, evidence)
        except (OSError, ValueError, TypeError, KeyError):
            raise CommandError('Invalid observed restart receipt.') from None
        self.stdout.write(json.dumps({'resolved_operations': count}))
