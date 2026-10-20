"""Preview/execute/resume a frozen local repair manifest, without a new worker."""
import fcntl
import json
import os
from pathlib import Path
import time
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from api.rss.body_repair import outcome, preview, submit
from api.rss.operations import OperationError


def save(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with open(temporary, 'w', encoding='utf-8', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class Command(BaseCommand):
    help = 'Preview, execute or resume stored RSS body repairs; requires the existing rss-sync worker.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['preview', 'execute', 'resume'])
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--target-url')
        parser.add_argument('--wait-seconds', type=int, default=120)

    def handle(self, *args, **options):
        if options['action'] == 'preview':
            return self.repair(**options)
        database = str(settings.DATABASES['default']['NAME'])
        directory = Path(tempfile.gettempdir()) if database == ':memory:' or 'mode=memory' in database else Path(database).parent
        lock_path = directory / '.rss-body-repair.lock'
        with lock_path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CommandError('Another body repair is running; resume after it finishes.') from None
            return self.repair(**options)

    def repair(self, **options):
        path = Path(options['manifest'])
        if not 1 <= options['days'] <= 7 or not 1 <= options['wait_seconds'] <= 600:
            raise CommandError('days must be 1..7; wait-seconds must be 1..600.')
        if options['action'] == 'preview':
            if path.exists():
                raise CommandError('Manifest already exists; use resume or a new path.')
            data = preview(days=options['days'], target_url=options['target_url'])
            save(path, data)
        else:
            data = json.loads(path.read_text())
            if data.get('version') != 1:
                raise CommandError('Unsupported manifest version.')
            blocked = set()
            processed = 0
            for row in data['rows']:
                if row['status'] in {'skipped', 'success', 'failed'} or row['binding'] in blocked:
                    continue
                try:
                    operation = submit(row)
                except OperationError as error:
                    row.update(status='skipped', reason=error.code)
                    save(path, data)
                    continue
                row['operation'] = str(operation.pk)
                save(path, data)
                deadline = time.monotonic() + options['wait_seconds']
                while outcome(operation) == 'waiting' and time.monotonic() < deadline:
                    time.sleep(1)
                    operation.refresh_from_db()
                row.update(status=outcome(operation), result=operation.safe_result, state=operation.state)
                if row['status'] == 'waiting':
                    row['status'] = 'unconfirmed'
                if row['status'] == 'unconfirmed':
                    blocked.add(row['binding'])
                processed += 1
                save(path, data)
                if processed % 25 == 0:
                    self.stdout.write(json.dumps({'batch_processed': processed}, ensure_ascii=False))
        counts = {}
        for row in data['rows']:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        self.stdout.write(json.dumps(counts, ensure_ascii=False))
