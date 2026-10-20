#!/usr/bin/env python3
"""Local paired backup/reset wrapper. Preview is the default; failures stay stopped.

Only the explicitly named local Compose project is inspected/mutated. Run from
the local stack directory, passing its complete Compose file list. No production
mode, remote Docker endpoint, volume deletion, or automatic retry is supported.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time

WRITERS = {'app', 'rss-sync', 'channel-worker', 'indexer', 'crawler', 'full-content', 'migrate'}


class InitializeError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InitializeError(message)


def run(args, *, output=None, input=None, timeout=180):
    try:
        result = subprocess.run(args, input=input, stdout=output or subprocess.PIPE,
            stderr=subprocess.PIPE, check=True, timeout=timeout)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise InitializeError('Command failed; leave the named target stopped and inspect protected diagnostics.') from None


def inspect(identity):
    return json.loads(run(['docker', 'inspect', identity]))[0]


def environment(container):
    return dict(row.split('=', 1) for row in container['Config']['Env'] if '=' in row)


def inventory(project):
    endpoint = os.environ.get('DOCKER_HOST') or run(['docker', 'context', 'inspect',
        '--format', '{{.Endpoints.docker.Host}}']).decode().strip()
    require(endpoint.startswith('unix://'), 'Only the local Docker Unix socket is supported.')
    require(re.fullmatch(r'newshub-(?:local|rss)-[a-z0-9_-]+', project), 'Explicit local project namespace required.')
    identities = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).decode().split()
    containers = [inspect(identity) for identity in identities]
    services = {}
    for container in containers:
        labels = container['Config'].get('Labels') or {}
        require(labels.get('com.docker.compose.project') == project, 'Compose target changed.')
        if labels.get('com.docker.compose.oneoff') == 'True':
            require(not container['State']['Running'], 'A one-off task is still running.')
            continue
        service = labels.get('com.docker.compose.service')
        require(service not in services, 'Replicated services need a separate reviewed maintenance procedure.')
        services[service] = container
    require({'app', 'rss-sync', 'miniflux', 'rss-db'} <= services.keys(), 'Incomplete local RSS stack.')
    engine_env, app_env = environment(services['rss-sync']), environment(services['app'])
    for key in ('RSS_ENGINE_INSTANCE_UUID', 'RSS_ENGINE_ACCOUNT_ID'):
        require(engine_env.get(key) == app_env.get(key) and bool(engine_env.get(key)), 'Application/engine identity mismatch.')
    require(engine_env.get('RSS_ENGINE_BASE_URL', '').startswith('http://miniflux:'), 'Local engine service required.')
    for service in ('miniflux', 'app'):
        for bindings in (services[service]['HostConfig'].get('PortBindings') or {}).values():
            require(all(row['HostIp'] in {'127.0.0.1', '::1'} for row in bindings or []), 'Target publishes a nonlocal port.')
    # A container from another project sharing a DB volume is an undiscovered writer.
    volumes = {m['Name'] for name in ('app', 'rss-db') for m in services[name]['Mounts'] if m['Type'] == 'volume'}
    require(volumes and all(name.startswith(project + '_') for name in volumes), 'Database volumes must belong to the named project.')
    known = {c['Id'] for c in containers}
    for volume in volumes:
        attached = run(['docker', 'ps', '-q', '--no-trunc', '--filter', 'volume=' + volume]).decode().split()
        require(set(attached) <= known, 'Another project is writing a target volume.')
    return services, engine_env


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()



@contextmanager
def readable_backup(backup, image):
    """Keep mode 700/600 while lending this task-created backup to app UID.

    The maintenance app retains cap_drop=ALL and its normal non-root UID.
    A networkless helper changes only the new backup's ownership, then restores it.
    """
    def owner(uid, gid):
        code = ("import os,pathlib; p=pathlib.Path('/backup'); "
                "[(os.chown(f," + str(uid) + "," + str(gid) + "),os.chmod(f,0o600)) "
                "for f in p.iterdir() if f.is_file()]; "
                "os.chown(p," + str(uid) + "," + str(gid) + "); os.chmod(p,0o700)")
        run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--entrypoint', 'python',
             '-v', str(backup) + ':/backup', image, '-c', code])
    try:
        owner(10001, 10001)
        yield
    finally:
        owner(os.getuid(), os.getgid())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--compose-file', action='append', required=True)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--reset-content', action='store_true')
    parser.add_argument('--settle-timeout', type=int, default=1200)
    args = parser.parse_args(argv)
    require(30 <= args.settle_timeout <= 1800, 'Settle timeout must be 30..1800 seconds.')
    os.umask(0o077)
    services, env = inventory(args.project)
    files = [Path(name).resolve(strict=True) for name in args.compose_file]
    compose = ['docker', 'compose', '-p', args.project]
    for path in files:
        compose += ['-f', str(path)]
    # Read the exact intended configuration without printing interpolated secrets.
    config = json.loads(run(compose + ['config', '--format', 'json']))
    config_refs = json.loads(run(compose + ['config', '--no-env-resolution', '--format', 'json']))
    for service in ('app', 'rss-db'):
        actual_volumes = {m['Name'] for m in services[service]['Mounts'] if m['Type'] == 'volume'}
        selected_volumes = {config.get('volumes', {}).get(m['source'], {}).get('name', m['source'])
            for m in config['services'][service].get('volumes', []) if m['type'] == 'volume'}
        require(selected_volumes <= actual_volumes, 'Compose DB volumes differ from the stopped target.')
    require({'app', 'rss-sync', 'miniflux', 'rss-db'} <= config['services'].keys(), 'Incomplete Compose configuration.')
    instance, account = env['RSS_ENGINE_INSTANCE_UUID'], int(env['RSS_ENGINE_ACCOUNT_ID'])
    backup = args.backup_dir.absolute()
    require(not backup.is_symlink() and backup.parent.resolve() == backup.parent, 'Real absolute backup parent required.')
    command = ['/app/backend/manage.py', 'rss_initialize', '--local-instance', instance]
    def app_command(extra, *, mount=False):
        call = compose + ['run', '--rm', '--no-deps', '--user', '10001:10001', '--entrypoint', 'python',
            '-e', 'NEWSHUB_LOCAL_INSTANCE=' + instance, '-e', 'RSS_ENGINE_BASE_URL=http://miniflux:8080',
            '-e', 'RUN_MAIN=true']
        if mount:
            call += ['-v', str(backup) + ':/backup:ro']
            with readable_backup(backup, services['app']['Image']):
                return run(call + ['app'] + extra)
        return run(call + ['app'] + extra)
    # Before stopping anything, prove the selected image has the new command.
    preview = json.loads(app_command(command))
    require(preview['instance_uuid'] == instance and preview['account_id'] == account, 'Preview target mismatch.')
    print(json.dumps({'project': args.project, 'preview': not args.apply,
        'already_initialized': preview['already_initialized'], 'counts': preview['counts'],
        'cutoff_date_utc': preview['cutoff_date_utc'], 'writers': sorted(WRITERS & services.keys()),
        'backup_dir': str(backup)}, sort_keys=True))
    if not args.apply:
        return
    if preview['already_initialized']:
        # Do not stop writers, clear the engine, or touch new content on a replay.
        result = json.loads(app_command(command + ['--apply'] + (['--reset-content'] if args.reset_content else [])))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    require(args.reset_content, 'This maintenance wrapper requires --apply --reset-content; use rss_initialize directly for additive defaults.')
    require(not backup.exists(), 'A fresh paired backup directory is required; never overwrite an earlier backup.')
    backup.mkdir(mode=0o700)
    journal = backup / 'maintenance.json'
    def checkpoint(phase):
        journal.write_text(json.dumps({'project': args.project, 'instance_uuid': instance,
            'phase': phase, 'containers': {name: c['Id'] for name, c in services.items()},
            'images': {name: c['Image'] for name, c in services.items()}}, sort_keys=True))
    checkpoint('prepared')
    stopping = [c['Id'] for name, c in services.items() if name in WRITERS | {'miniflux'} and c['State']['Running']]
    if stopping:
        run(['docker', 'stop', '--time', '45', *stopping], timeout=240)
    require(all(not inspect(c['Id'])['State']['Running'] for name, c in services.items()
        if name in WRITERS | {'miniflux'}), 'A target writer did not exit.')
    checkpoint('writers_stopped')
    app, pg = services['app'], services['rss-db']
    pg_env = environment(pg)
    require(pg_env.get('POSTGRES_DB') == 'miniflux' and pg_env.get('POSTGRES_USER') == 'miniflux', 'Dedicated Miniflux DB required.')
    # Snapshot through SQLite backup; do not copy a WAL/live file.
    db_path = environment(app)['DJANGO_DB_PATH']
    require(db_path == '/var/lib/newshub/db/db.sqlite3', 'Unexpected local application DB path.')
    code = "import sqlite3; a=sqlite3.connect('file:" + db_path + "?mode=ro',uri=True); a.execute('PRAGMA query_only=ON'); b=sqlite3.connect('/backup/application.sqlite3'); a.backup(b); b.close(); a.close(); __import__('os').chmod('/backup/application.sqlite3',0o600)"
    run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--entrypoint', 'python',
        '--volumes-from', app['Id'], '-v', str(backup) + ':/backup', app['Image'], '-c', code])
    with (backup / 'miniflux.dump').open('wb') as handle:
        run(['docker', 'exec', pg['Id'], 'pg_dump', '-U', 'miniflux', '-d', 'miniflux', '-Fc'], output=handle)
    # Include exact Compose and referenced configuration/secrets, privately and locally.
    with tarfile.open(backup / 'configuration.tar', 'w') as archive:
        encoded = json.dumps(config, sort_keys=True).encode()
        member = tarfile.TarInfo('resolved-compose.json')
        member.size, member.mode = len(encoded), 0o600
        archive.addfile(member, io.BytesIO(encoded))
        paths = set(files)
        for path in files:
            if (path.parent / '.env').is_file():
                paths.add(path.parent / '.env')
        for service in config_refs['services'].values():
            for entry in service.get('env_file', []):
                paths.add(Path(entry['path'] if isinstance(entry, dict) else entry).resolve(strict=True))
        for secret in config.get('secrets', {}).values():
            if secret.get('file'):
                paths.add(Path(secret['file']).resolve(strict=True))
        for service in config['services'].values():
            for mount in service.get('volumes', []):
                if mount.get('type') == 'bind' and Path(mount['source']).is_file():
                    paths.add(Path(mount['source']).resolve(strict=True))
        for index, path in enumerate(sorted(paths)):
            archive.add(path, arcname=f'{index}-{path.name}', recursive=False)
    # Root-created snapshot becomes private to the invoking local operator.
    run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--entrypoint', 'python',
        '-v', str(backup) + ':/backup', app['Image'], '-c',
        "import os; os.chown('/backup/application.sqlite3'," + str(os.getuid()) + ',' + str(os.getgid()) + ")"])
    names = ('application.sqlite3', 'miniflux.dump', 'configuration.tar')
    receipt = {'instance_uuid': instance, 'account_id': account, 'project': args.project,
        'created_at': datetime.now(timezone.utc).isoformat(), 'sha256': {name: sha(backup / name) for name in names}}
    (backup / 'backup.json').write_text(json.dumps(receipt, sort_keys=True))
    checkpoint('backed_up')
    # Preserve users/tokens/schema/sequence identities; only dedicated engine content is cleared.
    other = run(['docker', 'exec', pg['Id'], 'psql', '-XAt', '-U', 'miniflux', '-d', 'miniflux',
        '-c', f'SELECT count(*) FROM feeds WHERE user_id <> {account}']).decode().strip()
    require(other == '0', 'Other Miniflux accounts have feeds; refusing a shared engine reset.')
    # Fail before clearing the engine if the app cannot write its own SQLite DB.
    writer_probe = ("import sqlite3; c=sqlite3.connect('file:" + db_path
        + "?mode=rw',uri=True,timeout=5); c.execute('BEGIN IMMEDIATE'); c.rollback(); c.close()")
    app_command(['-c', writer_probe])
    checkpoint('engine_reset_started')
    run(['docker', 'exec', pg['Id'], 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'miniflux', '-d', 'miniflux',
        '-c', f'BEGIN; DELETE FROM feeds WHERE user_id = {account}; COMMIT;'])
    checkpoint('engine_reset_complete')
    app_command(['/app/backend/manage.py', 'migrate', '--noinput'])
    result = json.loads(app_command(command + ['--apply', '--reset-content', '--backup-dir', '/backup'], mount=True))
    # Derived content is rebuildable; retain it in this paired local backup first.
    cleanup = """import os, pathlib, tarfile, shutil
root=pathlib.Path('/var/lib/newshub')
with tarfile.open('/backup/derived.tar','w') as archive:
 for name in ('chroma','tts'):
  p=root/name
  if p.exists():
   archive.add(p,arcname=name); shutil.rmtree(p); p.mkdir(); os.chown(p,10001,10001)
for name in ('db.sqlite3','db.sqlite3-wal','db.sqlite3-shm'):
 p=pathlib.Path('DBPATH').parent/name
 if p.exists(): os.chown(p,10001,10001)
""".replace('DBPATH', db_path)
    run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0', '--entrypoint', 'python',
        '--volumes-from', app['Id'], '-v', str(backup) + ':/backup', app['Image'], '-c', cleanup])
    checkpoint('content_initialized')
    # Resume only the supported local roles. Retired collectors stay stopped.
    run(compose + ['up', '-d', '--no-deps', 'miniflux', 'rss-sync'], timeout=240)
    checkpoint('collecting_defaults')
    deadline = time.monotonic() + args.settle_timeout
    while True:
        status = json.loads(app_command(command))['runtime']
        operation_at, sync_at = status['last_operation_at'], status['last_sync_at']
        if status['pending_operations'] == 0 and sync_at and (not operation_at or sync_at >= operation_at):
            break
        require(time.monotonic() < deadline, 'Initial collection is not settled; application remains stopped. Do not repeat the reset.')
        time.sleep(2)
    checkpoint('initial_collection_settled')
    # Channel workers can dispatch user-configured models. Leave them stopped
    # during this no-provider maintenance; their configuration is preserved.
    run(compose + ['up', '-d', '--no-deps', 'app'], timeout=240)
    checkpoint('resumed')
    result['runtime'] = status
    result['counts_after'] = json.loads(app_command(command))['counts']
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except InitializeError as error:
        raise SystemExit(str(error)) from None
