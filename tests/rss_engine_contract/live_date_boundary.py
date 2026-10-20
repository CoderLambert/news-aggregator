"""Explicit live-only scenario, run by T00; excluded from offline collection."""
import time

import pytest
import requests


@pytest.mark.rss_live
def test_frozen_seven_day_rule_filters_before_extraction_and_survives_poll(lab):
    client = lab.client()
    requests.post(lab.fixture_url + '/state', json={'version': 9}, timeout=5).raise_for_status()
    feed_id = client.create_feed('http://fixture:8000/date-feed', crawler=True,
        block_filter_entry_rules='EntryDate=before:2026-10-14')
    expected = {'date-boundary', 'date-offset-boundary', 'date-new'}
    entries = client.get_feed_entries(feed_id)['entries']
    assert {row['url'].rsplit('/', 1)[-1] for row in entries} == expected
    assert all('Synthetic article' in row['content'] for row in entries)
    paths = [row['path'] for row in requests.get(lab.fixture_url + '/state', timeout=5).json()['requests']]
    assert '/article/date-old' not in paths and '/article/date-offset-old' not in paths
    assert all('/article/' + key in paths for key in expected)
    before = client.get_feed(feed_id)['checked_at']
    client.refresh_feed(feed_id)
    deadline = time.monotonic() + 20
    while client.get_feed(feed_id)['checked_at'] == before and time.monotonic() < deadline:
        time.sleep(.2)
    assert client.get_feed(feed_id)['checked_at'] != before
    assert client.get_feed(feed_id)['block_filter_entry_rules'] == 'EntryDate=before:2026-10-14'
    paths = [row['path'] for row in requests.get(lab.fixture_url + '/state', timeout=5).json()['requests']]
    assert '/article/date-old' not in paths and '/article/date-offset-old' not in paths
    assert {row['url'].rsplit('/', 1)[-1] for row in client.get_feed_entries(feed_id)['entries']} == expected
