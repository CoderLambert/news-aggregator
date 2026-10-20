"""The existing online backup stays consistent with ingestion WAL writers."""
import json
import sqlite3

import pytest

from scripts.deploy import sqlite_snapshot
from scripts.deploy.tests.test_release_operations import make_database, manifest


@pytest.mark.parametrize('version', [3, 4])
def test_online_backup_with_active_ingestion_writer_and_worker_manifest(tmp_path, version):
    source = tmp_path / 'writer.sqlite3'
    writer = make_database(source)
    try:
        writer.executescript('''
          CREATE TABLE api_newssourceitem (id INTEGER PRIMARY KEY, news_id INTEGER, upstream_id TEXT);
          CREATE TABLE api_feedstate (id INTEGER PRIMARY KEY, revision INTEGER);
          CREATE TABLE api_requestbudget (key TEXT PRIMARY KEY, cooldown_until TEXT);
          INSERT INTO api_newssourceitem VALUES (1, 1, 'real-identity');
          INSERT INTO api_feedstate VALUES (1, 7);
          INSERT INTO api_requestbudget VALUES ('host:example.test', '2030-01-01');
        ''')
        release = manifest()
        release.update(schema_version=version, capabilities={
            'full_content_worker': True,
            'channel_worker': True,
        })
        if version == 4:
            release['capabilities']['crawler_worker'] = False
        manifest_file = tmp_path / 'release.json'
        manifest_file.write_text(json.dumps(release))
        # A new process-style independent connection can read a complete commit
        # while this writer holds an unfinished next ingestion transaction.
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("UPDATE api_newssourceitem SET upstream_id='uncommitted'")
        writer.execute('UPDATE api_feedstate SET revision=8')
        writer.execute("UPDATE api_requestbudget SET cooldown_until='2031-01-01'")
        snapshot = tmp_path / 'snapshot.sqlite3'
        sqlite_snapshot.backup_database(source, snapshot, manifest_file)
        with sqlite3.connect(snapshot) as reader:
            assert reader.execute('PRAGMA quick_check').fetchone() == ('ok',)
            assert reader.execute('SELECT upstream_id FROM api_newssourceitem').fetchone() == ('real-identity',)
            assert reader.execute('SELECT revision FROM api_feedstate').fetchone() == (7,)
            assert reader.execute('SELECT cooldown_until FROM api_requestbudget').fetchone() == ('2030-01-01',)
        writer.rollback()
        restored = tmp_path / 'restored.sqlite3'
        sqlite_snapshot.restore_database(snapshot, restored, manifest_file)
        assert sqlite_snapshot.inspect_database(restored)['quick_check'] == 'ok'
    finally:
        writer.close()


@pytest.mark.parametrize('capability', [1, 'true', None, {'full_content_worker': True, 'other': False}])
def test_backup_refuses_ambiguous_worker_manifest(tmp_path, capability):
    value = manifest()
    value.update(schema_version=2, capabilities=capability if isinstance(capability, dict) else {'full_content_worker': capability})
    file = tmp_path / 'release.json'
    file.write_text(json.dumps(value))
    with pytest.raises(sqlite_snapshot.SnapshotError, match='capability'):
        sqlite_snapshot._read_release_manifest(file)
    with pytest.raises(sqlite_snapshot.SnapshotError, match='capability'):
        sqlite_snapshot._read_release_manifest_from_value(value)


@pytest.mark.parametrize('capabilities', [
    {'full_content_worker': True},
    {'channel_worker': True},
    {'full_content_worker': True, 'channel_worker': 1},
    {'full_content_worker': True, 'channel_worker': True, 'unknown': False},
])
def test_snapshot_refuses_ambiguous_v3_worker_manifest(tmp_path, capabilities):
    value = manifest()
    value.update(schema_version=3, capabilities=capabilities)
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(value))

    with pytest.raises(sqlite_snapshot.SnapshotError, match='capability'):
        sqlite_snapshot._read_release_manifest(path)
