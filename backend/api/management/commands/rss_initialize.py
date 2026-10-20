"""Preview by default; mutation is restricted to an explicitly named local engine."""
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from api.rss.initialize import counts, cutoff_date, defaults, initialize, initialization_status
from api.rss.models import RSSInitialization
from api.rss.subscriptions import engine_identity


def validate_local(instance):
    host = urlsplit(os.environ.get('RSS_ENGINE_BASE_URL', '')).hostname
    if (os.environ.get('NEWSHUB_LOCAL_INSTANCE') != str(instance)
            or host not in {'miniflux', 'localhost', '127.0.0.1', '::1'}):
        raise CommandError('rss_initialize applies only to the explicitly marked local engine instance.')


def validate_backup(directory, instance, account):
    path = Path(directory)
    if (not path.is_absolute() or path.is_symlink() or path.resolve() != path
            or not path.is_dir() or path.stat().st_mode & 0o077):
        raise CommandError('A protected absolute paired backup directory is required.')
    try:
        receipt = json.loads((path / 'backup.json').read_text())
        if receipt['instance_uuid'] != str(instance) or receipt['account_id'] != account:
            raise ValueError
        for name in ('application.sqlite3', 'miniflux.dump', 'configuration.tar'):
            artifact = path / name
            if (artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size == 0
                    or sha256(artifact.read_bytes()).hexdigest() != receipt['sha256'][name]):
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise CommandError('Paired backup is missing, changed, or belongs to another engine.') from None
    return str(path)


class Command(BaseCommand):
    help = 'Preview pinned RSS defaults; --apply --reset-content requires a stopped local target and paired backup.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--local-instance', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--reset-content', action='store_true')
        parser.add_argument('--backup-dir', default='')

    def handle(self, *args, **options):
        instance, account = engine_identity()
        if options['local_instance'] != str(instance):
            raise CommandError('Local engine identity mismatch.')
        manifest, checksum = defaults()
        has_schema = RSSInitialization._meta.db_table in connection.introspection.table_names()
        existing = (RSSInitialization.objects.filter(engine_instance_uuid=instance, account_id=account,
            manifest_version=manifest['version']).first() if has_schema else None)
        result = {'preview': not options['apply'], 'instance_uuid': str(instance), 'account_id': account,
            'manifest': manifest['version'], 'manifest_sha256': checksum,
            'already_initialized': bool(existing), 'reset_content': options['reset_content'],
            'cutoff_date_utc': str(existing.cutoff_date if existing else cutoff_date()),
            'counts': counts(), 'feeds': manifest['feeds']}
        if options['apply']:
            validate_local(instance)
            backup = options['backup_dir']
            if options['reset_content'] and not existing:
                backup = validate_backup(backup, instance, account)
            record, changed = initialize(instance, account, reset=options['reset_content'], backup_path=backup)
            result.update(changed=changed, cutoff_date_utc=str(record.cutoff_date), counts_after=counts())
        result['runtime'] = initialization_status(instance, account) if has_schema else None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
