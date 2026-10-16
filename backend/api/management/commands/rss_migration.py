import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ObjectDoesNotExist

from api.rss.engine import EngineAdapter, EngineConfig, EngineError
from api.rss import source_migration


class Command(BaseCommand):
    help = 'Plan/apply/verify a reviewed RSS source switch group; apply defaults to dry-run.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['plan', 'apply', 'verify'])
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--source-ids', required=True)
        parser.add_argument('--environment', choices=['isolated', 'production'], required=True)
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        adapter = None
        try:
            path = Path(options['manifest'])
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                raise CommandError('manifest_missing_or_too_large')
            manifest = json.loads(path.read_text())
            ids = [int(value) for value in options['source_ids'].split(',')]
            kwargs = dict(source_ids=ids, environment=options['environment'])
            if options['action'] == 'plan' or (options['action'] == 'apply' and not options['execute']):
                result = source_migration.plan(manifest, **kwargs)
                result['dry_run'] = True
            elif options['action'] == 'verify':
                result = source_migration.verify(manifest, **kwargs)
            else:
                # Target validation precedes any engine configuration or network.
                source_migration.plan(manifest, **kwargs)
                adapter = EngineAdapter(EngineConfig.from_environment())
                result = source_migration.apply(manifest, adapter=adapter, execute=True, **kwargs)
            self.stdout.write(json.dumps(result, sort_keys=True))
            if result.get('verified') is False:
                raise CommandError(result.get('reason', 'verification_failed'))
        except ObjectDoesNotExist:
            raise CommandError('manifest_object_missing') from None
        except (source_migration.MigrationBlocked, EngineError, KeyError, TypeError, ValueError) as error:
            raise CommandError(str(error)) from None
        finally:
            if adapter is not None:
                adapter.close()
