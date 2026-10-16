"""Directory contracts using pinned real metadata and isolated synthetic SQLite."""
import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
from unittest.mock import patch

import pytest
from django.db import IntegrityError

from api.rss.directory import (
    DirectoryCursorError, DirectoryValidationError, SEED_PATH,
    import_pinned_seed, import_snapshot, search_directory,
)
from api.rss.directory_models import FeedDirectoryEntry, FeedDirectorySnapshot


def seed():
    return json.loads(SEED_PATH.read_bytes())


def publish(document):
    payload = json.dumps(document, ensure_ascii=False).encode()
    return import_snapshot(payload, expected_checksum=hashlib.sha256(payload).hexdigest())


def test_pinned_source_format_and_license_receipts():
    lock = json.loads(SEED_PATH.with_suffix('.lock.json').read_text())
    assert hashlib.sha256(SEED_PATH.read_bytes()).hexdigest() == lock['sha256']
    assert lock['upstream']['commit'] == '9ab2482cae9031a5a39635c887fcfc8ece7e130a'
    assert lock['upstream']['license'] == 'CC0-1.0'
    assert lock['upstream']['included_entries'] == 38
    assert len(lock['upstream']['excluded_insecure_http_urls']) == 7
    assert hashlib.sha256((SEED_PATH.parent / 'plenary-CC0-1.0.txt').read_bytes()).hexdigest() == lock['upstream']['license_sha256']
    rsshub = json.loads((SEED_PATH.parent / 'rsshub-format.lock.json').read_text())
    assert rsshub['license'] == 'AGPL-3.0-only'
    assert hashlib.sha256((SEED_PATH.parent / 'rsshub-AGPL-3.0.txt').read_bytes()).hexdigest() == rsshub['files']['LICENSE']['sha256']
    assert hashlib.sha256((SEED_PATH.parent / 'rsshub-subset-v1.json').read_bytes()).hexdigest() == rsshub['subset_sha256']


@pytest.mark.django_db
def test_real_seed_queries_are_local_and_deterministic(monkeypatch):
    from api.models import ChannelSubscription, Source
    before = (Source.objects.count(), ChannelSubscription.objects.count())
    def no_network(*args, **kwargs):
        raise AssertionError('directory search/import attempted network')
    monkeypatch.setattr(socket, 'socket', no_network)
    snapshot = import_pinned_seed()
    assert snapshot.entries.count() == 41
    for query in ['github', 'React', '健康', '中文']:
        first = search_directory(query)
        assert first['results'], query
        assert first == search_directory(query)
        assert first['snapshot_version'] == snapshot.checksum
        for result in first['results']:
            assert result['verified_at'] is None
            assert result['subscribed'] is None
            assert result['cached_articles'] == []
            assert not {'heat', 'topFeeds', 'subscriptionCount', 'radar', 'handler'} & result.keys()
    github = search_directory('github')['results']
    native = next(row for row in github if row['name'] == 'The GitHub Blog')
    assert native['origin']['id'] == 'plenaryapp/awesome-rss-feeds'
    assert native['origin']['license'] == 'CC0-1.0'
    template = next(row for row in github if row['kind'] == 'route_template')
    assert template['public_url'] == '/github/issue/:user/:repo/:state?/:labels?'
    assert template['required_parameters'] == ['repo', 'user']
    assert template['origin']['license'] == 'AGPL-3.0-only'
    assert before == (Source.objects.count(), ChannelSubscription.objects.count())


@pytest.mark.django_db
@pytest.mark.parametrize('damage', ['checksum', 'schema', 'license', 'duplicate', 'late-invalid', 'personal', 'verified', 'ambiguous', 'empty', 'private-url'])
def test_bad_updates_keep_old_snapshot(damage):
    previous = import_pinned_seed()
    document = seed()
    rows = document['collections'][0]['entries']
    if damage == 'checksum':
        with pytest.raises(DirectoryValidationError, match='checksum'):
            import_snapshot(SEED_PATH.read_bytes(), expected_checksum='0' * 64)
        assert FeedDirectorySnapshot.objects.get(active=True).pk == previous.pk
        return
    if damage == 'schema': document['schema_version'] = 99
    elif damage == 'license': del document['collections'][0]['source']['license']
    elif damage == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif damage == 'late-invalid': rows[-1]['name'] = None
    elif damage == 'personal': rows[0]['visibility'] = 'personal'
    elif damage == 'verified': rows[0]['verified_at'] = '2026-10-16T00:00:00Z'
    elif damage == 'ambiguous': document['collections'][0]['namespaces'] = {}
    elif damage == 'empty': document['collections'] = []
    elif damage == 'private-url': rows[0]['public_url'] = 'https://127.0.0.1/feed'
    with pytest.raises(DirectoryValidationError): publish(document)
    assert FeedDirectorySnapshot.objects.get(active=True).pk == previous.pk
    assert previous.entries.count() == 41
    assert FeedDirectorySnapshot.objects.count() == 1


@pytest.mark.django_db
def test_failed_database_write_rolls_back_activation():
    previous = import_pinned_seed()
    document = seed()
    document['collections'][0]['entries'][0]['description'] += ' next'
    with patch.object(FeedDirectoryEntry.objects, 'bulk_create', side_effect=IntegrityError('simulated write failure')):
        with pytest.raises(IntegrityError): publish(document)
    assert FeedDirectorySnapshot.objects.get(active=True).pk == previous.pk
    assert FeedDirectorySnapshot.objects.count() == 1


@pytest.mark.django_db
def test_reimport_and_updates_keep_stable_ids_and_retained_snapshots():
    previous = import_pinned_seed()
    ids = set(previous.entries.values_list('entry_id', flat=True))
    assert import_pinned_seed().pk == previous.pk
    assert FeedDirectorySnapshot.objects.count() == 1
    document = seed()
    document['collections'][0]['entries'].reverse()
    current = publish(document)
    assert set(current.entries.values_list('entry_id', flat=True)) == ids
    previous.refresh_from_db()
    assert not previous.active
    assert current.active and previous.entries.count() == 41
    assert search_directory('React') == search_directory('REACT')


@pytest.mark.django_db
def test_ranking_exact_prefix_text_then_availability_and_id():
    document = seed()
    document.pop('collections')
    document['entries'] = [
        {'key': 'exact', 'name': 'React', 'public_url': 'https://exact.example.org/feed'},
        {'key': 'prefix', 'name': 'React news', 'public_url': 'https://prefix.example.org/feed'},
        {'key': 'tag', 'name': 'Other', 'tags': ['React'], 'public_url': 'https://other.example.org/feed'},
        {'key': 'template', 'name': 'Other route', 'tags': ['React'], 'kind': 'route_template', 'public_url': '/example/:user', 'required_parameters': ['user']},
        {'key': 'tie-a', 'name': 'Other A', 'tags': ['React'], 'public_url': 'https://a.example.org/feed'},
        {'key': 'tie-b', 'name': 'Other B', 'tags': ['React'], 'public_url': 'https://b.example.org/feed'},
        {'key': 'hidden', 'name': 'React hidden', 'visibility': 'hidden', 'public_url': 'https://hidden.example.org/feed'},
    ]
    publish(document)
    results = search_directory('react')['results']
    assert [row['name'] for row in results[:2]] == ['React', 'React news']
    assert results[-1]['kind'] == 'route_template'
    assert [row['id'] for row in results[2:-1]] == sorted(row['id'] for row in results[2:-1])
    assert all(row['name'] != 'React hidden' for row in results)
    assert search_directory('https://exact.example.org/feed')['results'][0]['name'] == 'React'


@pytest.mark.django_db
def test_signed_cursor_binds_query_and_snapshot():
    import_pinned_seed()
    all_rows = search_directory(limit=50)['results']
    first = search_directory(limit=5)
    second = search_directory(limit=5, cursor=first['next_cursor'])
    assert first['results'] + second['results'] == all_rows[:10]
    for cursor, q in [('garbage', ''), (first['next_cursor'], 'different')]:
        with pytest.raises(DirectoryCursorError): search_directory(q, cursor=cursor)
    document = seed(); document['collections'][0]['entries'][0]['name'] += ' changed'
    publish(document)
    with pytest.raises(DirectoryCursorError): search_directory(cursor=first['next_cursor'])


@pytest.mark.django_db
def test_rsshub_ignores_scripts_analytics_and_preserves_requirements():
    document = json.loads((SEED_PATH.parent / 'rsshub-subset-v1.json').read_bytes())
    namespace = document['namespaces']['github']; namespace['heat'] = 9999
    route = next(iter(namespace['routes'].values()))
    route.update({'radar': {'target': 'throw new Error()'}, 'handler': 'exec', 'topFeeds': [1], 'heat': 99999,
                  'features': {'requireConfig': [{'name': 'ACCESS_TOKEN', 'description': 'x'}, {'name': 'OPTIONAL', 'optional': True}], 'requirePuppeteer': True}})
    publish(document)
    result = search_directory('github')['results'][0]
    assert result['kind'] == 'route_template'
    assert result['capability_requirements'] == ['config:ACCESS_TOKEN', 'requirePuppeteer']
    assert result['verified_at'] is None
    assert 'throw new Error' not in json.dumps(result)


@pytest.mark.django_db
def test_empty_directory_and_input_limits():
    assert search_directory() == {'results': [], 'next_cursor': None, 'snapshot_version': None}
    for limit in (0, 51, True, '2'):
        with pytest.raises(DirectoryValidationError): search_directory(limit=limit)
    with pytest.raises(DirectoryValidationError): search_directory('x' * 201)
    for payload in (b'not json', b'{"schema_version":1,"schema_version":1}', b'\xff'):
        with pytest.raises(DirectoryValidationError): import_snapshot(payload, expected_checksum=hashlib.sha256(payload).hexdigest())


def test_real_0051_to_0052_migration(tmp_path):
    # Separate process and explicit disposable DB: never touch the caller DB.
    program = '''
import django
django.setup()
from django.db import connection, transaction, IntegrityError
from django.db.migrations.executor import MigrationExecutor
old = ('api', '0051_seed_domestic_medical_sources')
new = ('api', '0052_feed_directory')
executor = MigrationExecutor(connection)
executor.migrate([old])
apps = executor.loader.project_state([old]).apps
Source = apps.get_model('api', 'Source')
original_ids = set(Source.objects.values_list('pk', flat=True))
executor = MigrationExecutor(connection)
executor.migrate([new])
apps = executor.loader.project_state([new]).apps
Snapshot = apps.get_model('api', 'FeedDirectorySnapshot')
Entry = apps.get_model('api', 'FeedDirectoryEntry')
assert original_ids == set(apps.get_model('api', 'Source').objects.values_list('pk', flat=True))
first = Snapshot.objects.create(checksum='a'*64, commit='b'*40, license='CC0-1.0', schema_version=1, active=True)
try:
    with transaction.atomic():
        Snapshot.objects.create(checksum='c'*64, commit='b'*40, license='CC0-1.0', schema_version=1, active=True)
except IntegrityError:
    pass
else:
    raise AssertionError('active uniqueness not enforced')
import uuid
entry_id = uuid.uuid4()
Entry.objects.create(snapshot=first, entry_id=entry_id, name='one', kind='feed', public_url='https://example.org/feed')
try:
    with transaction.atomic():
        Entry.objects.create(snapshot=first, entry_id=entry_id, name='duplicate', kind='feed', public_url='https://example.org/feed')
except IntegrityError:
    pass
else:
    raise AssertionError('stable entry uniqueness not enforced')
assert Entry.objects.count() == 1
connection.close()
'''
    environment = dict(os.environ, DJANGO_SETTINGS_MODULE='newsaggregator.settings', DJANGO_ENV='development', RUN_MAIN='true', DJANGO_DB_PATH=str(tmp_path / 'directory-migration.sqlite3'))
    result = subprocess.run([sys.executable, '-c', program], env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
