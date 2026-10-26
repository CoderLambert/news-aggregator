"""Directory contracts using pinned real metadata and isolated synthetic SQLite."""
import copy
import hashlib
import json
import os
import pathlib
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
from api.rss.catalog_taxonomy import SECTIONS


def seed():
    return json.loads(SEED_PATH.read_bytes())


def publish(document):
    payload = json.dumps(document, ensure_ascii=False).encode()
    return import_snapshot(payload, expected_checksum=hashlib.sha256(payload).hexdigest())


def test_pinned_source_format_and_license_receipts():
    lock = json.loads(SEED_PATH.with_suffix('.lock.json').read_text())
    data = SEED_PATH.parent
    assert hashlib.sha256(SEED_PATH.read_bytes()).hexdigest() == lock['sha256']
    assert lock['upstream']['commit'] == 'f9b54abf9dd3e7af2a1dda12bca06c8fe8b57d7b'
    assert lock['upstream']['license'] == 'CC0-1.0'
    assert (lock['selected_entries'], lock['included_entries'], lock['restricted_entries']) == (200, 194, 6)
    assert hashlib.sha256((data / 'tidings-top200.opml').read_bytes()).hexdigest() == lock['upstream']['sha256']
    assert hashlib.sha256((data / lock['upstream']['license_path']).read_bytes()).hexdigest() == lock['upstream']['license_sha256']
    assert hashlib.sha256((data / lock['import_report']['path']).read_bytes()).hexdigest() == lock['import_report']['sha256']
    receipt = lock['description_input']
    assert hashlib.sha256((data / receipt['receipt']).read_bytes()).hexdigest() == receipt['receipt_sha256']
    report = json.loads((data / lock['import_report']['path']).read_text())
    descriptions = json.loads((data / receipt['receipt']).read_text())
    assert len(report) == 200 and len(descriptions) == 194
    assert sum(row['status'] == 'included' for row in report) == 194
    assert sum(row['status'] == 'restricted' for row in report) == 6
    rsshub = json.loads((data / 'rsshub-format.lock.json').read_text())
    assert rsshub['license'] == 'AGPL-3.0-only'
    assert hashlib.sha256((data / 'rsshub-AGPL-3.0.txt').read_bytes()).hexdigest() == rsshub['files']['LICENSE']['sha256']
    assert hashlib.sha256((data / 'rsshub-subset-v1.json').read_bytes()).hexdigest() == rsshub['subset_sha256']


@pytest.mark.django_db
def test_real_seed_queries_are_local_and_deterministic(monkeypatch):
    from api.models import ChannelSubscription, Source
    before = (Source.objects.count(), ChannelSubscription.objects.count())
    def no_network(*args, **kwargs):
        raise AssertionError('directory search/import attempted network')
    monkeypatch.setattr(socket, 'socket', no_network)
    snapshot = import_pinned_seed()
    assert snapshot.entries.count() == 194
    for query in ['OpenAI', '机器之心', 'Security', 'Podcasts']:
        first = search_directory(query)
        assert first['results'], query
        assert first == search_directory(query)
        assert first['snapshot_version'] == snapshot.checksum
        for result in first['results']:
            assert result['verified_at'] is None
            assert result['subscribed'] is None
            assert result['cached_articles'] == []
            assert not {'heat', 'topFeeds', 'subscriptionCount', 'radar', 'handler'} & result.keys()
    openai = next(row for row in search_directory('OpenAI')['results']
                  if row['name'] == 'OpenAI News')
    assert openai['origin']['id'] == 'fuxiaoai/tidings-rss'
    assert openai['origin']['license'] == 'CC0-1.0'
    assert openai['origin']['key'] == 'https://openai.com/news/rss.xml'
    assert openai['description'].startswith('OpenAI 官方动态')
    machine_heart = next(row for row in search_directory('机器之心')['results']
                         if row['name'] == '机器之心')
    assert machine_heart['public_url'].startswith('https://wechat2rss.')
    assert machine_heart['tags'] == ['🤖 Artificial Intelligence']
    assert not snapshot.entries.exclude(kind='feed').exists()
    assert before == (Source.objects.count(), ChannelSubscription.objects.count())


@pytest.mark.django_db
@pytest.mark.parametrize('damage', ['checksum', 'schema', 'license', 'duplicate', 'late-invalid', 'personal', 'verified', 'ambiguous', 'empty', 'private-url'])
def test_bad_updates_keep_old_snapshot(damage):
    previous = import_pinned_seed()
    document = seed()
    rows = document['entries']
    if damage == 'checksum':
        with pytest.raises(DirectoryValidationError, match='checksum'):
            import_snapshot(SEED_PATH.read_bytes(), expected_checksum='0' * 64)
        assert FeedDirectorySnapshot.objects.get(active=True).pk == previous.pk
        return
    if damage == 'schema': document['schema_version'] = 99
    elif damage == 'license': del document['source']['license']
    elif damage == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif damage == 'late-invalid': rows[-1]['name'] = None
    elif damage == 'personal': rows[0]['visibility'] = 'personal'
    elif damage == 'verified': rows[0]['verified_at'] = '2026-10-16T00:00:00Z'
    elif damage == 'ambiguous': document['namespaces'] = {}
    elif damage == 'empty': document['entries'] = []
    elif damage == 'private-url': rows[0]['public_url'] = 'https://127.0.0.1/feed'
    with pytest.raises(DirectoryValidationError): publish(document)
    assert FeedDirectorySnapshot.objects.get(active=True).pk == previous.pk
    assert previous.entries.count() == 194
    assert FeedDirectorySnapshot.objects.count() == 1


@pytest.mark.django_db
def test_failed_database_write_rolls_back_activation():
    previous = import_pinned_seed()
    document = seed()
    document['entries'][0]['description'] += ' next'
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
    document['entries'].reverse()
    current = publish(document)
    assert set(current.entries.values_list('entry_id', flat=True)) == ids
    previous.refresh_from_db()
    assert not previous.active
    assert current.active and previous.entries.count() == 194
    assert search_directory('OpenAI') == search_directory('OPENAI')


@pytest.mark.django_db
def test_ranking_exact_prefix_then_featured_and_text_kind_name_id():
    document = seed()
    document['entries'] = [
        {'key': 'exact', 'name': 'React', 'public_url': 'https://exact.example.org/feed'},
        {'key': 'prefix', 'name': 'React news', 'public_url': 'https://prefix.example.org/feed'},
        {'key': 'featured', 'name': 'OpenAI News', 'tags': ['React'], 'public_url': 'https://featured.example.org/feed'},
        {'key': 'tag', 'name': 'Other', 'tags': ['React'], 'public_url': 'https://other.example.org/feed'},
        {'key': 'template', 'name': 'Other route', 'tags': ['React'], 'kind': 'route_template', 'public_url': '/example/:user', 'required_parameters': ['user']},
        {'key': 'tie-a', 'name': 'Other A', 'tags': ['React'], 'public_url': 'https://a.example.org/feed'},
        {'key': 'tie-b', 'name': 'Other A', 'tags': ['React'], 'public_url': 'https://b.example.org/feed'},
        {'key': 'hidden', 'name': 'React hidden', 'visibility': 'hidden', 'public_url': 'https://hidden.example.org/feed'},
    ]
    publish(document)
    results = search_directory('react')['results']
    assert [row['name'] for row in results[:2]] == ['React', 'React news']
    assert [(row['name'], row['recommended']) for row in results] == [
        ('React', False), ('React news', False), ('OpenAI News', True),
        ('Other', False), ('Other A', False), ('Other A', False), ('Other route', False),
    ]
    assert results[-1]['kind'] == 'route_template'
    duplicate_names = [row['id'] for row in results if row['name'] == 'Other A']
    assert duplicate_names == sorted(duplicate_names)
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
    document = seed(); document['entries'][0]['name'] += ' changed'
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
    assert search_directory() == {
        'results': [], 'next_cursor': None, 'snapshot_version': None,
        'total': 0,
        'count_scope': 'public_catalog_unique_feed_urls',
        'sections': [dict(section, count=0, groups=[dict(group, count=0) for group in section['groups']])
                     for section in SECTIONS],
        'categories': [
            {'id': 'ai', 'name': '人工智能'},
            {'id': 'engineering', 'name': '编程与技术'},
            {'id': 'security', 'name': '网络安全'},
            {'id': 'news', 'name': '科技与资讯'},
            {'id': 'science', 'name': '科学研究'},
            {'id': 'design', 'name': '产品与设计'},
            {'id': 'business', 'name': '商业与创业'},
            {'id': 'culture', 'name': '人文与博客'},
            {'id': 'community', 'name': '社区与播客'},
        ],
    }
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
    # backend/ must be on PYTHONPATH so the subprocess can import `newsaggregator`.
    # Derive it from __file__: test_directory.py → rss/ → tests/ → api/ → backend/
    _backend_dir = str(pathlib.Path(__file__).resolve().parents[3])
    _existing_pypath = os.environ.get('PYTHONPATH', '')
    _pythonpath = _backend_dir if not _existing_pypath else f'{_backend_dir}{os.pathsep}{_existing_pypath}'
    environment = dict(os.environ, DJANGO_SETTINGS_MODULE='newsaggregator.settings', DJANGO_ENV='development', RUN_MAIN='true', DJANGO_DB_PATH=str(tmp_path / 'directory-migration.sqlite3'), PYTHONPATH=_pythonpath)
    result = subprocess.run([sys.executable, '-c', program], env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
