"""Only for the owner-validated, offline newsaggregator.dev_settings profile."""
import json
import sys

from django.core.management.base import BaseCommand, CommandError
from newsaggregator.dev_defaults import BootstrapError, seed_defaults


class Command(BaseCommand):
    help = 'Create/preserve isolated development accounts and unverified private model candidates.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--key-stdin', action='store_true', help='Read an optional key from a private pipe, never argv.')
        parser.add_argument('--existing-only', action='store_true', help='Import only after explicit initialization.')

    def handle(self, *args, **options):
        try:
            key = None
            if options['key_stdin']:
                raw = sys.stdin.buffer.read(4099)
                if len(raw) > 4098:
                    raise BootstrapError('invalid_development_key')
                if raw:
                    key = raw.decode('ascii').rstrip('\r\n')
                    if not key or len(key) > 4096:
                        raise BootstrapError('invalid_development_key')
            result = seed_defaults(key, existing_only=options['existing_only'])
        except BootstrapError as error:
            raise CommandError(str(error)) from None
        except Exception:
            # No input, ciphertext, SQL or arbitrary exception text in CLI/logs.
            raise CommandError('development_bootstrap_failed; state preserved for inspection') from None
        self.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
