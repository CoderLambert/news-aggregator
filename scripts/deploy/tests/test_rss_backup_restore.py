"""T03 safety boundaries; fake Docker tests are not live engine evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

from scripts.rss import recovery as rss

SHA = 'a' * 40
INSTANCE = 'd573a70a-d258-411c-94b0-fdd33864d10d'
MIGRATIONS = [{'app': 'api', 'name': '0058_private_translation_versions'}]


@pytest.fixture
def target(tmp_path):
    path = tmp_path / 'db.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''
CREATE TABLE django_migrations(app TEXT, name TEXT);
CREATE TABLE api_feedbinding(id TEXT PRIMARY KEY,engine_instance_uuid TEXT,account_id INTEGER,engine_feed_id INTEGER,canonical_feed_url TEXT);
CREATE TABLE api_feedsyncstate(engine_instance_uuid TEXT,account_id INTEGER);
CREATE TABLE api_engineentrymap(binding_id TEXT REFERENCES api_feedbinding(id),engine_entry_id INTEGER,news_id INTEGER,source_url TEXT);
CREATE TABLE preserved(id INTEGER PRIMARY KEY,body TEXT);
INSERT INTO preserved VALUES(1,'original body');
''')
        db.execute('INSERT INTO django_migrations VALUES(?,?)', ('api', MIGRATIONS[0]['name']))
        db.execute('INSERT INTO api_feedbinding VALUES(?,?,?,?,?)', ('binding', INSTANCE.replace('-', ''), 2, 1, 'https://example.org/feed'))
        db.execute('INSERT INTO api_engineentrymap VALUES(?,?,?,?)', ('binding', 7, None, 'https://example.org/article'))
    return {'schema_version': 1, 'environment': 'isolated', 'project': 'newshub-rss-t03-test',
        'release': {'schema_version': 3, 'release_sha': SHA, 'image': 'newshub:' + SHA,
            'migrations': MIGRATIONS, 'static_sha': 'b' * 64,
            'capabilities': {'full_content_worker': True, 'channel_worker': True}},
        'sqlite': {'path': str(path)},
        'postgres': {'container_id': '1' * 64, 'image': 'postgres@sha256:' + 'a' * 64,
            'database': 'miniflux', 'user': 'miniflux', 'volume': 'newshub-rss-t03-test_rss-pg-data'},
        'engine': {'container_id': '2' * 64, 'image': 'miniflux/miniflux@sha256:' + 'b' * 64,
            'instance_uuid': INSTANCE, 'account_id': 2, 'username': 'collector', 'schema_version': 144},
        'writers': {'roles': {role: [] for role in rss.ROLES}, 'host_processes': [], 'schedulers': [],
                    'host_inventory_complete': True},
        'other_containers': {}, 'secret_refs': {}, 'rollback': None}


class FakePG:
    def __init__(self):
        self.state = 'original'
        self.restore_calls = 0

    def dump(self, manifest, path):
        path.write_bytes(self.state.encode())
        path.chmod(0o600)

    def restore(self, manifest, path):
        self.restore_calls += 1
        self.state = path.read_text()

    def sql(self, manifest, sql):
        if 'FROM feeds' in sql:
            return '[[1,2,"https://example.org/feed"]]'
        if 'FROM entries' in sql:
            return '[[7,1,2,"https://example.org/article"]]'
        raise AssertionError(sql)


@pytest.fixture
def lab(monkeypatch):
    pg = FakePG()
    monkeypatch.setattr(rss, 'quiesce', Mock())
    monkeypatch.setattr(rss, 'pg_state', lambda manifest, docker: hashlib.sha256(docker.state.encode()).hexdigest())
    monkeypatch.setattr(rss, 'command', Mock(return_value=b''))
    return pg


def test_backup_dry_run_has_no_docker_or_filesystem_mutation(target, tmp_path, monkeypatch):
    monkeypatch.setattr(rss, 'Docker', Mock(side_effect=AssertionError('must not instantiate Docker')))
    output = tmp_path / 'dry-pair'
    result = rss.backup(target, None, output)
    assert result['dry_run'] and not output.exists()
    assert not result['databases_restored']


@pytest.mark.parametrize('version', [1, 2, 4, True])
def test_recovery_requires_exact_release_schema_three(target, version):
    target['release']['schema_version'] = version
    with pytest.raises(rss.RecoveryError):
        rss.validate_manifest(target, 'isolated', target['project'])


def test_unknown_target_schema_environment_and_missing_writer_inventory_refused(target):
    for change in [lambda m: m.update(schema_version=2), lambda m: m['writers']['roles'].pop('channel-worker'),
                   lambda m: m['writers'].update(host_inventory_complete=False)]:
        value = copy.deepcopy(target)
        change(value)
        with pytest.raises(rss.RecoveryError):
            rss.validate_manifest(value, 'isolated', target['project'])
    with pytest.raises(rss.RecoveryError, match='project'):
        rss.validate_manifest(target, 'isolated', 'newshub-rss-wrong-target')
    with pytest.raises(rss.RecoveryError, match='environment'):
        rss.validate_manifest(target, 'production', target['project'])


def test_paired_overwrite_roundtrip_and_repeat_preserve_content(target, lab, tmp_path):
    first = tmp_path / 'first'
    rss.backup(target, lab, first, execute=True)
    with sqlite3.connect(target['sqlite']['path']) as db:
        db.execute("UPDATE preserved SET body='newer body'")
    lab.state = 'newer'
    prior = tmp_path / 'prior'
    rss.backup(target, lab, prior, execute=True)
    result = rss.restore(target, lab, first, prior_backup=prior, replace=True, execute=True)
    assert result['foreign_keys'] == 'ok' and lab.state == 'original'
    with sqlite3.connect(target['sqlite']['path']) as db:
        assert db.execute('SELECT body FROM preserved').fetchone()[0] == 'original body'
    repeated_prior = tmp_path / 'repeated-prior'
    rss.backup(target, lab, repeated_prior, execute=True)
    rss.restore(target, lab, first, prior_backup=repeated_prior, replace=True, execute=True)
    assert lab.restore_calls == 2
    assert (first / 'pair.json').stat().st_mode & 0o777 == 0o600
    assert first.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('field', ['instance_uuid', 'account_id', 'image', 'schema_version'])
def test_pair_cannot_cross_engine_identity_image_or_schema(target, lab, tmp_path, field):
    output = tmp_path / 'pair'
    rss.backup(target, lab, output, execute=True)
    altered = copy.deepcopy(target)
    altered['engine'][field] = 999 if field in {'account_id', 'schema_version'} else 'different'
    with pytest.raises(rss.RecoveryError, match='engine/account/schema/image'):
        rss.load_pair(output, altered)


def test_wrong_dump_and_mismatched_prior_refuse_before_restore(target, lab, tmp_path):
    original = tmp_path / 'original'
    rss.backup(target, lab, original, execute=True)
    lab.state = 'changed'
    with pytest.raises(rss.RecoveryError, match='prior backup'):
        rss.restore(target, lab, original, prior_backup=original, replace=True, execute=True)
    assert lab.restore_calls == 0
    (original / 'miniflux.dump').write_bytes(b'wrong pair')
    with pytest.raises(rss.RecoveryError, match='hash mismatch'):
        rss.restore(target, lab, original, prior_backup=original, replace=True, execute=True)
    assert lab.restore_calls == 0


def test_still_active_writer_refuses_before_any_backup(target, lab, tmp_path, monkeypatch):
    monkeypatch.setattr(rss, 'quiesce', Mock(side_effect=rss.RecoveryError('writer is still active')))
    with pytest.raises(rss.RecoveryError, match='still active'):
        rss.backup(target, lab, tmp_path / 'blocked', execute=True)
    assert not (tmp_path / 'blocked').exists()


def test_sqlite_unknown_schema_wrong_instance_fk_and_entry_identity_refused(target, lab):
    with sqlite3.connect(target['sqlite']['path']) as db:
        db.execute("UPDATE api_feedbinding SET account_id=42")
    with pytest.raises(rss.RecoveryError, match='different engine/account'):
        rss.sqlite_state(target['sqlite']['path'], target)
    with sqlite3.connect(target['sqlite']['path']) as db:
        db.execute('UPDATE api_feedbinding SET account_id=2')
        db.execute("UPDATE api_engineentrymap SET source_url='https://example.org/wrong'")
    with pytest.raises(rss.RecoveryError, match='entry mapping'):
        rss.verify_pair_state(target['sqlite']['path'], target, lab)
    with sqlite3.connect(target['sqlite']['path']) as db:
        db.execute("UPDATE api_engineentrymap SET binding_id='missing'")
    with pytest.raises(rss.RecoveryError, match='foreign key'):
        rss.sqlite_state(target['sqlite']['path'], target)


def test_unknown_sqlite_migration_set_is_not_additive_compatibility(target):
    with sqlite3.connect(target['sqlite']['path']) as db:
        db.execute("INSERT INTO django_migrations VALUES('api','9999_unknown')")
    with pytest.raises(rss.RecoveryError, match='migration set'):
        rss.sqlite_state(target['sqlite']['path'], target)


def test_changed_or_reused_host_pid_is_never_signalled(target):
    process = {'pid': os.getpid(), 'start_ticks': 1, 'cmdline_sha256': '0' * 64, 'role': 'app'}
    with pytest.raises(rss.RecoveryError, match='identity changed'):
        rss.process_identity(process)


def test_application_rollback_delegates_without_restore_or_legacy_collectors(target, lab, tmp_path, monkeypatch):
    target_release = tmp_path / 'target.json'
    target_release.write_text(json.dumps({**target['release'], 'release_sha': 'c' * 40, 'image': 'newshub:' + 'c' * 40}))
    evidence = tmp_path / 'compatibility.json'
    evidence.write_text(json.dumps({'schema_version': 1, 'release': json.loads(target_release.read_text()),
                                   'rss_compatible': True, 'production_sealed': False}))
    env_file = tmp_path / 'target.env'
    env_file.write_text('synthetic only')
    target['rollback'] = {'target_release': str(target_release), 'compatibility_evidence': str(evidence),
        'evidence_sha256': rss.digest(evidence), 'env_file': str(env_file), 'static_root': str(tmp_path / 'static'),
        'db_volume': target['project'] + '_db-data', 'worker_services': ['indexer', 'channel-worker']}
    prior = tmp_path / 'prior'
    rss.backup(target, lab, prior, execute=True)
    monkeypatch.setattr(rss, 'restore', Mock(side_effect=AssertionError('normal rollback must not restore')))
    result = rss.rollback(target, lab, prior_backup=prior, execute=True)
    assert not result['databases_restored'] and lab.restore_calls == 0
    call = rss.command.call_args.args[0]
    assert rss.command.call_args.kwargs['timeout'] is None  # delegate readiness/cleanup, never kill its shell at180s
    assert call[-3:] == ['--worker-services', 'indexer,channel-worker', '--execute']
    assert 'restore' not in call and 'crawler' not in call and 'rss-sync' not in call
    target['environment'] = 'production'
    with pytest.raises(rss.RecoveryError, match='not sealed'):
        rss.rollback_command(target, tmp_path / 'current.json')


def test_restore_dry_run_still_validates_pair_and_explicit_replace(target, lab, tmp_path):
    output = tmp_path / 'pair'
    rss.backup(target, lab, output, execute=True)
    with pytest.raises(rss.RecoveryError, match='--replace'):
        rss.restore(target, None, output, prior_backup=output)
    result = rss.restore(target, None, output, prior_backup=output, replace=True)
    assert result['dry_run'] and lab.restore_calls == 0


def test_fresh_restore_requires_empty_database_and_absent_sqlite(target, lab, tmp_path, monkeypatch):
    output = tmp_path / 'pair'
    rss.backup(target, lab, output, execute=True)
    fresh_target = copy.deepcopy(target)
    fresh_target['sqlite']['path'] = str(tmp_path / 'fresh.sqlite3')
    original_sql = lab.sql
    monkeypatch.setattr(lab, 'sql', lambda manifest, sql: '1' if 'pg_tables' in sql else original_sql(manifest, sql))
    with pytest.raises(rss.RecoveryError, match='not empty'):
        rss.restore(fresh_target, lab, output, prior_backup=None, fresh=True, execute=True)
    assert lab.restore_calls == 0
    monkeypatch.setattr(lab, 'sql', lambda manifest, sql: '0' if 'pg_tables' in sql else original_sql(manifest, sql))
    rss.restore(fresh_target, lab, output, prior_backup=None, fresh=True, execute=True)
    assert Path(fresh_target['sqlite']['path']).exists() and lab.restore_calls == 1
    with pytest.raises(rss.RecoveryError, match='absent SQLite'):
        rss.restore(fresh_target, lab, output, prior_backup=None, fresh=True)


def test_protected_secret_backup_is_private_and_never_silently_overwrites_reference(target, lab, tmp_path):
    secret = tmp_path / 'collector-token'
    secret.write_text('synthetic-only-token')
    secret.chmod(0o600)
    target['secret_refs'] = {'collector-token': str(secret)}
    output = tmp_path / 'pair'
    rss.backup(target, lab, output, execute=True)
    saved = output / 'secrets/collector-token'
    assert saved.read_bytes() == secret.read_bytes() and saved.stat().st_mode & 0o777 == 0o600
    assert saved.parent.stat().st_mode & 0o777 == 0o700
    secret.chmod(0o644)
    with pytest.raises(rss.RecoveryError, match='no group/other access'):
        rss.validate_manifest(target, 'isolated', target['project'])
    secret.chmod(0o600)
    secret.write_text('new-credential')
    with pytest.raises(rss.RecoveryError, match='restore its protected backup separately'):
        rss.load_pair(output, target)
    assert secret.read_text() == 'new-credential'


@pytest.mark.parametrize('mismatch', ['extra_container', 'pg_image', 'engine_database', 'sqlite_mount', 'pg_port'])
def test_explicit_container_volume_and_connection_allowlist_fails_closed(target, monkeypatch, mismatch):
    app_id = '3' * 64
    target['writers']['roles']['app'] = [app_id]
    values = {}
    for container, (service, image) in rss.container_inventory(target).items():
        values[container] = {'Id': container, 'Config': {'Image': image or 'synthetic',
            'Labels': {'com.docker.compose.project': target['project'], 'com.docker.compose.service': service},
            'Env': ['DATABASE_URL=postgres://miniflux:synthetic@rss-db/miniflux']},
            'HostConfig': {'PortBindings': {}}, 'State': {'Running': True}, 'Mounts': []}
    values[app_id]['Mounts'] = [{'Type': 'bind', 'Source': str(Path(target['sqlite']['path']).parent),
                              'Destination': '/var/lib/newshub/db', 'RW': True}]
    values[target['postgres']['container_id']]['Mounts'] = [{'Type': 'volume', 'Name': target['postgres']['volume'],
        'Destination': '/var/lib/postgresql/data', 'Source': '/explicit-synthetic-pg', 'RW': True}]
    if mismatch == 'pg_image':
        values[target['postgres']['container_id']]['Config']['Image'] = 'wrong:latest'
    elif mismatch == 'engine_database':
        values[target['engine']['container_id']]['Config']['Env'] = ['DATABASE_URL=postgres://miniflux:synthetic@rss-db/unrelated']
    elif mismatch == 'sqlite_mount':
        values[app_id]['Mounts'][0]['Source'] = '/unrelated-database'
    elif mismatch == 'pg_port':
        values[target['postgres']['container_id']]['HostConfig']['PortBindings'] = {'5432/tcp': [{'HostPort': '5432'}]}
    def command(arguments, **kwargs):
        assert arguments[:3] == ['docker', 'ps', '-aq']
        ids = list(values) + (['4' * 64] if mismatch == 'extra_container' else [])
        return '\n'.join(ids).encode()
    monkeypatch.setattr(rss, 'command', command)
    fake = Mock(inspect=lambda container: values[container])
    with pytest.raises(rss.RecoveryError):
        rss.verify_targets(target, fake)
