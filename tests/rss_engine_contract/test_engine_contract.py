import time

import miniflux
import pytest
import requests

from contract import MAX_ID, PersistentContentProbe, isolated_project, page_parameters, upper_bound


@pytest.mark.parametrize("status,body,error", [(200, b"not-json", requests.exceptions.JSONDecodeError), (503, b"unavailable", miniflux.ServerError)])
def test_persistent_probe_rejects_abnormal_engine_response(status, body, error):
    class Session:
        headers = {}

        def get(self, url, **kwargs):
            assert url == "http://127.0.0.1:9999/v1/entries/1/fetch-content"
            assert kwargs["params"] == {"update_content": "true"}
            response = requests.Response()
            response.status_code = status
            response._content = body
            return response

    client = PersistentContentProbe("http://127.0.0.1:9999", api_key="synthetic-only", session=Session())
    with pytest.raises(error):
        client.persist_content(1)


@pytest.mark.parametrize("lower,upper", [(0, 0), (0, 101), (101, 101), (MAX_ID-2, MAX_ID-1)])
def test_exclusive_page_bounds(lower, upper):
    params = page_parameters(lower, upper)
    assert params["after_entry_id"] == lower
    assert params["before_entry_id"] == upper + 1
    assert params["order"] == "id" and params["direction"] == "asc"


@pytest.mark.parametrize("lower,upper,limit", [(0, MAX_ID, 100), (-1, 1, 100), (2, 1, 100), (True, 2, 100), (0, 2, 0), (0, 2, 1001)])
def test_reject_unrepresentable_or_invalid_pages(lower, upper, limit):
    with pytest.raises(ValueError):
        page_parameters(lower, upper, limit)


@pytest.mark.parametrize("config", [{}, {"environment": "production", "project": "newshub-rss-t00-0123456789ab"}, {"environment": "isolated", "project": "newshub"}, {"environment": "isolated", "project": "newshub-rss-t00-0123456789ab", "url": "http://localhost"}])
def test_live_target_allowlist(config):
    with pytest.raises(ValueError):
        isolated_project(config)


@pytest.mark.rss_live
def test_a1_empty_database_and_fixed_upper_bound(lab):
    client = lab.client()
    assert upper_bound(client) == 0
    assert client.get_entries(**page_parameters(0, 0))["entries"] == []
    assert client.get_version()["version"] == "2.3.3"
    feed = client.create_feed("http://fixture:8000/feed", crawler=True)
    assert client.get_feed(feed)["crawler"] is True
    upper = upper_bound(client)
    seen, lower = [], 0
    while True:
        entries = client.get_entries(**page_parameters(lower, upper, 3))["entries"]
        if not entries:
            break
        ids = [entry["id"] for entry in entries]
        assert ids == sorted(ids) and all(lower < i <= upper for i in ids)
        # Same cursor returns the same page, without offset assumptions.
        assert ids == [e["id"] for e in client.get_entries(**page_parameters(lower, upper, 3))["entries"]]
        seen.extend(ids)
        lower = ids[-1]
    assert len(seen) == len(set(seen)) == 8 and seen[-1] == upper
    assert len(client.get_entries(order="id", direction="asc", before_entry_id=upper)["entries"]) == 7
    assert client.get_entries(**page_parameters(upper, upper))["entries"] == []
    assert len(client.get_entries(limit=0)["entries"]) <= 1000
    with pytest.raises(miniflux.ClientError):
        client.get_entries(limit=1001)


@pytest.mark.rss_live
def test_a3_refresh_and_explicit_persistent_refetch(lab):
    client = lab.client()
    feed = client.get_feeds()[0]["id"]
    entry = client.get_entries(order="id", direction="asc", limit=1)["entries"][0]
    assert "version 1" in entry["content"]
    requests.post(lab.fixture_url + "/state", json={"version": 2}, timeout=5).raise_for_status()
    before = client.get_feed(feed)["checked_at"]
    assert client.refresh_feed(feed)
    deadline = time.monotonic() + 20
    while client.get_feed(feed)["checked_at"] == before and time.monotonic() < deadline:
        time.sleep(0.2)
    assert client.get_feed(feed)["checked_at"] != before
    assert "version 1" in client.get_entry(entry["id"])["content"]
    assert "version 2" in client.fetch_entry_content(entry["id"])["content"]
    assert "version 1" in client.get_entry(entry["id"])["content"]
    persisted = client.persist_content(entry["id"])
    assert "version 2" in persisted["content"]
    # A separate SDK instance confirms the database, not a returned extraction.
    assert "version 2" in lab.client().get_entry(entry["id"])["content"]


@pytest.mark.rss_live
def test_a2_cleanup_uses_created_at_and_preserves_exceptions(lab):
    dump = lab.compose("exec", "-T", "engine", "/usr/bin/miniflux", "-config-dump")
    assert "CLEANUP_ARCHIVE_READ_DAYS=90" in dump
    assert "CLEANUP_ARCHIVE_UNREAD_DAYS=90" in dump
    ids = [e["id"] for e in lab.client().get_entries(order="id", direction="asc")["entries"]]
    assert len(ids) == 8
    for index, entry_id in enumerate(ids):
        age = 91 if index in (0, 1, 6, 7) else 89
        status = "read" if index % 2 else "unread"
        published = "now()" if age == 91 else "now() - interval '200 days'"
        starred = "true" if index == 6 else "false"
        shared = "t00-shared" if index == 7 else ""
        lab.sql(f"UPDATE entries SET created_at=now()-interval '{age} days', published_at={published}, status='{status}', starred={starred}, share_code='{shared}' WHERE id={entry_id}")
    lab.compose("exec", "-T", "engine", "/usr/bin/miniflux", "-run-cleanup-tasks")
    remaining = {e["id"] for e in lab.client().get_entries()["entries"]}
    assert remaining == set(ids[2:])
    assert lab.sql("SELECT count(*) FROM entry_tombstones") == "2"


@pytest.mark.rss_live
@pytest.mark.parametrize("url", ["http://fixture:8000/feed", "http://127.0.0.1:8000/feed", "http://169.254.169.254/latest/meta-data/", "http://[::1]:8000/feed", "file:///etc/passwd", "ftp://fixture/feed"])
def test_a4_guarded_private_and_dangerous_urls_rejected(lab, url):
    with pytest.raises(miniflux.ClientError) as failure:
        lab.client("guarded").create_feed(url)
    if url.startswith("http:"):
        assert "private network" in str(failure.value).lower()
    assert lab.client("guarded").get_feeds() == []


@pytest.mark.rss_live
@pytest.mark.parametrize("path", ["error", "invalid"])
def test_a4_abnormal_publisher_response_not_registered(lab, path):
    client = lab.client()
    before = {feed["id"] for feed in client.get_feeds()}
    with pytest.raises(miniflux.ClientError):
        client.create_feed("http://fixture:8000/" + path)
    assert {feed["id"] for feed in client.get_feeds()} == before


@pytest.mark.rss_live
def test_a4_feed_credentials_are_not_sent_to_article(lab):
    client = lab.client()
    feed = client.get_feeds()[0]["id"]
    client.update_feed(feed, username="synthetic-feed-user", password="synthetic-feed-password")
    requests.post(lab.fixture_url + "/state", json={"version": 3}, timeout=5).raise_for_status()
    client.refresh_feed(feed)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = requests.get(lab.fixture_url + "/state", timeout=5).json()
        if any(r["path"] == "/feed" and r["auth"] for r in state["requests"]):
            break
        time.sleep(0.2)
    assert any(r["path"] == "/feed" and r["auth"] for r in state["requests"])
    entry_id = client.get_entries(limit=1)["entries"][0]["id"]
    client.persist_content(entry_id)
    state = requests.get(lab.fixture_url + "/state", timeout=5).json()
    articles = [r for r in state["requests"] if r["path"].startswith("/article/")]
    assert articles and all(not r["auth"] for r in articles)


@pytest.mark.rss_live
def test_a4_cross_host_redirect_strips_feed_credentials(lab):
    # Transport behavior only: production authenticated gateways must forbid
    # redirects altogether (T18). This private-enabled engine is NOT SSRF proof.
    requests.post(lab.fixture_url + "/state", json={"version": 4}, timeout=5).raise_for_status()
    lab.client().create_feed("http://fixture:8000/redirect-other",
        username="synthetic-redirect-user", password="synthetic-redirect-password")
    state = requests.get(lab.fixture_url + "/state", timeout=5).json()
    redirects = [r for r in state["requests"] if r["path"] == "/redirect-other"]
    feeds = [r for r in state["requests"] if r["path"] == "/feed"]
    assert redirects and all(r["auth"] for r in redirects)
    assert feeds and all(not r["auth"] for r in feeds)
