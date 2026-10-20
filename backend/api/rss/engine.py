"""Fixed-account Miniflux adapter. Call outside DB transactions; caller owns CAS.

Socket timeouts are inactivity limits, not total deadlines or remote cancellation.
A supervisor must recover a stalled worker. Mutations are never blindly retried.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
import time
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import miniflux
import requests

MAX_ID = 2**63 - 1


class EngineError(Exception):
    """Safe to persist: no upstream bodies, URLs, headers or exception strings."""

    def __init__(self, code, *, retryable=False, unknown_result=False, retry_after=None):
        self.code = code
        self.retryable = retryable
        self.unknown_result = unknown_result
        self.retry_after = retry_after
        super().__init__(code)


def _id(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_ID:
        raise EngineError("invalid_identity")
    return value


def _url(value, *, feed=True):
    # Syntax gate only; engine/deployment must enforce DNS and redirect SSRF rules.
    try:
        if not isinstance(value, str) or (feed and len(value) > 1024) or any(ord(c) <= 32 for c in value) or "\\" in value:
            raise ValueError
        p = urlsplit(value)
        if p.scheme not in ({"https"} if feed else {"http", "https"}) or not p.hostname or p.username is not None or p.password is not None:
            raise ValueError
        p.port
        host = p.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        try:
            address = ip_address(host)
        except ValueError:
            if "." not in host or host.rsplit(".", 1)[-1].isdigit() or host.endswith((".local", ".localhost", ".internal", ".lan", ".arpa")):
                raise ValueError
        else:
            if not address.is_global:
                raise ValueError
        if feed:
            # Input, discovery and returned FeedDTOs must use the same URL
            # identity. Preserve business path/query bytes and nondefault ports.
            authority = ('[' + host + ']') if ':' in host else host
            authority += f':{p.port}' if p.port and p.port != 443 else ''
            canonical = urlunsplit(('https', authority, p.path, p.query, ''))
            if len(canonical) > 1024:
                raise ValueError
            return canonical
        return value
    except (ValueError, TypeError):
        raise EngineError("invalid_public_url") from None


def _text(value):
    if not isinstance(value, str):
        raise EngineError("invalid_response")
    return value


def _utc(value):
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        raise EngineError("invalid_response") from None


def _server_entry_url_rules(*, include_html=False):
    from api.rss.feed_policy import required_entry_url_block_rules
    return required_entry_url_block_rules(include_html=include_html)  # Pure, no ORM/settings read.


@dataclass(frozen=True)
class EngineConfig:
    engine_instance_uuid: str
    account_id: int
    base_url: str
    api_token: str = field(repr=False)
    read_timeout: float = 10.0
    control_timeout: float = 30.0
    connect_timeout: float = 5.0
    max_response_bytes: int = 8 * 1024 * 1024
    read_attempts: int = 3
    max_retry_delay: float = 10.0
    # Named, operator-approved (name, blocklist_rules, keeplist_rules) only.
    link_filters: tuple = ()
    # Server-owned immutable snapshot only, never a browser/API field. Mandatory
    # static restrictions are also merged in _policy and cannot be cleared.
    server_entry_url_block_rules: str = field(default_factory=_server_entry_url_rules)
    full_content_enabled: bool = True

    @classmethod
    def from_environment(cls):
        """Read deployment configuration and a mounted token, never HTTP payloads."""
        try:
            with open(os.environ["RSS_ENGINE_TOKEN_FILE"], encoding="utf-8") as handle:
                token = handle.read(65537).strip()
            if not token or len(token) > 65536:
                raise ValueError
            enabled = os.environ.get('RSS_FULL_CONTENT_ENABLED', '1')
            if enabled not in {'0', '1'}:
                raise ValueError
            return cls(os.environ["RSS_ENGINE_INSTANCE_UUID"], int(os.environ["RSS_ENGINE_ACCOUNT_ID"]),
                       os.environ["RSS_ENGINE_BASE_URL"], token, full_content_enabled=enabled == '1')
        except (OSError, KeyError, ValueError):
            raise EngineError("invalid_config") from None

    def __post_init__(self):
        try:
            UUID(str(self.engine_instance_uuid))
            p = urlsplit(self.base_url)
            if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or p.query or p.fragment:
                raise ValueError
            p.port
            _id(self.account_id)
            if not self.api_token or not 1 <= self.read_attempts <= 5 or self.max_response_bytes < 1:
                raise ValueError
            if min(self.read_timeout, self.control_timeout, self.connect_timeout, self.max_retry_delay) <= 0:
                raise ValueError
            rule = self.server_entry_url_block_rules
            if type(self.full_content_enabled) is not bool:
                raise ValueError
            if (not isinstance(rule, str) or len(rule) > 65536 or (rule and not rule.startswith('EntryURL='))
                    or any(c in rule for c in '\r\n\x00')):
                raise ValueError
        except (ValueError, TypeError):
            raise EngineError("invalid_config") from None


@dataclass(frozen=True)
class FeedDTO:
    engine_instance_uuid: str
    account_id: int
    id: int
    feed_url: str
    title: str
    crawler: bool
    disabled: bool

    def to_dict(self):
        return {**asdict(self), "account_id": str(self.account_id), "id": str(self.id)}


@dataclass(frozen=True)
class EntryDTO:
    engine_instance_uuid: str
    account_id: int
    feed_id: int
    id: int
    title: str
    url: str
    comments_url: str | None
    author: str
    content: str
    published_at: str | None
    created_at: str | None

    def to_dict(self):
        return {**asdict(self), "account_id": str(self.account_id), "feed_id": str(self.feed_id), "id": str(self.id)}


@dataclass(frozen=True)
class PolicyBinding:
    engine_instance_uuid: str
    account_id: int
    engine_feed_id: int
    policy_version: int
    desired_mode: str
    desired_enabled: bool
    link_filter_key: str | None = None


@dataclass(frozen=True)
class PolicyReceipt:
    feed: FeedDTO
    applied_policy_version: int

    def to_dict(self):
        return {"feed": self.feed.to_dict(), "applied_policy_version": str(self.applied_policy_version)}


def _retry_after(value):
    if not value:
        return None
    try:
        return max(0.0, float(int(value)))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class _BoundedSession(requests.Session):
    """Small SDK response-size patch, using Requests decoding and connection pools.

    All SDK entrances use this same session. No redirect (including API credential
    forwarding), ambient proxy, custom decompressor or alternate endpoint client.
    """

    def __init__(self, limit):
        super().__init__()
        self.trust_env = False
        self.limit = limit
        self.hooks["response"].append(self._bound)

    def request(self, method, url, **kwargs):
        kwargs.update(stream=True, allow_redirects=False)
        return super().request(method, url, **kwargs)

    def _bound(self, response, **kwargs):
        try:
            if response.status_code >= 300:
                status = response.status_code
                code = {401: "authentication", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(status, "upstream_http")
                raise EngineError(code, retryable=status == 429 or status >= 500,
                                  unknown_result=status >= 500,
                                  retry_after=_retry_after(response.headers.get("Retry-After")))
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > self.limit:
                    raise EngineError("response_too_large")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
            return response
        finally:
            response.close()


class EngineAdapter:
    """One instance per worker slot (Requests sessions are not thread safe).

    After unknown_result, durable operations must reconcile or block; absence in
    get_feeds alone cannot prove a timed-out remote create has stopped. Never call
    create_feed/refetch_entry again automatically for an unknown operation.
    """
    def __init__(self, config: EngineConfig):
        self.config = config  # deployment-created config; never built from request data
        self._session = _BoundedSession(config.max_response_bytes)
        self._client = miniflux.Client(config.base_url, api_key=config.api_token,
                                      session=self._session, timeout=(config.connect_timeout, config.read_timeout))
        self._identity_checked = False

    def close(self):
        self._session.close()

    def _call(self, fn, *, control=False):
        self._client._timeout = (self.config.connect_timeout, self.config.control_timeout if control else self.config.read_timeout)
        for attempt in range(1 if control else self.config.read_attempts):
            try:
                return fn()
            except EngineError as exc:
                error = EngineError(exc.code, retryable=exc.retryable,
                                    unknown_result=control and (exc.unknown_result or exc.code in {"response_too_large", "invalid_response"}),
                                    retry_after=exc.retry_after)
            except requests.exceptions.JSONDecodeError:
                error = EngineError("invalid_response", unknown_result=control)
            except requests.RequestException:
                error = EngineError("network", retryable=True, unknown_result=control)
            except (ValueError, KeyError, TypeError, miniflux.ClientError):
                error = EngineError("invalid_response", unknown_result=control)
            if control or not error.retryable or attempt + 1 >= self.config.read_attempts:
                raise error from None
            delay = error.retry_after if error.retry_after is not None else min(2**attempt, self.config.max_retry_delay)
            if delay > self.config.max_retry_delay:
                raise error from None  # defer to durable next_attempt; never retry before Retry-After
            time.sleep(delay)

    def _identity(self):
        if not self._identity_checked:
            me = self._call(self._client.me)
            if not isinstance(me, dict) or me.get("id") != self.config.account_id or me.get("is_admin") is not False:
                raise EngineError("account_mismatch")
            self._identity_checked = True

    def _owned(self, row):
        if not isinstance(row, dict) or _id(row.get("user_id")) != self.config.account_id:
            raise EngineError("account_mismatch")

    def _feed(self, row):
        self._owned(row)
        if type(row.get("crawler")) is not bool or type(row.get("disabled")) is not bool:
            raise EngineError("invalid_response")
        return FeedDTO(str(self.config.engine_instance_uuid), self.config.account_id, _id(row.get("id")),
                       _url(row.get("feed_url")), _text(row.get("title")), row["crawler"], row["disabled"])

    def _entry(self, row):
        self._owned(row)
        comments = row.get("comments_url")
        if comments:
            try:
                comments = _url(comments, feed=False)
            except EngineError:
                comments = None
        return EntryDTO(str(self.config.engine_instance_uuid), self.config.account_id,
                        _id(row.get("feed_id")), _id(row.get("id")), _text(row.get("title")),
                        _url(row.get("url"), feed=False), comments or None, _text(row.get("author", "")),
                        _text(row.get("content")), _utc(row.get("published_at")), _utc(row.get("created_at")))

    def discover(self, url):
        self._identity()
        rows = self._call(lambda: self._client.discover(_url(url)), control=True)
        if not isinstance(rows, list):
            raise EngineError("invalid_response")
        if any(not isinstance(row, dict) for row in rows):
            raise EngineError("invalid_response")
        return [{"url": _url(row.get("url")), "title": _text(row.get("title", ""))} for row in rows]

    def list_feeds(self):
        self._identity()
        rows = self._call(self._client.get_feeds)
        if not isinstance(rows, list):
            raise EngineError("invalid_response")
        return [self._feed(row) for row in rows]

    def get_feed(self, feed_id):
        self._identity()
        feed_id = _id(feed_id)
        result = self._feed(self._call(lambda: self._client.get_feed(feed_id)))
        if result.id != feed_id:
            raise EngineError("identity_mismatch")
        return result

    def create_feed(self, canonical_url, *, desired_mode="feed", disabled=False):
        # 2.3.3 processes initial entries even when disabled=True on creation.
        if desired_mode == 'full_content' and not self.config.full_content_enabled:
            raise EngineError('full_content_disabled')
        canonical_url = _url(canonical_url)
        policy = self._policy(desired_mode, disabled, None)
        self._identity()
        # Also handles a replay following process death before its result was saved.
        matches = [feed for feed in self.list_feeds() if feed.feed_url == canonical_url]
        if len(matches) > 1:
            raise EngineError("identity_conflict")
        if matches:
            return self._confirm_policy(matches[0].id, policy)
        created = False
        try:
            feed_id = self._call(lambda: self._client.create_feed(canonical_url, **policy), control=True)
            created = True
            return self._confirm_policy(_id(feed_id), policy)
        except EngineError as exc:
            if not (created or exc.unknown_result or exc.code in {"invalid_response", "network"}):
                raise
            try:
                matches = [feed for feed in self.list_feeds() if feed.feed_url == canonical_url]
                if len(matches) == 1:
                    return self._confirm_policy(matches[0].id, policy)
            except EngineError:
                pass
            raise EngineError("create_unknown", unknown_result=True) from None

    def _policy(self, mode, disabled, filter_key):
        if mode not in {"feed", "full_content"} or type(disabled) is not bool:
            raise EngineError("invalid_policy")
        if mode == 'full_content' and not disabled and not self.config.full_content_enabled:
            raise EngineError('full_content_disabled')
        filters = {key: (block, keep) for key, block, keep in self.config.link_filters}
        if filter_key is not None and filter_key not in filters:
            raise EngineError("invalid_policy")
        block, keep = filters.get(filter_key, ("", ""))
        rules = list(dict.fromkeys(filter(None, (_server_entry_url_rules(include_html=mode == 'full_content'),
                                                 self.config.server_entry_url_block_rules))))
        return dict(crawler=mode == "full_content", disabled=disabled, blocklist_rules=block, keeplist_rules=keep,
                    block_filter_entry_rules='\n'.join(rules))

    def _confirm_policy(self, feed_id, fields):
        row = self._call(lambda: self._client.get_feed(feed_id))
        feed = self._feed(row)
        if feed.id != feed_id or any(row.get(key) != value for key, value in fields.items()):
            raise EngineError("policy_unconfirmed", unknown_result=True)
        return feed

    def _update(self, feed_id, fields):
        self.get_feed(feed_id)
        try:
            self._call(lambda: self._client.update_feed(feed_id, **fields), control=True)
        except EngineError as exc:
            if not exc.unknown_result:
                raise
        try:
            return self._confirm_policy(feed_id, fields)
        except EngineError:
            raise EngineError("policy_unconfirmed", unknown_result=True) from None

    def set_enabled(self, feed_id, *, disabled):
        if type(disabled) is not bool:
            raise EngineError("invalid_policy")
        if not disabled and not self.config.full_content_enabled and self.get_feed(feed_id).crawler:
            raise EngineError('full_content_disabled')
        return self._update(_id(feed_id), {"disabled": disabled})

    def update_feed_policy(self, binding, expected_policy_version):
        if str(binding.engine_instance_uuid) != str(self.config.engine_instance_uuid) or str(binding.account_id) != str(self.config.account_id):
            raise EngineError("account_mismatch")
        if type(expected_policy_version) is not int or expected_policy_version < 1 or binding.policy_version != expected_policy_version:
            raise EngineError("stale_policy")
        if type(binding.desired_enabled) is not bool:
            raise EngineError("invalid_policy")
        fields = self._policy(binding.desired_mode, not binding.desired_enabled, getattr(binding, "link_filter_key", None))
        feed = self._update(_id(binding.engine_feed_id), fields)
        return PolicyReceipt(feed, expected_policy_version)  # caller must CAS current policy and lease

    def refresh_feed(self, feed_id):
        feed = self.get_feed(feed_id)
        if feed.crawler and not self.config.full_content_enabled:
            raise EngineError('full_content_disabled')
        self._call(lambda: self._client.refresh_feed(feed_id), control=True)

    def read_upper_bound(self):
        self._identity()
        rows = self._rows(self._call(lambda: self._client.get_entries(order="id", direction="desc", limit=1)))
        if len(rows) > 1:
            raise EngineError("invalid_page")
        if not rows:
            return 0
        self._owned(rows[0])
        return _id(rows[0].get("id"))

    @staticmethod
    def _rows(response):
        if not isinstance(response, dict) or not isinstance(response.get("entries"), list):
            raise EngineError("invalid_response")
        return response["entries"]

    def list_entries(self, lower, upper, limit=100):
        _id(lower, zero=True)
        _id(upper, zero=True)
        if upper == MAX_ID:
            raise EngineError("upper_bound_overflow")
        if lower > upper or type(limit) is not int or not 1 <= limit <= 1000:
            raise EngineError("invalid_page")
        self._identity()
        rows = self._rows(self._call(lambda: self._client.get_entries(order="id", direction="asc",
                         after_entry_id=lower, before_entry_id=upper + 1, limit=limit)))
        if len(rows) > limit:
            raise EngineError("invalid_page")
        result = [self._entry(row) for row in rows]  # never yield a partial page
        ids = [row.id for row in result]
        if ids != sorted(set(ids)) or any(not lower < value <= upper for value in ids):
            raise EngineError("invalid_page")
        return result

    def get_entry(self, entry_id):
        self._identity()
        entry_id = _id(entry_id)
        entry = self._entry(self._call(lambda: self._client.get_entry(entry_id)))
        if entry.id != entry_id:
            raise EngineError("identity_mismatch")
        return entry

    def refetch_entry(self, entry_id):
        if not self.config.full_content_enabled:
            raise EngineError('full_content_disabled')
        before = self.get_entry(entry_id)

        def persist():
            response = self._session.get(self._client._get_endpoint(f"/entries/{entry_id}/fetch-content"),
                                         params={"update_content": "true"}, timeout=self._client._timeout)
            if response.status_code != 200:
                raise EngineError("invalid_response", unknown_result=True)
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
                raise EngineError("invalid_response", unknown_result=True)
            return payload["content"]

        try:
            content = self._call(persist, control=True)
        except EngineError as exc:
            if exc.unknown_result:
                try:
                    self.get_entry(entry_id)  # reconcile; cannot prove expected persisted value
                except EngineError:
                    pass
                raise EngineError("refetch_unknown", unknown_result=True) from None
            raise
        try:
            after = self.get_entry(entry_id)
        except EngineError:
            raise EngineError("refetch_unknown", unknown_result=True) from None
        if after.feed_id != before.feed_id or after.content != content:
            raise EngineError("refetch_unconfirmed", unknown_result=True)
        return after
