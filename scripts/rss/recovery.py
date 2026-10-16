#!/usr/bin/env python3
"""Thin, explicit RSS paired recovery on existing release/SQLite primitives.

All mutations default to dry-run. No automatic service restart after backups or
restores; an interrupted pair stays stopped and requires diagnosis, not guessing.
The manifest is a target inventory, not an approval-file protocol.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.deploy import release_manifest, sqlite_snapshot

ROLES = {'app', 'crawler', 'indexer', 'channel-worker', 'full-content', 'rss-sync'}
HEX = re.compile(r'[0-9a-f]{64}')
NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}')
WRITER_FIELDS = {'roles', 'host_processes', 'schedulers', 'host_inventory_complete'}


class RecoveryError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RecoveryError(message)


def fields(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected), label + ' fields are incomplete or unknown')


def read_json(path):
    path = regular(path)
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        raise RecoveryError('invalid JSON artifact') from None


def regular(path):
    path = Path(path)
    require(path.is_absolute() and not path.is_symlink() and path.is_file(), 'absolute regular file required')
    require(path.resolve() == path, 'symlink path components are forbidden')
    return path


def sqlite_target(path):
    path = Path(path)
    require(path.is_absolute() and not path.is_symlink() and path.parent.is_dir()
            and path.parent.resolve() == path.parent, 'explicit real SQLite target parent required')
    if path.exists():
        regular(path)
    return path


def digest(path):
    h = hashlib.sha256()
    with regular(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def value_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def release(value):
    try:
        result = release_manifest.validate_manifest(value)
    except release_manifest.ManifestError:
        raise RecoveryError('invalid release manifest') from None
    require(result['schema_version'] == 3, 'RSS recovery requires strict release schema 3')
    return result


def validate_manifest(value, environment, project):
    fields(value, {'schema_version', 'environment', 'project', 'release', 'sqlite', 'postgres',
                   'engine', 'writers', 'other_containers', 'secret_refs', 'rollback'}, 'target manifest')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'unsupported RSS manifest schema')
    require(environment in {'isolated', 'production'} and value['environment'] == environment,
            'environment does not match explicit target')
    require(isinstance(project, str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project)
            and value['project'] == project, 'project does not match explicit target')
    if environment == 'isolated':
        require(project.startswith('newshub-rss-'), 'isolated project requires explicit newshub-rss- namespace')
    release(value['release'])
    fields(value['sqlite'], {'path'}, 'SQLite target')
    sqlite_target(value['sqlite']['path'])
    fields(value['postgres'], {'container_id', 'image', 'database', 'user', 'volume'}, 'PostgreSQL target')
    fields(value['engine'], {'container_id', 'image', 'instance_uuid', 'account_id', 'username', 'schema_version'}, 'engine target')
    for part in (value['postgres'], value['engine']):
        require(isinstance(part['container_id'], str) and HEX.fullmatch(part['container_id']), 'full container ID required')
        require(isinstance(part['image'], str) and re.fullmatch(r'.+@sha256:[0-9a-f]{64}', part['image']),
                'engine and PostgreSQL require immutable image digests')
    for key in ('database', 'user', 'volume'):
        require(isinstance(value['postgres'][key], str) and NAME.fullmatch(value['postgres'][key]), 'invalid PostgreSQL target')
    engine = value['engine']
    try:
        require(str(uuid.UUID(engine['instance_uuid'])) == engine['instance_uuid'], 'noncanonical engine UUID')
    except (ValueError, TypeError, AttributeError):
        raise RecoveryError('invalid engine UUID') from None
    require(type(engine['account_id']) is int and engine['account_id'] > 0, 'invalid service account')
    require(isinstance(engine['username'], str) and NAME.fullmatch(engine['username']), 'invalid service username')
    require(type(engine['schema_version']) is int and engine['schema_version'] > 0, 'unknown engine schema')
    writers = value['writers']
    fields(writers, WRITER_FIELDS, 'writer inventory')
    require(writers['host_inventory_complete'] is True, 'host writer/scheduler inventory must be complete')
    fields(writers['roles'], ROLES, 'writer roles')
    ids = [value['postgres']['container_id'], engine['container_id']]
    for role, containers in writers['roles'].items():
        require(isinstance(containers, list) and all(isinstance(item, str) and HEX.fullmatch(item) for item in containers),
                'writer allowlist requires full container IDs')
        ids.extend(containers)
    require(isinstance(value['other_containers'], dict), 'other container inventory must be explicit')
    for service, container_id in value['other_containers'].items():
        require(isinstance(service, str) and NAME.fullmatch(service) and service not in ROLES | {'miniflux', 'rss-db'},
                'invalid non-writer service')
        require(isinstance(container_id, str) and HEX.fullmatch(container_id), 'full non-writer container ID required')
        ids.append(container_id)
    require(len(ids) == len(set(ids)), 'container allowlist contains duplicates')
    require(isinstance(writers['host_processes'], list) and isinstance(writers['schedulers'], list), 'invalid host inventory')
    for process in writers['host_processes']:
        fields(process, {'pid', 'start_ticks', 'cmdline_sha256', 'role'}, 'host process')
        require(type(process['pid']) is int and process['pid'] > 1 and process['pid'] != os.getpid(), 'unsafe host PID')
        require(type(process['start_ticks']) is int and process['start_ticks'] > 0, 'host PID start identity required')
        require(isinstance(process['cmdline_sha256'], str) and HEX.fullmatch(process['cmdline_sha256']), 'host command digest required')
        require(process['role'] in ROLES, 'unknown host writer role')
    for scheduler in writers['schedulers']:
        fields(scheduler, {'unit', 'scope'}, 'scheduler')
        require(scheduler['scope'] in {'user', 'system'} and isinstance(scheduler['unit'], str)
                and re.fullmatch(r'[A-Za-z0-9_.@-]+\.(timer|service)', scheduler['unit']), 'explicit systemd scheduler required')
    require(isinstance(value['secret_refs'], dict), 'secret references must be explicit')
    for name, path in value['secret_refs'].items():
        require(isinstance(name, str) and NAME.fullmatch(name), 'invalid secret reference name')
        require(regular(path).stat().st_mode & 0o077 == 0, 'secret reference must have no group/other access')
    if value['rollback'] is not None:
        fields(value['rollback'], {'target_release', 'compatibility_evidence', 'evidence_sha256',
            'env_file', 'static_root', 'db_volume', 'worker_services'}, 'application rollback')
        rollback = value['rollback']
        for name in ('target_release', 'compatibility_evidence', 'env_file'):
            regular(rollback[name])
        require(isinstance(rollback['worker_services'], list) and len(set(rollback['worker_services'])) == len(rollback['worker_services'])
                and set(rollback['worker_services']) <= {'indexer', 'channel-worker'}, 'RSS rollback cannot start legacy collectors')
        require(rollback['db_volume'] == project + '_db-data', 'rollback DB volume differs from explicit target')
        require(Path(rollback['static_root']).is_absolute(), 'rollback static root must be absolute')
    return value


def command(args, *, input=None, output=None, stdin=None, timeout=180):
    try:
        result = subprocess.run(args, input=input, stdin=stdin, stdout=output if output else subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=True)
        return result.stdout if output is None else b''
    except (OSError, subprocess.SubprocessError):
        # SQL errors and commands may contain protected data. Never echo stderr.
        raise RecoveryError('subprocess failed; targets remain stopped, inspect protected diagnostics') from None


class Docker:
    def __init__(self):
        endpoint = os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
        endpoint = endpoint or command(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).decode().strip()
        require(endpoint.startswith('unix://'), 'local Unix Docker endpoint required')

    def inspect(self, container):
        return json.loads(command(['docker', 'inspect', container]))[0]

    def sql(self, manifest, sql):
        pg = manifest['postgres']
        return command(['docker', 'exec', '-i', pg['container_id'], 'psql', '-X', '-A', '-t',
            '--set=ON_ERROR_STOP=1', '--username', pg['user'], '--dbname', pg['database']], input=sql.encode()).decode().strip()

    def dump(self, manifest, path):
        pg = manifest['postgres']
        with path.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            command(['docker', 'exec', pg['container_id'], 'pg_dump', '--format=custom', '--no-owner', '--no-acl',
                '--username', pg['user'], '--dbname', pg['database']], output=stream)
            stream.flush(); os.fsync(stream.fileno())

    def restore(self, manifest, path):
        pg = manifest['postgres']
        with regular(path).open('rb') as stream:
            try:
                subprocess.run(['docker', 'exec', '-i', pg['container_id'], 'pg_restore', '--clean', '--if-exists',
                    '--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', '--username', pg['user'],
                    '--dbname', pg['database']], stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=180, check=True)
            except (OSError, subprocess.SubprocessError):
                raise RecoveryError('PostgreSQL restore failed; pair remains stopped; preserve prior backup') from None


def container_inventory(manifest):
    result = {manifest['postgres']['container_id']: ('rss-db', manifest['postgres']['image']),
              manifest['engine']['container_id']: ('miniflux', manifest['engine']['image'])}
    for role, containers in manifest['writers']['roles'].items():
        for container in containers:
            result[container] = (role, None)
    for service, container in manifest['other_containers'].items():
        result[container] = (service, None)
    return result


def verify_targets(manifest, docker):
    inventory = container_inventory(manifest)
    found = set(command(['docker', 'ps', '-aq', '--no-trunc', '--filter',
                         'label=com.docker.compose.project=' + manifest['project']]).decode().split())
    require(found == set(inventory), 'project containers differ from explicit allowlist')
    sqlite_parent = str(Path(manifest['sqlite']['path']).parent)
    for container, (service, image) in inventory.items():
        item = docker.inspect(container)
        labels = item['Config'].get('Labels') or {}
        require(item['Id'] == container and labels.get('com.docker.compose.project') == manifest['project']
            and labels.get('com.docker.compose.service') == service, 'container target/role mismatch')
        if image:
            require(item['Config']['Image'] == image, 'engine/PostgreSQL image mismatch')
        if service == 'miniflux':
            env = dict(entry.split('=', 1) for entry in item['Config'].get('Env', []) if '=' in entry)
            database_url = env.get('DATABASE_URL')
            if not database_url and env.get('DATABASE_URL_FILE'):
                mounts = [m for m in item['Mounts'] if m['Destination'] == env['DATABASE_URL_FILE']]
                require(len(mounts) == 1 and mounts[0].get('Source') in manifest['secret_refs'].values(), 'engine database secret is not explicitly inventoried')
                database_url = regular(mounts[0]['Source']).read_text().strip()
            parsed = urlsplit(database_url or '')
            require(parsed.scheme in {'postgres', 'postgresql'} and parsed.hostname == 'rss-db'
                    and parsed.port in {None, 5432} and parsed.path == '/' + manifest['postgres']['database']
                    and parsed.username == manifest['postgres']['user'], 'engine points to a different PostgreSQL target')
        if service == 'rss-db':
            require(item['State']['Running'], 'PostgreSQL target must be running for dump/restore')
            mounts = [m for m in item['Mounts'] if m['Destination'] == '/var/lib/postgresql/data']
            require(len(mounts) == 1 and mounts[0]['Type'] == 'volume'
                    and mounts[0]['Name'] == manifest['postgres']['volume'], 'PostgreSQL volume mismatch')
            require(not item['HostConfig'].get('PortBindings'), 'PostgreSQL target must have no published ports')
        elif service in ROLES:
            # SQLite may be an explicit bind or the existing deploy db-data volume.
            mounts = [m for m in item['Mounts'] if m['Destination'] == '/var/lib/newshub/db']
            require(len(mounts) == 1 and mounts[0]['Source'] == sqlite_parent and ((mounts[0]['Type'] == 'bind')
                or (mounts[0]['Type'] == 'volume' and mounts[0]['Name'] == manifest['project'] + '_db-data')),
                'writer SQLite mount mismatch')
            if service == 'app' and manifest['environment'] == 'production':
                require(item['Config']['Image'] == manifest['release']['image']
                        and labels.get(release_manifest.REVISION_LABEL) == manifest['release']['release_sha'],
                        'application image/revision differs from release manifest')
        elif service not in {'miniflux'}:
            require(not any(m.get('RW') and (m.get('Source') == sqlite_parent
                or m.get('Name') in {manifest['postgres']['volume'], manifest['project'] + '_db-data'})
                for m in item['Mounts']), 'non-writer service mounts a writable database')
    pg_volume = json.loads(command(['docker', 'volume', 'inspect', manifest['postgres']['volume']]))[0]
    require((pg_volume.get('Labels') or {}).get('com.docker.compose.project') == manifest['project'], 'PostgreSQL volume project mismatch')
    mounted = set(command(['docker', 'ps', '-q', '--no-trunc', '--filter',
                          'volume=' + manifest['postgres']['volume']]).decode().split())
    require(mounted == {manifest['postgres']['container_id']}, 'unexpected running PostgreSQL volume user')


def process_identity(process):
    root = Path('/proc') / str(process['pid'])
    try:
        stat = (root / 'stat').read_text()
        # comm can contain spaces/parentheses; field22 follows the final ')'.
        tail = stat.rsplit(')', 1)[1].split()
        if tail[0] == 'Z':
            return False
        require(int(tail[19]) == process['start_ticks'] and
                hashlib.sha256((root / 'cmdline').read_bytes()).hexdigest() == process['cmdline_sha256'],
                'host PID identity changed; refusing to signal')
        return True
    except FileNotFoundError:
        return False


def systemctl(scheduler, *args):
    scope = ['--user'] if scheduler['scope'] == 'user' else []
    return command(['systemctl', *scope, *args, scheduler['unit']]).decode().strip()


def quiesce(manifest, docker, *, stop=False):
    # Verify the complete target set before any stop; unknown resources are never
    # stopped to make validation pass. Schedulers stop before their spawned PIDs.
    verify_targets(manifest, docker)
    for scheduler in manifest['writers']['schedulers']:
        if stop:
            systemctl(scheduler, 'stop')
        require(systemctl(scheduler, 'show', '--property=ActiveState', '--value') in {'inactive', 'failed'}, 'host scheduler is still active')
    for process in manifest['writers']['host_processes']:
        if stop and process_identity(process):
            os.kill(process['pid'], signal.SIGTERM)
            deadline = time.monotonic() + 45
            while process_identity(process) and time.monotonic() < deadline:
                time.sleep(.1)
        require(not process_identity(process), 'host writer is still active')
    stopped = [manifest['engine']['container_id']]
    stopped += [item for items in manifest['writers']['roles'].values() for item in items]
    if stop:
        command(['docker', 'stop', '--time', '45', *stopped])
    require(all(not docker.inspect(item)['State']['Running'] for item in stopped), 'writer/Miniflux is still active; use --stop-writers explicitly')
    require(docker.sql(manifest, "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend';") == '0',
            'unlisted PostgreSQL client is still active')
    sqlite_path = str(Path(manifest['sqlite']['path']).parent)
    mounted = set(command(['docker', 'ps', '-q', '--no-trunc', '--filter', 'volume=' + sqlite_path]).decode().split())
    mounted |= set(command(['docker', 'ps', '-q', '--no-trunc', '--filter', 'volume=' + manifest['project'] + '_db-data']).decode().split())
    require(not mounted, 'SQLite has a running container user')


def pg_state(manifest, docker):
    engine = manifest['engine']
    require(docker.sql(manifest, 'SELECT max(version)::text FROM schema_version;') == str(engine['schema_version']), 'unknown engine database schema')
    user = docker.sql(manifest, f"SELECT json_build_array(id,username,is_admin)::text FROM users WHERE id={engine['account_id']};")
    require(json.loads(user or 'null') == [engine['account_id'], engine['username'], False], 'dedicated non-admin account identity mismatch')
    tables = docker.sql(manifest, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;").splitlines()
    h = hashlib.sha256()
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        rows = docker.sql(manifest, f'SELECT row_to_json(t)::text FROM public.{quoted} t ORDER BY 1;')
        h.update(table.encode() + b'\0' + rows.encode() + b'\n')
    sequences = docker.sql(manifest, "SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename;").splitlines()
    for sequence in sequences:
        quoted = '"' + sequence.replace('"', '""') + '"'
        state = docker.sql(manifest, f'SELECT last_value::text,is_called::text FROM public.{quoted};')
        h.update(sequence.encode() + b'\0' + state.encode() + b'\n')
    return h.hexdigest()


def sqlite_state(path, manifest):
    with contextlib.closing(sqlite_snapshot._open_readonly(Path(path))) as db:
        sqlite_snapshot._quick_check(db)
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign key violation')
        require(sqlite_snapshot._migration_rows(db) == manifest['release']['migrations'], 'unknown SQLite migration set')
        engine = manifest['engine']
        bindings = db.execute('SELECT id,engine_instance_uuid,account_id,engine_feed_id,canonical_feed_url FROM api_feedbinding ORDER BY id').fetchall()
        for row in bindings:
            require(str(uuid.UUID(row[1])) == engine['instance_uuid'] and row[2] == engine['account_id'], 'SQLite binding belongs to a different engine/account')
        cursors = db.execute('SELECT engine_instance_uuid,account_id FROM api_feedsyncstate').fetchall()
        require(all(str(uuid.UUID(row[0])) == engine['instance_uuid'] and row[1] == engine['account_id'] for row in cursors), 'SQLite sync state belongs to a different engine/account')
        mappings = db.execute('SELECT binding_id,engine_entry_id,news_id,source_url FROM api_engineentrymap ORDER BY binding_id,engine_entry_id').fetchall()
    return {'bindings': bindings, 'mappings': mappings, 'mapping_sha256': value_digest([bindings, mappings]),
            'logical_sha256': sqlite_snapshot._logical_database_sha256(Path(path), deadline=time.monotonic() + 120)}


def verify_pair_state(path, manifest, docker):
    state = sqlite_state(path, manifest)
    engine = manifest['engine']
    feeds = json.loads(docker.sql(manifest, "SELECT coalesce(json_agg(json_build_array(id,user_id,feed_url)), '[]'::json)::text FROM feeds;"))
    entries = json.loads(docker.sql(manifest, "SELECT coalesce(json_agg(json_build_array(id,feed_id,user_id,url)), '[]'::json)::text FROM entries;"))
    feed_map, entry_map = {r[0]: r for r in feeds}, {r[0]: r for r in entries}
    bindings = {r[0]: r for r in state['bindings']}
    for _, _, _, feed_id, url in state['bindings']:
        if feed_id is not None:
            require(feed_id in feed_map and feed_map[feed_id][1:] == [engine['account_id'], url], 'Feed mapping does not match PostgreSQL identity/URL')
    expired = 0
    for binding_id, entry_id, _, url in state['mappings']:
        require(binding_id in bindings, 'entry binding is missing')
        row = entry_map.get(entry_id)
        if row is None:
            expired += 1  # Miniflux retention may remove entries, never local News.
            continue
        require(row[1:] == [bindings[binding_id][3], engine['account_id'], url], 'entry mapping does not match PostgreSQL identity/URL')
    state['retained_entries_missing'] = expired
    return state


def artifact_paths(directory):
    return {name: Path(directory) / name for name in ('sqlite.sqlite3', 'sqlite.sqlite3.manifest.json', 'miniflux.dump')}


def load_pair(directory, manifest):
    directory = Path(directory)
    require(directory.is_absolute() and directory.resolve() == directory and directory.is_dir(), 'pair directory must be explicit and real')
    pair = read_json(directory / 'pair.json')
    fields(pair, {'schema_version', 'pair_id', 'created_at', 'source', 'release', 'engine', 'files',
                  'sqlite_logical_sha256', 'pg_logical_sha256', 'mapping_sha256', 'secret_sha256', 'restore_points'}, 'paired backup')
    require(type(pair['schema_version']) is int and pair['schema_version'] == 1, 'unsupported paired backup schema')
    release(pair['release'])
    require(pair['engine'] == {k: manifest['engine'][k] for k in ('instance_uuid', 'account_id', 'username', 'image', 'schema_version')}
            and pair['source']['pg_image'] == manifest['postgres']['image'], 'paired backup engine/account/schema/image mismatch')
    require(pair['release']['migrations'] == manifest['release']['migrations'], 'paired backup schema differs from target release')
    paths = artifact_paths(directory)
    require(set(pair['files']) == set(paths), 'paired backup file set mismatch')
    require(all(digest(path) == pair['files'][name] for name, path in paths.items()), 'paired backup artifact hash mismatch')
    artifact, embedded_release = sqlite_snapshot._validate_artifact(paths['sqlite.sqlite3'])
    require(embedded_release == pair['release'], 'SQLite sidecar is paired with a different release')
    state = sqlite_state(paths['sqlite.sqlite3'], {**manifest, 'release': pair['release']})
    require(state['logical_sha256'] == pair['sqlite_logical_sha256'] and state['mapping_sha256'] == pair['mapping_sha256'], 'paired backup mapping/content mismatch')
    require(set(pair['secret_sha256']) == set(manifest['secret_refs']), 'protected secret reference set differs from backup')
    for name, path in manifest['secret_refs'].items():
        require(digest(directory / 'secrets' / name) == pair['secret_sha256'][name], 'protected secret backup hash mismatch')
        require(digest(path) == pair['secret_sha256'][name], 'protected secret differs; restore its protected backup separately before continuing')
    return pair


def backup(manifest, docker, output, *, execute=False, stop_writers=False):
    output = Path(output)
    require(output.is_absolute() and output.parent.resolve() == output.parent and output.parent.is_dir()
            and not output.exists() and not output.is_symlink(), 'new absolute backup directory required')
    result = {'action': 'backup', 'dry_run': not execute, 'project': manifest['project'], 'output': str(output),
              'writers': sorted(ROLES), 'requires_stopped_miniflux': True, 'databases_restored': False}
    if not execute:
        return result
    quiesce(manifest, docker, stop=stop_writers)
    before = pg_state(manifest, docker)
    state = verify_pair_state(manifest['sqlite']['path'], manifest, docker)
    work = Path(tempfile.mkdtemp(prefix='.rss-pair-', dir=output.parent))
    os.chmod(work, 0o700)
    try:
        release_path = work / 'release.json'
        release_path.write_text(json.dumps(manifest['release']))
        os.chmod(release_path, 0o600)
        started = datetime.now(timezone.utc).isoformat()
        sqlite_snapshot.backup_database(Path(manifest['sqlite']['path']), work / 'sqlite.sqlite3', release_path)
        sqlite_time = datetime.now(timezone.utc).isoformat()
        docker.dump(manifest, work / 'miniflux.dump')
        pg_time = datetime.now(timezone.utc).isoformat()
        quiesce(manifest, docker)
        require(pg_state(manifest, docker) == before, 'PostgreSQL changed during paired backup')
        after = verify_pair_state(manifest['sqlite']['path'], manifest, docker)
        require(state == after, 'SQLite changed during paired backup')
        require(sqlite_state(work / 'sqlite.sqlite3', manifest)['logical_sha256'] == state['logical_sha256'], 'SQLite snapshot content differs')
        pair = {'schema_version': 1, 'pair_id': str(uuid.uuid4()), 'created_at': started,
            'source': {'project': manifest['project'], 'sqlite_path': manifest['sqlite']['path'],
                       'pg_volume': manifest['postgres']['volume'], 'pg_image': manifest['postgres']['image']},
            'release': manifest['release'],
            'engine': {k: manifest['engine'][k] for k in ('instance_uuid', 'account_id', 'username', 'image', 'schema_version')},
            'files': {name: digest(path) for name, path in artifact_paths(work).items()},
            'sqlite_logical_sha256': state['logical_sha256'], 'pg_logical_sha256': before,
            'mapping_sha256': state['mapping_sha256'], 'secret_sha256': {name: digest(path) for name, path in manifest['secret_refs'].items()},
            'restore_points': {'sqlite': sqlite_time, 'postgres': pg_time}}
        secret_directory = work / 'secrets'
        secret_directory.mkdir(mode=0o700)
        for name, source in manifest['secret_refs'].items():
            with regular(source).open('rb') as reader, (secret_directory / name).open('xb') as writer:
                os.fchmod(writer.fileno(), 0o600)
                shutil.copyfileobj(reader, writer)
                writer.flush(); os.fsync(writer.fileno())
        with (work / 'pair.json').open('w') as writer:
            os.fchmod(writer.fileno(), 0o600)
            writer.write(json.dumps(pair, indent=2, sort_keys=True) + '\n')
            writer.flush(); os.fsync(writer.fileno())
        sqlite_snapshot._fsync_directory(secret_directory)
        release_path.unlink()
        load_pair(work, manifest)
        # Reserve without replacement; pair.json publishes last. A partial output
        # has no valid pair and is never usable as a successful recovery point.
        output.mkdir(mode=0o700)
        for name in (*artifact_paths(work), 'secrets', 'pair.json'):
            os.rename(work / name, output / name)
        sqlite_snapshot._fsync_directory(output)
        sqlite_snapshot._fsync_directory(output.parent)
    finally:
        if work.exists():
            shutil.rmtree(work)
    return {**result, 'pair_id': pair['pair_id'], 'retained_entries_missing': state['retained_entries_missing']}


def verify_prior(directory, manifest, docker):
    prior = load_pair(directory, manifest)
    state = verify_pair_state(manifest['sqlite']['path'], manifest, docker)
    require(prior['sqlite_logical_sha256'] == state['logical_sha256']
            and prior['mapping_sha256'] == state['mapping_sha256']
            and prior['pg_logical_sha256'] == pg_state(manifest, docker), 'prior backup does not match both current target databases')
    return prior


def restore(manifest, docker, source, *, prior_backup, replace=False, execute=False, stop_writers=False, fresh=False):
    pair = load_pair(source, manifest)
    if fresh:
        require(not replace and prior_backup is None and not sqlite_target(manifest['sqlite']['path']).exists(), 'fresh restore requires absent SQLite and no overwrite/prior options')
        require(not any(Path(manifest['sqlite']['path'] + suffix).exists() for suffix in ('-wal', '-shm')), 'fresh target has SQLite sidecars')
    else:
        require(replace and prior_backup is not None, 'paired overwrite requires --replace and a matching prior backup')
        load_pair(prior_backup, manifest)
    result = {'action': 'restore', 'dry_run': not execute, 'pair_id': pair['pair_id'], 'project': manifest['project'],
              'rpo': pair['restore_points'], 'writers_remain_stopped': True}
    if not execute:
        return result
    quiesce(manifest, docker, stop=stop_writers)
    if fresh:
        require(docker.sql(manifest, "SELECT count(*) FROM pg_tables WHERE schemaname='public';") == '0', 'fresh PostgreSQL target is not empty')
    else:
        verify_prior(prior_backup, manifest, docker)
    # Validate archive structure before touching either database. Archive SQL is
    # operator-trusted; hashes prove pairing/integrity, not authenticity.
    dump = regular(Path(source) / 'miniflux.dump')
    with dump.open('rb') as archive:
        command(['docker', 'exec', '-i', manifest['postgres']['container_id'], 'pg_restore', '--list'],
                stdin=archive, output=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix='.rss-release-', dir=Path(manifest['sqlite']['path']).parent) as directory:
        release_path = Path(directory) / 'release.json'
        release_path.write_text(json.dumps(pair['release']))
        os.chmod(release_path, 0o600)
        # PG's transaction is atomic; there is no distributed transaction across
        # PG and SQLite. Any later failure leaves all writers stopped with prior.
        docker.restore(manifest, dump)
        require(pg_state(manifest, docker) == pair['pg_logical_sha256'], 'restored PostgreSQL content mismatch')
        sqlite_snapshot.restore_database(Path(source) / 'sqlite.sqlite3', Path(manifest['sqlite']['path']),
            release_path, replace=not fresh, writers_stopped=True,
            prior_backup=None if fresh else Path(prior_backup) / 'sqlite.sqlite3')
    state = verify_pair_state(manifest['sqlite']['path'], manifest, docker)
    require(state['logical_sha256'] == pair['sqlite_logical_sha256'] and state['mapping_sha256'] == pair['mapping_sha256'], 'restored pair content/mapping mismatch')
    quiesce(manifest, docker)
    return {**result, 'foreign_keys': 'ok', 'mapping_sha256': state['mapping_sha256'],
            'service_account': 'verified_non_admin', 'retained_entries_missing': state['retained_entries_missing']}


def rollback_command(manifest, current_release_path):
    settings = manifest['rollback']
    require(settings is not None, 'no compatible application rollback target configured')
    target = release(read_json(settings['target_release']))
    require(target['migrations'] == manifest['release']['migrations'], 'rollback requires exact tested schema')
    require(digest(settings['compatibility_evidence']) == settings['evidence_sha256'], 'compatibility evidence hash mismatch')
    proof = read_json(settings['compatibility_evidence'])
    fields(proof, {'schema_version', 'release', 'rss_compatible', 'production_sealed'}, 'compatibility evidence')
    require(type(proof['schema_version']) is int and proof['schema_version'] == 1 and proof['rss_compatible'] is True
            and proof['release'] == target, 'rollback target lacks matching RSS compatibility evidence')
    require(manifest['environment'] != 'production' or proof['production_sealed'] is True, 'production rollback target is not sealed')
    allowed = {'indexer'} | ({'channel-worker'} if target['capabilities']['channel_worker'] else set())
    require(set(settings['worker_services']) <= allowed, 'rollback worker capability mismatch')
    return ['bash', str(ROOT / 'scripts/deploy/rollback.sh'), '--env-file', settings['env_file'], '--project', manifest['project'],
            '--sha', target['release_sha'], '--image', target['image'], '--root', settings['static_root'],
            '--manifest', settings['target_release'], '--current-manifest', str(current_release_path),
            '--db-volume', settings['db_volume'], '--worker-services', ','.join(settings['worker_services'])]


def rollback(manifest, docker, *, prior_backup, execute=False, stop_writers=False):
    # Merely build/validate the existing release command for a dry run. No DB
    # restore function is reachable from the normal application rollback path.
    result = {'action': 'rollback', 'dry_run': not execute, 'project': manifest['project'],
              'databases_restored': False, 'legacy_collectors_started': False}
    arguments = rollback_command(manifest, Path('/tmp/current-rss-release.json'))
    if not execute:
        return {**result, 'worker_services': manifest['rollback']['worker_services']}
    require(prior_backup is not None, 'application rollback requires a current paired safety backup')
    quiesce(manifest, docker, stop=stop_writers)
    verify_prior(prior_backup, manifest, docker)
    with tempfile.TemporaryDirectory(prefix='rss-rollback-release-') as directory:
        current = Path(directory) / 'current.json'
        current.write_text(json.dumps(manifest['release']))
        os.chmod(current, 0o600)
        arguments = rollback_command(manifest, current)
        # rollback.sh owns its 300s-per-service readiness and fail-closed traps.
        # A shorter subprocess.run timeout would SIGKILL its shell mid-switch,
        # bypass those traps and leave newly started app writers running.
        command(arguments + ['--execute'], timeout=None)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore', 'rollback', 'status', 'install-check', 'diagnose'])
    parser.add_argument('--environment', required=True, choices=['isolated', 'production'])
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--target-project', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stop-writers', action='store_true')
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--prior-backup', type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = validate_manifest(read_json(args.manifest), args.environment, args.target_project)
        if args.action in {'status', 'install-check', 'diagnose'}:
            require(not args.execute and not args.stop_writers, 'read-only operation cannot execute mutations')
            docker = Docker()
            verify_targets(manifest, docker)
            return_value = {'action': args.action, 'target_inventory': 'verified', 'project': args.target_project,
                            'engine_account_schema': 'not_checked_until_quiesced'}
        else:
            docker = Docker() if args.execute else None
            if args.action == 'backup':
                require(args.output is not None and not args.source and not args.replace and not args.fresh and not args.prior_backup, 'backup requires only --output')
                return_value = backup(manifest, docker, args.output, execute=args.execute, stop_writers=args.stop_writers)
            elif args.action == 'restore':
                require(args.source is not None and args.output is None, 'restore requires --source')
                return_value = restore(manifest, docker, args.source, prior_backup=args.prior_backup, replace=args.replace,
                    execute=args.execute, stop_writers=args.stop_writers, fresh=args.fresh)
            else:
                require(args.source is None and args.output is None and not args.replace and not args.fresh, 'rollback does not restore databases')
                return_value = rollback(manifest, docker, prior_backup=args.prior_backup,
                    execute=args.execute, stop_writers=args.stop_writers)
        print(json.dumps(return_value, sort_keys=True))
        return 0
    except (RecoveryError, release_manifest.ManifestError, sqlite_snapshot.SnapshotError, OSError, sqlite3.Error,
            KeyError, TypeError, ValueError) as error:
        message = str(error) if isinstance(error, (RecoveryError, sqlite_snapshot.SnapshotError)) else type(error).__name__
        print('rss-recovery: ' + message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
