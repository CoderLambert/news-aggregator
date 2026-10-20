"""SDK-over-real-local-HTTP tests; no Django settings, database or external engine."""
import gzip
import json
import threading
import time
import tracemalloc
from collections import defaultdict, deque
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from api.rss.engine import EngineAdapter, EngineConfig, EngineError, MAX_ID, PolicyBinding
from api.rss.feed_policy import required_entry_url_block_rules

INSTANCE = "be22a55a-11c1-4ae4-9038-c919ec75aa42"
SECRET = "never-print-api-secret"


def feed(**kw):
    return dict(id=7, user_id=3, feed_url="https://publisher.example/feed", title="Feed",
                crawler=False, disabled=False, blocklist_rules="", keeplist_rules="",
                block_filter_entry_rules=required_entry_url_block_rules(),
                username="private-user", password="private-pass", **kw)


def entry(entry_id=12):
    return dict(id=entry_id, user_id=3, feed_id=7, title="Article", url="https://publisher.example/article",
                comments_url="http://127.0.0.1/internal", author="Author", content="old content",
                published_at="2026-10-16T12:00:00+08:00", created_at="2026-10-16T04:01:00Z",
                enclosures=[{"url": "http://internal/media"}], hash="not-a-body-hash")


@pytest.fixture
def server():
    routes, calls = defaultdict(deque), []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        do_POST = do_PUT = do_GET

        def handle_request(self):
            size = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(size)
            calls.append((self.command, self.path, json.loads(body) if body else None, self.headers.get("X-Auth-Token")))
            path = urlsplit(self.path).path
            if path == "/v1/me" and not routes[path]:
                result = (200, {"id": 3, "is_admin": False}, {})
            else:
                assert routes[path], (self.command, path)
                action = routes[path].popleft()
                result = action(self) if callable(action) else action
            status, payload, headers = result
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            try:
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # BaseServer.serve_forever defaults to a 0.5s shutdown poll. This fixture
    # starts a fresh server for every parameterized case; a short poll retains
    # the real HTTP lifecycle while avoiding up to 0.5s per teardown.
    thread = threading.Thread(
        target=httpd.serve_forever,
        kwargs={"poll_interval": 0.02},
        daemon=True,
    )
    thread.start()
    config = EngineConfig(INSTANCE, 3, f"http://127.0.0.1:{httpd.server_port}", SECRET,
                          read_timeout=.1, control_timeout=.1, read_attempts=1, full_content_enabled=True)
    yield routes, calls, config
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def ok(payload):
    return 200, payload, {}


def assert_error(code, fn, *, unknown=None):
    with pytest.raises(EngineError) as caught:
        fn()
    assert caught.value.code == code
    if unknown is not None:
        assert caught.value.unknown_result is unknown
    assert SECRET not in str(caught.value)
    return caught.value


def test_dto_whitelist_identity_utc_and_big_json_ids(server):
    routes, calls, config = server
    routes["/v1/feeds/7"].append(ok(feed()))
    routes[f"/v1/entries/{MAX_ID}"].append(ok(entry(MAX_ID)))
    adapter = EngineAdapter(config)
    output = adapter.get_feed(7).to_dict()
    assert "password" not in output and "username" not in output
    output = adapter.get_entry(MAX_ID).to_dict()
    assert output["id"] == str(MAX_ID) and output["account_id"] == "3"
    assert output["published_at"] == "2026-10-16T04:00:00Z"
    assert output["comments_url"] is None and "enclosures" not in output and "hash" not in output
    assert all(call[3] == SECRET for call in calls)
    assert SECRET not in repr(config)


@pytest.mark.parametrize("me", [{"id": 4, "is_admin": False}, {"id": 3, "is_admin": True}])
def test_fixed_nonadmin_account(server, me):
    routes, calls, config = server
    routes["/v1/me"].append(ok(me))
    assert_error("account_mismatch", lambda: EngineAdapter(config).list_feeds())
    assert len(calls) == 1


def test_wrong_row_account_or_identity(server):
    routes, _, config = server
    row = entry()
    row["user_id"] = 99
    routes["/v1/entries/12"].append(ok(row))
    assert_error("account_mismatch", lambda: EngineAdapter(config).get_entry(12))
    routes["/v1/entries/12"].append(ok(entry(13)))
    assert_error("identity_mismatch", lambda: EngineAdapter(config).get_entry(12))


def test_create_ambiguous_result_reconciles_without_second_post(server):
    routes, calls, config = server
    routes["/v1/feeds"].extend([ok([]), (503, b"secret upstream details", {}), ok([feed()])])
    routes["/v1/feeds/7"].append(ok(feed()))
    result = EngineAdapter(config).create_feed("https://publisher.example/feed")
    assert result.id == 7
    assert [c[0] for c in calls].count("POST") == 1


def test_create_unknown_remains_unknown_when_absent(server):
    routes, calls, config = server
    routes["/v1/feeds"].extend([ok([]), (503, b"secret", {}), ok([])])
    assert_error("create_unknown", lambda: EngineAdapter(config).create_feed("https://publisher.example/feed"), unknown=True)
    assert [c[0] for c in calls].count("POST") == 1


def test_replay_does_not_create_again(server):
    routes, calls, config = server
    routes["/v1/feeds"].append(ok([feed()]))
    routes["/v1/feeds/7"].append(ok(feed()))
    assert EngineAdapter(config).create_feed("https://publisher.example/feed").id == 7
    assert not any(c[0] == "POST" for c in calls)


def test_policy_get_verification_and_local_version_receipt(server):
    routes, calls, config = server
    rules = required_entry_url_block_rules(include_html=True) + '\n' + required_entry_url_block_rules()
    updated = {**feed(), "crawler": True, "disabled": True, 'block_filter_entry_rules': rules}
    routes["/v1/feeds/7"].extend([ok(feed()), (503, b"unknown write", {}), ok(updated)])
    binding = PolicyBinding(INSTANCE, 3, 7, 9, "full_content", False)
    result = EngineAdapter(config).update_feed_policy(binding, 9)
    assert result.applied_policy_version == 9 and result.feed.disabled
    assert [c[0] for c in calls] == ["GET", "GET", "PUT", "GET"]
    assert calls[2][2] == dict(crawler=True, disabled=True, blocklist_rules="", keeplist_rules="",
        block_filter_entry_rules=rules)


def test_policy_unconfirmed_and_stale(server):
    routes, calls, config = server
    routes["/v1/feeds/7"].extend([ok(feed()), (201, feed(), {}), ok(feed())])
    binding = PolicyBinding(INSTANCE, 3, 7, 9, "full_content", True)
    adapter = EngineAdapter(config)
    assert_error("stale_policy", lambda: adapter.update_feed_policy(binding, 8))
    assert not calls
    assert_error("policy_unconfirmed", lambda: adapter.update_feed_policy(binding, 9), unknown=True)


def test_refetch_persists_and_gets_independently(server):
    routes, calls, config = server
    routes["/v1/entries/12"].extend([ok(entry()), ok({**entry(), "content": "new content"})])
    routes["/v1/entries/12/fetch-content"].append(ok({"content": "new content"}))
    assert EngineAdapter(config).refetch_entry(12).content == "new content"
    assert calls[2][1] == "/v1/entries/12/fetch-content?update_content=true"
    assert calls[3][1] == "/v1/entries/12"


def test_refetch_nonpersistent_result_and_unknown(server):
    routes, _, config = server
    routes["/v1/entries/12"].extend([ok(entry()), ok(entry())])
    routes["/v1/entries/12/fetch-content"].append(ok({"content": "new content"}))
    assert_error("refetch_unconfirmed", lambda: EngineAdapter(config).refetch_entry(12), unknown=True)
    routes["/v1/entries/12"].extend([ok(entry()), ok(entry())])
    routes["/v1/entries/12/fetch-content"].append((503, b"secret", {}))
    assert_error("refetch_unknown", lambda: EngineAdapter(config).refetch_entry(12), unknown=True)


def test_keyset_exclusive_bounds_and_empty_upper(server):
    routes, calls, config = server
    routes["/v1/entries"].extend([ok({"entries": []}), ok({"entries": [entry(12)]})])
    adapter = EngineAdapter(config)
    assert adapter.read_upper_bound() == 0
    assert adapter.list_entries(11, 12, 1)[0].id == 12
    assert parse_qs(urlsplit(calls[-1][1]).query) == dict(order=["id"], direction=["asc"], after_entry_id=["11"], before_entry_id=["13"], limit=["1"])
    assert_error("upper_bound_overflow", lambda: adapter.list_entries(0, MAX_ID))


@pytest.mark.parametrize("ids", [[12, 11], [12, 12], [10], [14]])
def test_page_invalid_never_returns_partial(server, ids):
    routes, _, config = server
    routes["/v1/entries"].append(ok({"entries": [entry(i) for i in ids]}))
    assert_error("invalid_page", lambda: EngineAdapter(config).list_entries(10, 13))


@pytest.mark.parametrize("method,path,payload", [
    ("list_feeds", "/v1/feeds", [feed()]),
    ("read_upper_bound", "/v1/entries", {"entries": []}),
    ("discover", "/v1/discover", []),
    ("get_entry", "/v1/entries/12", entry()),
    ("get_feed", "/v1/feeds/7", feed()),
])
def test_all_sdk_entrances_bounded_and_recover(server, method, path, payload):
    routes, _, config = server
    routes[path].extend([ok(b"x" * 262144), ok(payload)])
    adapter = EngineAdapter(replace(config, max_response_bytes=1024))
    args = {"discover": ("https://publisher.example/",), "get_entry": (12,), "get_feed": (7,)}.get(method, ())
    assert_error("response_too_large", lambda: getattr(adapter, method)(*args))
    getattr(adapter, method)(*args)


def test_large_compressed_response_memory_bounded(server):
    routes, _, config = server
    compressed = gzip.compress(b"x" * (32 * 1024 * 1024))
    routes["/v1/feeds"].append((200, compressed, {"Content-Encoding": "gzip"}))
    adapter = EngineAdapter(replace(config, max_response_bytes=256 * 1024))
    tracemalloc.start()
    try:
        assert_error("response_too_large", adapter.list_feeds)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024  # actual decompressed stream is 32 MiB


def test_socket_timeout_releases_slot_for_next_call(server):
    routes, _, config = server

    def stall(_):
        time.sleep(.3)
        return ok([])

    routes["/v1/feeds"].extend([stall, ok([])])
    adapter = EngineAdapter(config)
    assert_error("network", adapter.list_feeds)
    assert adapter.list_feeds() == []


def test_retry_after_finite_reads_and_no_redirect_or_error_leak(server):
    routes, calls, config = server
    routes["/v1/feeds"].extend([(503, b"secret", {"Retry-After": "0"}), ok([])])
    adapter = EngineAdapter(replace(config, read_attempts=2))
    assert adapter.list_feeds() == []
    routes["/v1/feeds"].append((429, b"secret", {"Retry-After": "90"}))
    error = assert_error("rate_limited", adapter.list_feeds)
    assert error.retry_after == 90
    routes["/v1/feeds"].append((302, b"secret", {"Location": config.base_url + "/leak"}))
    assert_error("upstream_http", adapter.list_feeds)
    assert not any("/leak" in c[1] for c in calls)


def test_mutating_entrances_and_identity_are_bounded(server):
    routes, calls, config = server
    routes["/v1/me"].append(ok(b"x" * 2048))
    adapter = EngineAdapter(replace(config, max_response_bytes=1024))
    assert_error("response_too_large", adapter.list_feeds)
    routes["/v1/feeds/7"].append(ok(feed()))
    routes["/v1/feeds/7/refresh"].append(ok(b"x" * 2048))
    assert_error("response_too_large", lambda: adapter.refresh_feed(7), unknown=True)
    routes["/v1/feeds/7"].extend([ok(feed()), ok(b"x" * 2048), ok({**feed(), "disabled": True})])
    assert adapter.set_enabled(7, disabled=True).disabled
    routes["/v1/feeds"].extend([ok([]), ok(b"x" * 2048), ok([feed()])])
    routes["/v1/feeds/7"].append(ok(feed()))
    assert adapter.create_feed("https://publisher.example/feed").id == 7
    routes["/v1/entries/12"].extend([ok(entry()), ok(entry())])
    routes["/v1/entries/12/fetch-content"].append(ok(b"x" * 2048))
    assert_error("refetch_unknown", lambda: adapter.refetch_entry(12), unknown=True)


def test_environment_config_file_and_safe_failure(tmp_path, monkeypatch):
    token = tmp_path / "secret"
    token.write_text(SECRET + "\n")
    for name, value in dict(RSS_ENGINE_INSTANCE_UUID=INSTANCE, RSS_ENGINE_ACCOUNT_ID="3",
                            RSS_ENGINE_BASE_URL="http://miniflux:8080", RSS_ENGINE_TOKEN_FILE=str(token)).items():
        monkeypatch.setenv(name, value)
    config = EngineConfig.from_environment()
    assert config.account_id == 3 and config.api_token == SECRET
    token.unlink()
    assert_error("invalid_config", EngineConfig.from_environment)


@pytest.mark.parametrize("url", ["http://publisher.example/feed", "https://user:secret@publisher.example/feed",
                                 "https://127.0.0.1/feed", "https://169.254.169.254/feed", "https://127.1/feed",
                                 "file:///etc/passwd", "https://publisher.example/\nfeed"])
def test_malicious_input_never_reaches_engine(server, url):
    _, calls, config = server
    assert_error("invalid_public_url", lambda: EngineAdapter(config).create_feed(url))
    assert not calls


def test_get_failure_after_successful_mutation_is_unknown(server):
    routes, calls, config = server
    routes["/v1/feeds"].extend([ok([]), (201, {"feed_id": 7}, {}), ok([])])
    routes["/v1/feeds/7"].append((404, b"not yet visible", {}))
    assert_error("create_unknown", lambda: EngineAdapter(config).create_feed("https://publisher.example/feed"), unknown=True)
    routes["/v1/entries/12"].extend([ok(entry()), (503, b"secret", {})])
    routes["/v1/entries/12/fetch-content"].append(ok({"content": "new content"}))
    assert_error("refetch_unknown", lambda: EngineAdapter(config).refetch_entry(12), unknown=True)


def test_approved_filter_key_only(server):
    routes, calls, config = server
    adapter = EngineAdapter(replace(config, link_filters=(("approved", "sponsor", "article"),)))
    binding = PolicyBinding(INSTANCE, 3, 7, 1, "feed", True, "arbitrary-code")
    assert_error("invalid_policy", lambda: adapter.update_feed_policy(binding, 1))
    assert not calls
    expected = {**feed(), "blocklist_rules": "sponsor", "keeplist_rules": "article"}
    routes["/v1/feeds/7"].extend([ok(feed()), (201, expected, {}), ok(expected)])
    adapter.update_feed_policy(replace(binding, link_filter_key="approved"), 1)
    assert calls[2][2]["keeplist_rules"] == "article"


def test_create_socket_timeout_still_reconciles_without_reposting(server):
    routes, calls, config = server

    def delayed_ack(_):
        time.sleep(.3)
        return 201, {"feed_id": 7}, {}

    routes["/v1/feeds"].extend([ok([]), delayed_ack, ok([feed()])])
    routes["/v1/feeds/7"].append(ok(feed()))
    assert EngineAdapter(config).create_feed("https://publisher.example/feed").id == 7
    assert [c[0] for c in calls].count("POST") == 1


def test_gate_off_blocks_full_create_even_disabled_and_refetch_before_http(server):
    routes, calls, config = server
    adapter = EngineAdapter(replace(config, full_content_enabled=False))
    for disabled in (False, True):
        assert_error('full_content_disabled', lambda: adapter.create_feed(
            'https://publisher.example/feed', desired_mode='full_content', disabled=disabled))
    assert_error('full_content_disabled', lambda: adapter.refetch_entry(12))
    assert_error('full_content_disabled', lambda: adapter.update_feed_policy(
        PolicyBinding(INSTANCE, 3, 7, 1, 'full_content', True), 1))
    assert not calls


def test_gate_off_reads_current_crawler_before_refresh_or_reenable(server):
    routes, calls, config = server
    adapter = EngineAdapter(replace(config, full_content_enabled=False))
    routes['/v1/feeds/7'].extend([ok({**feed(), 'crawler': True})] * 2)
    assert_error('full_content_disabled', lambda: adapter.refresh_feed(7))
    assert_error('full_content_disabled', lambda: adapter.set_enabled(7, disabled=False))
    assert all(call[0] == 'GET' for call in calls)


def test_gate_off_still_allows_disable_without_clearing_historical_mode(server):
    routes, calls, config = server
    adapter = EngineAdapter(replace(config, full_content_enabled=False))
    expected = {**feed(), 'crawler': True, 'disabled': True}
    routes['/v1/feeds/7'].extend([ok({**feed(), 'crawler': True}), ok(expected), ok(expected)])
    assert adapter.set_enabled(7, disabled=True).disabled
    assert calls[2][2] == {'disabled': True}


def test_existing_feed_missing_required_rule_is_unknown_and_never_recreated(server):
    routes, calls, config = server
    routes['/v1/feeds'].append(ok([feed()]))
    routes['/v1/feeds/7'].append(ok({**feed(), 'block_filter_entry_rules': ''}))
    assert_error('policy_unconfirmed', lambda: EngineAdapter(config).create_feed(
        'https://publisher.example/feed'), unknown=True)
    assert not any(call[0] == 'POST' for call in calls)


def test_created_feed_unproven_rule_never_reposts_after_read_only_reconcile(server):
    routes, calls, config = server
    missing = {**feed(), 'block_filter_entry_rules': ''}
    routes['/v1/feeds'].extend([ok([]), (201, {'feed_id': 7}, {}), ok([missing])])
    routes['/v1/feeds/7'].extend([ok(missing), ok(missing)])
    assert_error('create_unknown', lambda: EngineAdapter(config).create_feed(
        'https://publisher.example/feed'), unknown=True)
    assert sum(call[0] == 'POST' for call in calls) == 1


@pytest.mark.parametrize('value', ['', 'true', 'false', 'yes', '2', ' 1'])
def test_full_content_environment_gate_is_strict(server, monkeypatch, tmp_path, value):
    _, _, config = server
    token = tmp_path / 'synthetic-token'
    token.write_text(SECRET)
    for name, setting in dict(RSS_ENGINE_INSTANCE_UUID=INSTANCE, RSS_ENGINE_ACCOUNT_ID='3',
        RSS_ENGINE_BASE_URL=config.base_url, RSS_ENGINE_TOKEN_FILE=str(token), RSS_FULL_CONTENT_ENABLED=value).items():
        monkeypatch.setenv(name, setting)
    assert_error('invalid_config', EngineConfig.from_environment)


def test_malformed_response_is_safe_failure_not_empty_page(server):
    routes, _, config = server
    routes["/v1/entries"].append(ok(b"{incomplete-" + SECRET.encode()))
    assert_error("invalid_response", lambda: EngineAdapter(config).read_upper_bound())


def test_http_article_and_comments_preserve_long_urls_for_business_rejection(server):
    routes, _, config = server
    row = {**entry(), "url": "http://publisher.example/" + "a" * 1200,
           "comments_url": "http://forum.example/thread/12"}
    routes["/v1/entries"].append(ok({"entries": [row]}))
    result = EngineAdapter(config).list_entries(11, 12)[0]
    assert result.url == row["url"]  # T09 owns News.url 500-character rejection
    assert result.comments_url == row["comments_url"]


@pytest.mark.parametrize("status,code", [(401, "authentication"), (403, "forbidden"), (500, "upstream_http")])
def test_mutation_http_errors_classify_unknown_and_hide_body(server, status, code):
    routes, calls, config = server
    routes["/v1/feeds/7"].append(ok(feed()))
    routes["/v1/feeds/7/refresh"].append((status, SECRET.encode(), {}))
    assert_error(code, lambda: EngineAdapter(config).refresh_feed(7), unknown=status >= 500)
    assert [call[0] for call in calls].count("PUT") == 1


@pytest.mark.parametrize('value,expected', [(None, True), ('0', False), ('1', True)])
def test_full_content_defaults_on_with_explicit_operator_opt_out(monkeypatch, tmp_path, value, expected):
    token = tmp_path / 'synthetic-token'
    token.write_text(SECRET)
    for name, setting in dict(RSS_ENGINE_INSTANCE_UUID=INSTANCE, RSS_ENGINE_ACCOUNT_ID='3',
        RSS_ENGINE_BASE_URL='http://127.0.0.1:8080', RSS_ENGINE_TOKEN_FILE=str(token)).items():
        monkeypatch.setenv(name, setting)
    monkeypatch.delenv('RSS_FULL_CONTENT_ENABLED', raising=False)
    if value is not None:
        monkeypatch.setenv('RSS_FULL_CONTENT_ENABLED', value)
    assert EngineConfig.from_environment().full_content_enabled is expected
    assert EngineConfig(INSTANCE, 3, 'http://127.0.0.1:8080', SECRET).full_content_enabled is True


def test_frozen_initialization_date_is_in_create_and_future_policy_writes(server):
    routes, calls, config = server
    adapter = EngineAdapter(config)
    expected = adapter._policy('feed', False, None, '2026-10-14')
    row = {**feed(), **expected}
    routes['/v1/feeds'].extend([(200, [], {}), (201, {'feed_id': 7}, {})])
    routes['/v1/feeds/7'].extend([(200, row, {}), (200, row, {}), (204, b'', {}), (200, row, {})])
    adapter.create_feed('https://publisher.example/feed', published_since='2026-10-14')
    adapter.update_feed_policy(PolicyBinding(INSTANCE, 3, 7, 1, 'feed', True,
        published_since='2026-10-14'), 1)
    mutations = [body for method, _, body, _ in calls if method in {'POST', 'PUT'}]
    assert len(mutations) == 2
    assert all('EntryDate=before:2026-10-14' in row['block_filter_entry_rules'] for row in mutations)
    assert all(required_entry_url_block_rules() in row['block_filter_entry_rules'] for row in mutations)
    for invalid in ('2026-10-14T12:00:00Z', '2026-13-01', '2026-10-14\nEntryURL=.*'):
        assert_error('invalid_policy', lambda: adapter._policy('feed', False, None, invalid))
