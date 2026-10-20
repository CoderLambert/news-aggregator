"""Explicit isolated Miniflux/HTTPS-fixture proof, executed as a standalone script.

Requires a newly created synthetic engine with synthetic_admin and fixture.example;
never supplies production credentials or reads a running site's DB.
"""
import json
import os
import uuid


def main():
    if os.environ.get('RSS_RECOVERY_LIVE') != 'synthetic-isolated':
        raise RuntimeError('explicit isolated opt-in required')
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', verbosity=0)
    import miniflux
    from django.contrib.auth import get_user_model
    from api.models import Source
    from api.rss.models import FeedBinding, FeedOperation, SourceFeedLink, SourcePublication
    from api.rss.admin_verification import submit, verification_data
    from api.rss.control_worker import ControlWorker
    from api.rss.engine import EngineAdapter, EngineConfig
    base = 'http://engine:8080'
    admin = miniflux.Client(base, username='synthetic_admin', password='synthetic-recovery-admin')
    collector = admin.create_user('collector_' + uuid.uuid4().hex[:8], 'synthetic-collector', is_admin=False)
    client = miniflux.Client(base, username=collector['username'], password='synthetic-collector')
    key = client.create_api_key('isolated recovery test')['token']
    instance, account = str(uuid.uuid4()), collector['id']
    os.environ['RSS_ENGINE_INSTANCE_UUID'] = instance
    os.environ['RSS_ENGINE_ACCOUNT_ID'] = str(account)
    actor = get_user_model().objects.create_superuser('isolated-admin', password='synthetic-only')
    config = EngineConfig(instance, account, base, key, read_attempts=1, control_timeout=10)
    worker = ControlWorker(config, max_attempts=1)
    results = []
    try:
        for path, expected in (('feed', 'passed'), ('invalid', 'failed')):
            source = Source.objects.create(name='Isolated '+path, url='https://fixture.example/')
            SourcePublication.objects.create(source=source, publication='public', owner='miniflux', reading_policy='standard')
            binding = FeedBinding.objects.create(engine_instance_uuid=instance, account_id=account,
                canonical_feed_url='https://fixture.example/'+path, desired_enabled=True)
            SourceFeedLink.objects.create(source=source, binding=binding, enabled=True, editorial_pin=True)
            from api.rss.operations import enqueue_operation
            proof = enqueue_operation('register', actor=actor, binding=binding, dedupe_key='not-sent-'+path)
            FeedOperation.objects.filter(pk=proof.pk).update(state='failed')
            batch = submit([{'source_id': source.pk, 'expected_versions': {str(binding.pk): 1}}], actor, path, True)
            assert worker.run_once()
            row = verification_data(source)
            assert row['status'] == expected, row
            assert row['can_subscribe'] == (expected == 'passed')
            operation = batch.items.get().operation
            results.append({'scenario': path, 'status': row['status'], 'operation': operation.state,
                'phase': operation.execution_phase, 'error_code': operation.safe_result.get('code', '')})
            if path == 'feed':
                old = FeedOperation.objects.create(kind='register', binding=binding, actor=actor,
                    dedupe_key='old-unknown', request_hash='a'*64, state='manual_blocked', attempts=5,
                    safe_result={'outcome_unknown': True, 'code': 'create_unknown'})
                # Clear request cooldown only in this synthetic fixture.
                from datetime import timedelta
                from django.utils import timezone
                FeedOperation.objects.filter(pk=operation.pk).update(created_at=timezone.now()-timedelta(seconds=61))
                submit([{'source_id': source.pk, 'expected_versions': {str(binding.pk): 1}}], actor, 'reuse', True)
                assert worker.run_once()
                old.refresh_from_db()
                adapter = EngineAdapter(config)
                assert len(adapter.list_feeds()) == 1
                adapter.close()
                assert old.resolved_at and old.attempts == 5 and old.state == 'manual_blocked'
                results.append({'scenario': 'reuse_old_unknown', 'status': 'passed', 'remote_feed_count': 1})
        print(json.dumps({'isolated_miniflux': '2.3.3', 'results': results}, ensure_ascii=False))
    finally:
        worker.close()
        client.close() if hasattr(client, 'close') else None

if __name__ == '__main__': main()
