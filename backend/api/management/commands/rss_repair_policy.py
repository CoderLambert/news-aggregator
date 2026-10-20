"""Explicit target-feed opt in and CAS rollback; never infer a manual preference."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from api.management.commands.rss_repair_bodies import save
from api.rss.feed_policy import assert_binding_policy
from api.rss.models import FeedBinding, FeedOperation
from api.rss.operations import change_policy, OperationError


class Command(BaseCommand):
    help = 'Preview/enable a specifically authorized target feed, or restore its old mode with CAS.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['preview', 'execute', 'restore'])
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--target-feed')

    def handle(self, *args, **options):
        path = Path(options['manifest'])
        if options['action'] == 'preview':
            if path.exists():
                raise CommandError('Manifest already exists.')
            rows = []
            for binding in FeedBinding.objects.order_by('id'):
                row = dict(binding=str(binding.pk), feed=binding.canonical_feed_url,
                           original_mode=binding.desired_mode, version=binding.policy_version,
                           status='skipped', reason='mode_origin_unconfirmed')
                try:
                    decision = assert_binding_policy(binding)
                    if binding.desired_mode == 'full_content':
                        row['reason'] = 'already_enabled'
                    elif decision.desired_mode != 'full_content':
                        row['reason'] = decision.reason
                    elif binding.canonical_feed_url == options['target_feed'] and binding.desired_enabled:
                        row.update(status='candidate', reason='explicit_target_authorization')
                    elif FeedOperation.objects.filter(binding=binding, kind='update_feed_policy', actor__isnull=False).exists():
                        row['reason'] = 'manual_mode_preserved'
                except OperationError as error:
                    row['reason'] = error.code
                rows.append(row)
            data = dict(version=1, rows=rows)
            save(path, data)
        else:
            data = json.loads(path.read_text())
            if data.get('version') != 1:
                raise CommandError('Unsupported manifest version.')
            for row in data['rows']:
                if row['status'] == 'skipped':
                    continue
                restore = options['action'] == 'restore'
                if restore and not FeedOperation.objects.filter(
                        dedupe_key=f"body-repair-policy:{row['binding']}:{row['version']}:enable",
                        actor=None, kind='update_feed_policy').exists():
                    raise CommandError('Cannot restore a policy not changed by this manifest.')
                # The fixed key makes a crash after DB commit safe to resume.
                version = row['version'] + (1 if restore else 0)
                key = f"body-repair-policy:{row['binding']}:{row['version']}:{'restore' if restore else 'enable'}"
                operation = change_policy(row['binding'], expected_policy_version=version,
                    desired_mode=row['original_mode'] if restore else 'full_content', dedupe_key=key)
                row.update(status='restoring' if restore else 'submitted', operation=str(operation.pk))
                save(path, data)
        self.stdout.write(json.dumps(data, ensure_ascii=False))
