#!/usr/bin/env python3
"""Observe a LOCAL controller stop + engine restart, then record the boundary.

Preview is read-only. No feed/content/database reset. The caller first installs
and migrates a candidate whose app AND rss-sync include the recovery worker.
Only the selected dedicated controller and the same Miniflux container restart.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path

from initialize import environment, inspect, inventory, require, run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    services, env = inventory(args.project)
    worker, engine, app = (services[n] for n in ('rss-sync', 'miniflux', 'app'))
    instance = env['RSS_ENGINE_INSTANCE_UUID']
    require(worker['State']['Running'] and engine['State']['Running'] and app['State']['Running'], 'All selected local services must be running.')
    # Multiple controllers or an unreviewed candidate cannot establish a boundary.
    require(app['Image'] == worker['Image'], 'Install the same recovery candidate in app and rss-sync first.')
    require(not any(c['State']['Running'] for n, c in services.items() if n in {'migrate', 'crawler', 'full-content'}), 'Other collection/maintenance writers must already be stopped.')
    require(environment(app).get('NEWSHUB_LOCAL_INSTANCE', instance) == instance, 'Local instance marker mismatch.')
    require(not args.receipt.exists(), 'Use a fresh evidence receipt path.')
    summary = {'project': args.project, 'instance': instance, 'account': int(env['RSS_ENGINE_ACCOUNT_ID']),
        'worker_container': worker['Id'], 'engine_container': engine['Id'], 'preview': not args.apply}
    code = ('from api.rss.models import FeedOperation; from api.rss.admin_verification import record_restart_boundary; '
            'from api.rss.control_worker import ControlWorker; '
            'assert FeedOperation._meta.get_field("execution_phase"); '
            'assert FeedOperation._meta.get_field("resolved_at")')
    run(['docker', 'exec', app['Id'], 'python', '/app/backend/manage.py', 'shell', '-c', code])
    if not args.apply:
        print(json.dumps(summary)); return
    os.umask(0o077)
    run(['docker', 'stop', '--time', '20', worker['Id']], timeout=45)
    stopped = inspect(worker['Id'])
    require(not stopped['State']['Running'], 'Controller did not stop.')
    run(['docker', 'restart', '--time', '20', engine['Id']], timeout=45)
    restarted = inspect(engine['Id'])
    require(restarted['Id'] == engine['Id'] and restarted['State']['Running'], 'Engine identity changed.')
    evidence = {'worker_container': worker['Id'], 'engine_container': engine['Id'],
        'worker_stopped_at': stopped['State']['FinishedAt'], 'engine_previous_start': engine['State']['StartedAt'],
        'engine_started_at': restarted['State']['StartedAt']}
    # ISO timestamps from Docker include nanoseconds; Python accepts/truncates
    # them to microseconds conservatively for the persisted boundary comparison.
    parse = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parse(evidence['engine_previous_start']) < parse(evidence['worker_stopped_at']) < parse(evidence['engine_started_at']), 'Restart ordering unproven.')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(evidence, indent=2)+'\n')
    # docker cp preserves host UID/mode: a 0600 host receipt would be unreadable
    # by the app's non-root UID. Create it using the application identity.
    import hashlib
    data = args.receipt.read_bytes()
    remote = '/tmp/rss-recovery-boundary-' + hashlib.sha256(data).hexdigest()[:16] + '.json'
    writer = ('import os,sys; fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); '
              'os.write(fd,sys.stdin.buffer.read()); os.close(fd)')
    run(['docker', 'exec', '-i', app['Id'], 'python', '-c', writer, remote], input=data)
    result = run(['docker', 'exec', '-e', 'NEWSHUB_LOCAL_INSTANCE='+instance, app['Id'], 'python',
        '/app/backend/manage.py', 'rss_recovery_boundary', '--local-instance', instance,
        '--evidence-file', remote])
    run(['docker', 'start', worker['Id']])
    print(json.dumps({**summary, 'preview': False, 'boundary': json.loads(result)}))

if __name__ == '__main__': main()
