from pathlib import Path
import pytest
from api.rss.migration_inventory import build_inventory, canonical_feed
from api.services.source_policy import POLICIES

ROOT = Path(__file__).resolve().parents[4]


def test_static_inventory_preserves_all_policies_without_claiming_live_evidence():
    manifest = build_inventory(ROOT, 'synthetic')
    rows = {r['source_key']: r for r in manifest['sources']}
    assert rows.keys() == POLICIES.keys()
    assert manifest['snapshot_status'] == 'BLOCKED'
    assert all(r['source_id'] is None and not r['production_ready'] for r in rows.values())
    assert 'six tag' in rows['devto']['legacy_selection']
    assert '80' in rows['hackernews']['legacy_selection']
    assert 'abstracts' in rows['arxiv_ai']['coverage_difference']
    assert rows['github']['target_feed_url'] is None


def test_database_union_keeps_unknown_and_multiple_keys_without_name_matching():
    snapshot = {'id': 'synthetic-copy', 'sources': [
        {'source_id': 9, 'source_keys': ['devto', 'devto_alias'], 'display_name': 'Dev.to'},
        {'source_id': 10, 'source_keys': ['dynamic_html'], 'display_name': 'Dev.to',
         'publication': 'personal', 'owner': 'paused', 'epoch': 4},
    ]}
    result = build_inventory(ROOT, 'synthetic', snapshot=snapshot)
    rows = {r['inventory_key']: r for r in result['sources']}
    assert 'code:devto' not in rows
    assert rows['source:9']['source_keys'] == ['devto', 'devto_alias']
    assert rows['source:10']['publication'] == 'personal'
    assert rows['source:10']['expected_owner'] == 'paused'
    assert not result['production_ready']


def test_shared_feed_group_preserves_query_and_path_identity():
    result = build_inventory(ROOT, 'synthetic', targets={
        'code:devto': 'https://EXAMPLE.org:443/Feed?tag=python#fragment',
        'code:hackernews': 'https://example.org/Feed?tag=python',
        'code:github': 'https://example.org/feed?tag=python',
    })
    groups = result['switch_groups']
    assert len(groups) == 2
    assert any(g['members'] == ['code:devto', 'code:hackernews'] for g in groups)


def test_unsupported_keeps_publication_unknown_and_requires_explicit_disposition():
    row = next(r for r in build_inventory(ROOT, 'synthetic')['sources'] if r['source_key'] == 'reuters')
    assert row['unsupported_reason']
    assert row['publication'] == 'UNKNOWN'
    assert row['decision'] == 'review_required'
    assert row['desired_mode'] == 'feed'
    assert row['body_takeover'] == []


def test_invalid_snapshot_identity_and_target_are_rejected():
    with pytest.raises(ValueError):
        build_inventory(ROOT, 'synthetic', snapshot={'id': 'x', 'sources': [{'source_id': True}]})
    with pytest.raises(ValueError):
        build_inventory(ROOT, 'synthetic', targets={'unknown': 'https://example.org/feed'})
    with pytest.raises(ValueError):
        canonical_feed('https://user:secret@example.org/feed')


def test_standalone_snapshot_is_readonly_and_exports_hashes_not_content(tmp_path):
    import hashlib
    import sqlite3
    from api.rss.inventory_snapshot import extract_snapshot
    path = tmp_path / 'synthetic.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE api_source(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE api_news(id INTEGER PRIMARY KEY, full_content TEXT, full_content_zh TEXT);
            CREATE TABLE api_newssourceitem(id INTEGER PRIMARY KEY, source_key TEXT);
            CREATE TABLE api_sourceconfig(source_key TEXT PRIMARY KEY, source_id INTEGER, reading_policy TEXT, status TEXT);
            INSERT INTO api_source VALUES(1,'Dev.to');
            INSERT INTO api_news VALUES(7,'original-private-content','unique-legacy-translation');
            INSERT INTO api_sourceconfig VALUES('unbound_dynamic',NULL,'summary_only','draft');
        ''')
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    result = extract_snapshot(path, expected_sha256=checksum)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    assert result['sources'][0]['source_keys'] == ['devto']
    assert result['table_fingerprints']['api_news']['rows'] == 1
    assert result['unbound_source_configs'][0]['source_key'] == 'unbound_dynamic'
    assert 'original-private-content' not in str(result)
    assert 'unique-legacy-translation' not in str(result)
    with pytest.raises(ValueError, match='hash mismatch'):
        extract_snapshot(path, expected_sha256='0' * 64)
    Path(str(path) + '-wal').write_bytes(b'not-a-standalone-copy')
    with pytest.raises(ValueError, match='standalone'):
        extract_snapshot(path, expected_sha256=checksum)
