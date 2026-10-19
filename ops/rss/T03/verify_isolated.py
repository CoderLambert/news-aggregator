#!/usr/bin/env python3
"""Real PG/SQLite paired restore; synthetic data in a newly named Docker project."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.rss import recovery as rss


def run(args, *, input=None, env=None, ok=True):
    result = subprocess.run(args, input=input, env=env, capture_output=True, text=True, timeout=180)
    if ok and result.returncode:
        # Commands in this synthetic experiment contain no production credentials.
        raise RuntimeError(result.stderr[-3000:])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    docker = rss.Docker()  # local Unix endpoint check before creating anything
    project = 'newshub-rss-t03-' + uuid.uuid4().hex[:12]
    assert not run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
    for resource in ('network', 'volume'):
        assert not run(['docker', resource, 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
    versions = json.loads((ROOT / 'ops/rss/T00/versions.json').read_text())['images']
    engine_image, pg_image, python_image = [item['tag'] + '@' + item['repo_digests'][0].split('@')[1] for item in versions]
    sha = run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).stdout.strip()
    evidence = {'baseline_sha': sha, 'scope': 'synthetic isolated recovery; no production compatibility seal'}
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        temporary = Path(directory)
        db_dir = temporary / 'sqlite'
        db_dir.mkdir()
        db_path = db_dir / 'db.sqlite3'
        instance = str(uuid.uuid4())
        pg_url = 'postgres://rss_contract:synthetic-t03-only@rss-db/rss_contract?sslmode=disable'
        services = {
            'rss-db': {'image': pg_image, 'environment': {'POSTGRES_DB': 'rss_contract',
                'POSTGRES_USER': 'rss_contract', 'POSTGRES_PASSWORD': 'synthetic-t03-only'},
                'volumes': ['rss-pg-data:/var/lib/postgresql/data'], 'networks': ['isolated'],
                'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -h 127.0.0.1 -U rss_contract -d rss_contract'], 'interval': '1s', 'retries': 60}},
            'fixture': {'image': python_image, 'command': ['python', '/fixture/server.py'],
                'volumes': [str(ROOT / 'ops/rss/T00/server.py') + ':/fixture/server.py:ro'], 'networks': ['isolated']},
            'miniflux': {'image': engine_image, 'depends_on': {'rss-db': {'condition': 'service_healthy'}},
                'environment': {'DATABASE_URL': pg_url, 'RUN_MIGRATIONS': '1', 'CREATE_ADMIN': '1',
                    'ADMIN_USERNAME': 'synthetic_admin', 'ADMIN_PASSWORD': 'synthetic-admin-only',
                    'FETCHER_ALLOW_PRIVATE_NETWORKS': '1', 'POLLING_FREQUENCY': '999999',
                    'CLEANUP_ARCHIVE_READ_DAYS': '90', 'CLEANUP_ARCHIVE_UNREAD_DAYS': '90', 'LOG_LEVEL': 'error'},
                'ports': ['127.0.0.1::8080'], 'networks': ['isolated'],
                'healthcheck': {'test': ['CMD', '/usr/bin/miniflux', '-healthcheck', 'auto'], 'interval': '1s', 'retries': 60}},
        }
        for role in rss.ROLES:
            services[role] = {'image': python_image, 'command': ['python', '-c',
                'import signal,time; signal.signal(signal.SIGTERM, lambda *_: exit(0)); time.sleep(3600)'],
                'volumes': [str(db_dir) + ':/var/lib/newshub/db'], 'network_mode': 'none'}
        compose_file = temporary / 'compose.json'
        compose_file.write_text(json.dumps({'services': services, 'volumes': {'rss-pg-data': {}},
                                         'networks': {'isolated': {'driver': 'bridge'}}}))
        compose = ['docker', 'compose', '-p', project, '-f', str(compose_file)]
        def call(*arguments):
            return run(compose + list(arguments)).stdout.strip()
        print('isolated project:', project, flush=True)
        fresh_engine = None
        try:
            call('up', '-d', '--wait')
            address = call('port', 'miniflux', '8080')
            assert address.startswith('127.0.0.1:')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def api(path, data, username='synthetic_admin', password='synthetic-admin-only'):
                auth = base64.b64encode((username + ':' + password).encode()).decode()
                request = urllib.request.Request('http://' + address + '/v1/' + path,
                    data=None if data is None else json.dumps(data).encode(),
                    headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'})
                with opener.open(request, timeout=30) as response:
                    return json.load(response)
            account = api('users', {'username': 'synthetic_collector', 'password': 'synthetic-collector-only', 'is_admin': False})
            feed = api('feeds', {'feed_url': 'http://fixture:8000/feed', 'crawler': False}, 'synthetic_collector', 'synthetic-collector-only')
            entries = api('entries?order=id&direction=asc', None, 'synthetic_collector', 'synthetic-collector-only')['entries']
            assert entries
            environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'backend'), 'RUN_MAIN': 'true',
                'NEWSHUB_RUNTIME_ROLE': 'rss_sync', 'DJANGO_DB_PATH': str(db_path),
                'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings'}
            seeded = json.loads(run([args.python, str(ROOT / 'ops/rss/T03/seed_sqlite.py')], env=environment,
                input=json.dumps({'instance_uuid': instance, 'account_id': account['id'], 'feed_id': feed['feed_id'],
                                  'entry_id': entries[0]['id'], 'entry_url': entries[0]['url']})).stdout)
            pg_id, engine_id = call('ps', '-q', 'rss-db'), call('ps', '-q', 'miniflux')
            pg_version = run(['docker', 'exec', pg_id, 'psql', '-U', 'rss_contract', '-d', 'rss_contract', '-Atc',
                              'SELECT max(version) FROM schema_version']).stdout.strip()
            manifest = {'schema_version': 1, 'environment': 'isolated', 'project': project,
                'release': {'schema_version': 3, 'release_sha': sha, 'image': 'newshub-synthetic:' + sha,
                    'static_sha': 'a' * 64, 'migrations': seeded['migrations'],
                    'capabilities': {'full_content_worker': True, 'channel_worker': True}},
                'sqlite': {'path': str(db_path)},
                'postgres': {'container_id': pg_id, 'image': pg_image, 'database': 'rss_contract',
                    'user': 'rss_contract', 'volume': project + '_rss-pg-data'},
                'engine': {'container_id': engine_id, 'image': engine_image, 'instance_uuid': instance,
                    'account_id': account['id'], 'username': 'synthetic_collector', 'schema_version': int(pg_version)},
                'writers': {'roles': {role: [call('ps', '-q', role)] for role in rss.ROLES},
                    'host_processes': [], 'schedulers': [], 'host_inventory_complete': True},
                'other_containers': {'fixture': call('ps', '-q', 'fixture')}, 'secret_refs': {}, 'rollback': None}
            manifest_file = temporary / 'target.json'
            manifest_file.write_text(json.dumps(manifest))
            def operation(action, *arguments, ok=True, value=None):
                manifest_file.write_text(json.dumps(value or manifest))
                return run([args.python, str(ROOT / 'scripts/rss/recovery.py'), action, '--environment', 'isolated',
                    '--manifest', str(manifest_file), '--target-project', project, *map(str, arguments)], ok=ok)
            first = temporary / 'pair-before'
            assert json.loads(operation('backup', '--output', first).stdout)['dry_run'] and not first.exists()
            assert operation('backup', '--output', first, '--execute', ok=False).returncode == 2
            assert not first.exists() and docker.inspect(engine_id)['State']['Running']
            operation('backup', '--output', first, '--execute', '--stop-writers')
            original = rss.load_pair(first, manifest)
            assert not docker.inspect(engine_id)['State']['Running']
            # A real later commit in each DB creates an explicit RPO difference.
            with sqlite3.connect(db_path) as db:
                db.execute("UPDATE api_news SET full_content='synthetic later body'")
            docker.sql(manifest, "UPDATE entries SET content='synthetic later engine body';")
            prior = temporary / 'pair-prior'
            operation('backup', '--output', prior, '--execute')
            state_before_rejection = rss.sqlite_state(db_path, manifest)['logical_sha256'], rss.pg_state(manifest, docker)
            assert operation('restore', '--source', first, '--replace', '--prior-backup', first, '--execute', ok=False).returncode == 2
            bad = json.loads(json.dumps(manifest))
            bad['engine']['instance_uuid'] = str(uuid.uuid4())
            assert operation('restore', '--source', first, '--replace', '--prior-backup', prior, '--execute', value=bad, ok=False).returncode == 2
            bad['engine']['instance_uuid'] = instance
            bad['engine']['schema_version'] += 1
            assert operation('restore', '--source', first, '--replace', '--prior-backup', prior, '--execute', value=bad, ok=False).returncode == 2
            corrupted = temporary / 'wrong-pair'
            shutil.copytree(first, corrupted)
            with (corrupted / 'miniflux.dump').open('ab') as stream:
                stream.write(b'tampered')
            assert operation('restore', '--source', corrupted, '--replace', '--prior-backup', prior, '--execute', ok=False).returncode == 2
            assert state_before_rejection == (rss.sqlite_state(db_path, manifest)['logical_sha256'], rss.pg_state(manifest, docker))
            restored = json.loads(operation('restore', '--source', first, '--replace', '--prior-backup', prior, '--execute').stdout)
            assert rss.sqlite_state(db_path, manifest)['logical_sha256'] == original['sqlite_logical_sha256']
            assert rss.pg_state(manifest, docker) == original['pg_logical_sha256']
            operation('restore', '--source', first, '--replace', '--prior-backup', first, '--execute')
            with sqlite3.connect(db_path) as db:
                assert not db.execute('PRAGMA foreign_key_check').fetchall()
                expected_counts = {'auth_user': 1, 'api_channelsubscription': 1, 'api_channelgroupmember': 1,
                    'api_favorite': 1, 'api_newsreadstate': 1, 'api_legacytranslationsnapshot': 1,
                    'api_engineentrymap': 1, 'api_feedoperation': 1}
                for table, count in expected_counts.items():
                    assert db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == count
                assert db.execute('SELECT full_content_zh FROM api_news').fetchone()[0] == '保留旧中文正文'
            # Recover into an explicitly empty PG database and absent SQLite too.
            # Replace only our stopped engine identity so its configured DB URL
            # points at that fresh target; the restored UUID/account are preserved.
            docker.sql(manifest, 'CREATE DATABASE rss_fresh OWNER rss_contract;')
            run(['docker', 'rm', engine_id])
            fresh_engine = run(['docker', 'create', '--name', project + '-miniflux-fresh',
                '--label', 'com.docker.compose.project=' + project,
                '--label', 'com.docker.compose.service=miniflux', '--network', project + '_isolated',
                '--env', 'DATABASE_URL=' + pg_url.replace('/rss_contract?', '/rss_fresh?'), engine_image]).stdout.strip()
            fresh_manifest = json.loads(json.dumps(manifest))
            fresh_manifest['engine']['container_id'] = fresh_engine
            fresh_manifest['postgres']['database'] = 'rss_fresh'
            fresh_manifest['sqlite']['path'] = str(db_dir / 'fresh.sqlite3')
            fresh_result = json.loads(operation('restore', '--source', first, '--fresh', '--execute', value=fresh_manifest).stdout)
            assert fresh_result['mapping_sha256'] == original['mapping_sha256']
            assert rss.pg_state(fresh_manifest, docker) == original['pg_logical_sha256']
            evidence.update(project=project, sqlite_migrations=seeded['migrations'], engine_schema=int(pg_version),
                engine_image=engine_image, postgres_image=pg_image, python=run([args.python, '--version']).stdout.strip(),
                paired_restore='PASS', overwrite_replay='PASS', fresh_pair_restore='PASS', foreign_keys='PASS', relationships=expected_counts,
                wrong_pair_instance_schema_prior='REFUSED', active_writers='REFUSED',
                mapping_sha256=restored['mapping_sha256'], service_account=restored['service_account'],
                full_app_rollback='NOT_RUN: application compatibility is T26; command path tested separately',
                synthetic_writer_roles=sorted(rss.ROLES), production='NOT_RUN')
        finally:
            call('down', '--volumes', '--remove-orphans')
            # Compose does not always list/remove manually created, never-started
            # containers. Remove only this exact ID created above, after checking
            # its project label; never sweep containers from a name prefix.
            if fresh_engine and run(['docker', 'ps', '-aq', '--filter', 'id=' + fresh_engine]).stdout.strip():
                assert docker.inspect(fresh_engine)['Config']['Labels']['com.docker.compose.project'] == project
                run(['docker', 'rm', fresh_engine])
        assert not call('ps', '-aq')
        assert not run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
        assert not run(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
        assert not run(['docker', 'network', 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]).stdout.strip()
        evidence['resources_removed'] = True
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    print('PASS: real paired overwrite/replay, identity/hash refusals and resource cleanup')


if __name__ == '__main__':
    main()
