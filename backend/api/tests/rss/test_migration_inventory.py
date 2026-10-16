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
