"""T27 recorded evidence checks, plus explicit opt-in fresh browser/engine run."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'ops/rss/T27/evidence'


def read(name):
    return json.loads((EVIDENCE / name).read_text())


def test_browser_actual_checks_and_isolated_cleanup():
    result = read('browser-evidence.json')
    assert result['status'] == 'passed'
    for key in ('passive_no_collection', 'exact_code_clipboard_table_image',
                'account_switch_cache_and_private_acl', 'read_favorite_reload_user_isolation',
                'fake_ai_authorized_context_and_b_denied',
                'directory_local_discovery_0_1_3_direct_multigroup',
                'opml_selection_multigroup_progress_export',
                'explicit_repair_durable_sync_visible',
                'unsubscribe_reload_revokes_private_access',
                'mobile_keyboard_focus_escape_no_overflow'):
        assert result['checks'][key] is True, key
    assert result['checks']['browser_errors'] == []
    cleanup = read('cleanup.json')
    assert cleanup['resources_removed'] is True
    assert cleanup['project'] == result['project']
    assert result['project'].startswith('newshub-rss-t27-')


def test_passive_browser_and_restricted_publisher_never_fetch_article():
    requests = read('network.json')
    passive = [row for row in requests if row['phase'] == 'passive_anonymous']
    assert passive and all(row['method'] == 'GET' for row in passive)
    assert any('/rss-refetch/' in row['url'] and row['method'] == 'POST'
               and row['phase'] == 'explicit_repair' for row in requests)
    publisher = [json.loads(line) for line in (EVIDENCE / 'publisher-requests.jsonl').read_text().splitlines()]
    ended = read('browser-evidence.json')['checks']['passive_ended_at']
    assert not [row for row in publisher if row['path'].startswith('/article/') and row['time'] <= ended]
    assert not [row for row in publisher if row['path'] == '/article/restricted']
    assert any(row['path'] == '/article/public' for row in publisher)


def test_public_sampling_keeps_failure_and_unknown_completeness():
    result = read('public-samples.json')
    assert result['resources_removed'] and result['private_network_guard']
    assert {row['name'] for row in result['feeds']} == {
        'Julia Evans', 'WebKit', 'Martin Fowler', 'Uber Engineering', 'DEV Community', 'Hacker News'}
    for kind in ('native', 'summary_blog', 'dev', 'hn'):
        assert sum(len(row['entries']) for row in result['feeds'] if row['class'] == kind) <= 5
    assert next(row for row in result['feeds'] if row['name'] == 'Uber Engineering')['status'] == 'failed'
    assert 'self_post' in next(row for row in result['feeds'] if row['class'] == 'hn')['subtypes_missing']
    assert all(item['manual_completeness'] == 'not_confirmed'
               for row in result['feeds'] for item in row['entries'])


@pytest.mark.rss_live
def test_fresh_real_browser_and_engine(tmp_path):
    if os.environ.get('RSS_TEST_ALLOW_LIVE') != '1':
        pytest.skip('fresh isolated Docker/browser run requires RSS_TEST_ALLOW_LIVE=1')
    path = os.environ.get('RSS_TEST_CONFIG')
    assert path, 'explicit allowlist configuration required'
    config = json.loads(Path(path).read_text())
    assert config == {'allow_project_prefix': 'newshub-rss-t27-', 'allow_loopback_app': True,
                      'allow_synthetic_publisher': True, 'allow_public_sampling': False}
    subprocess.run([sys.executable, str(ROOT / 'ops/rss/T27/run_browser.py'),
                    '--output', str(tmp_path / 'browser')], cwd=ROOT, check=True, timeout=900)
    result = json.loads((tmp_path / 'browser/browser-evidence.json').read_text())
    assert result['status'] == 'passed'
