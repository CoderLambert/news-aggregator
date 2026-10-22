"""Ephemeral owner/task/generation transport. Never an authority for DB commits.

Redis time bounds stale authorization even if a worker/controller disappears.
All changes and replay reads are atomic; XREAD is only a wakeup, not a consumer
queue. No source, keys or exception details are stored in this channel.
"""
from functools import lru_cache
import ipaddress
import json
import re
import threading
import time
from urllib.parse import urlsplit

from django.conf import settings
from redis import Redis

ACTIVE_TTL = 90
TERMINAL_TTL = 300
MAX_EVENTS = 2048
MAX_BUFFER = 256 * 1024
CURSOR = re.compile(r'^\d{1,20}-\d{1,20}$')


class ChannelUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('translation_channel_unavailable')


# Operations use a single hash and stream in the same Redis hash slot. The token
# is never included in public events. TTL never renews the authorization deadline.
_MUTATE = r'''
local h, s = KEYS[1], KEYS[2]
local op, token = ARGV[1], ARGV[2]
local now = redis.call('TIME'); now = tonumber(now[1])*1000 + tonumber(now[2])/1000
local exists = redis.call('EXISTS', h) == 1
local state = redis.call('HGET', h, 'status')
local terminal = state and state ~= 'running'
if op == 'init' then
  if exists then return 0 end
  redis.call('HSET', h, 'token', token, 'status', 'running', 'text', '', 'checked', now)
elseif op == 'cancel' then
  if terminal then return 0 end
else
  if not exists or terminal or redis.call('HGET', h, 'token') ~= token then return 0 end
  if op ~= 'terminal' and now-tonumber(redis.call('HGET', h, 'checked') or '0') > 2000 then return 0 end
end
if op == 'check' then
  redis.call('HSET', h, 'checked', now)
  redis.call('EXPIRE', h, 90); redis.call('EXPIRE', s, 90)
  return 1
end
local kind, body = 'snapshot', cjson.decode(ARGV[3])
local text = redis.call('HGET', h, 'text') or ''
if op == 'delta' then
  text = text .. body.delta
  if string.len(text) > tonumber(ARGV[4]) then return 0 end
  kind = 'delta'
elseif op == 'replace' then text = body.text
elseif op == 'terminal' or op == 'cancel' then
  kind = 'terminal'
  redis.call('HSET', h, 'status', body.status, 'result', cjson.encode(body.result), 'error_code', body.error_code)
  -- Incomplete previews must disappear; a completed result lives in the DB.
  text = ''
end
local prev = redis.call('HGET', h, 'cursor') or '0-0'
body.previous_cursor = prev
local id = redis.call('XADD', s, 'MAXLEN', '=', 2048, '*', 'kind', kind, 'body', cjson.encode(body))
redis.call('HSET', h, 'text', text, 'cursor', id)
local ttl = kind == 'terminal' and 300 or 90
redis.call('EXPIRE', h, ttl); redis.call('EXPIRE', s, ttl)
return id
'''
_READ = r'''
local h, s = KEYS[1], KEYS[2]
if redis.call('EXISTS', h) == 0 then return '' end
local now = redis.call('TIME'); now = tonumber(now[1])*1000 + tonumber(now[2])/1000
local status = redis.call('HGET', h, 'status')
if status == 'running' and now-tonumber(redis.call('HGET', h, 'checked') or '0') > 2000 then return '' end
local cursor = redis.call('HGET', h, 'cursor')
local first = redis.call('XRANGE', s, '-', '+', 'COUNT', 1)
local function parts(id) local a,b=string.match(id, '^(%d+)%-(%d+)$'); return tonumber(a),tonumber(b) end
local function less(a,b) local x,y=parts(a); local u,v=parts(b); return x<u or (x==u and y<v) end
local requested = ARGV[1]
if status ~= 'running' or requested == '' or #first == 0 or less(requested, first[1][1]) or less(cursor, requested) then
  return cjson.encode({snapshot=true, cursor=cursor, text=redis.call('HGET', h, 'text'), status=status,
    result=redis.call('HGET', h, 'result') or 'null', error_code=redis.call('HGET', h, 'error_code') or ''})
end
return cjson.encode({snapshot=false, status=status, events=redis.call('XRANGE', s, '('..requested, '+', 'COUNT', 128)})
'''


@lru_cache(maxsize=4)
def _client(url):
    try:
        parsed = urlsplit(url)
        local = parsed.hostname == 'localhost'
        if not local:
            try:
                local = ipaddress.ip_address(parsed.hostname).is_loopback
            except (ValueError, TypeError):
                pass
        if (parsed.scheme not in {'redis', 'rediss'} or not parsed.password
                or (not local and parsed.scheme != 'rediss') or parsed.query):
            raise ValueError
        # Explicit RESP2, no automatic retry of an ambiguous XADD/mutation.
        from redis.retry import Retry
        from redis.backoff import NoBackoff
        return Redis.from_url(url, protocol=2, decode_responses=True,
                              socket_connect_timeout=0.3, socket_timeout=1.5,
                              retry=Retry(NoBackoff(), 0), max_connections=64)
    except Exception:
        raise ChannelUnavailable() from None


def client():
    return _client(getattr(settings, 'TRANSLATION_REDIS_URL', ''))


def available():
    try:
        client().ping()
    except Exception:
        raise ChannelUnavailable() from None


class Channel:
    def __init__(self, owner_id, task_id, generation):
        self.identity = {'task_id': str(task_id), 'news_id': None, 'generation': int(generation)}
        prefix = f'nh:translation:{{{int(owner_id)}:{task_id}:{int(generation)}}}'
        self.keys = [prefix + ':state', prefix + ':events']
        self.redis = client()

    def mutate(self, op, token='', **body):
        try:
            result = self.redis.eval(_MUTATE, 2, *self.keys, op, str(token),
                                     json.dumps(body, ensure_ascii=False), 1048576)
            if not result:
                raise ChannelUnavailable()
            return result
        except Exception:
            raise ChannelUnavailable() from None

    def read(self, cursor=''):
        if cursor and not CURSOR.fullmatch(cursor):
            raise ChannelUnavailable()
        try:
            value = self.redis.eval(_READ, 2, *self.keys, cursor)
            if not value:
                raise ChannelUnavailable()
            return json.loads(value)
        except Exception:
            raise ChannelUnavailable() from None

    def wait(self, cursor):
        try:
            self.redis.xread({self.keys[1]: cursor}, count=128, block=500)
        except Exception:
            raise ChannelUnavailable() from None


class BufferedPublisher:
    """A bounded, nonblocking producer; Redis I/O and DB control run separately."""
    def __init__(self, channel, token, validate, abort):
        self.channel, self.token = channel, token
        self.validate, self.abort = validate, abort
        self.condition = threading.Condition()
        self.pending, self.size, self.inflight = [], 0, 0
        self.stopped = threading.Event()
        self.done = threading.Event()
        self.failed = threading.Event()
        self.checked = time.monotonic()
        self.publisher = threading.Thread(target=self._publish, daemon=True, name='translation-publisher')
        self.controller = threading.Thread(target=self._control, daemon=True, name='translation-control')

    def __enter__(self):
        self.channel.mutate('init', self.token)
        self.publisher.start()
        self.controller.start()
        return self

    def fail(self):
        self.failed.set()
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        self.abort()

    def check(self):
        if self.failed.is_set() or time.monotonic() - self.checked > 2:
            raise ChannelUnavailable()

    def append(self, text):
        self.check()
        with self.condition:
            size = len(text.encode('utf-8'))
            if self.size + self.inflight + size > MAX_BUFFER:
                self.failed.set()
                raise ChannelUnavailable()
            self.pending.append(text)
            self.size += size
            if self.size >= 4096:
                self.condition.notify()

    def _publish(self):
        try:
            while not self.stopped.is_set():
                self.check()
                with self.condition:
                    if self.size < 4096 and not self.done.is_set():
                        self.condition.wait(0.025)
                    pieces, self.pending = self.pending, []
                    self.inflight = self.size
                    self.size = 0
                self.check()
                if pieces:
                    self.channel.mutate('delta', self.token, delta=''.join(pieces))
                with self.condition:
                    self.inflight = 0
                if self.done.is_set():
                    with self.condition:
                        if not self.pending:
                            break
        except Exception:
            self.fail()

    def _control(self):
        from django.db import close_old_connections
        try:
            while not self.stopped.wait(1):
                started = time.monotonic()
                # Close DB connections at thread boundaries. Authorization must
                # not outlive the two-second window even when a DB call stalls.
                close_old_connections()
                self.validate()
                if time.monotonic() - started > 1 or self.stopped.is_set():
                    raise ChannelUnavailable()
                self.channel.mutate('check', self.token)
                self.checked = started
        except Exception:
            self.fail()
        finally:
            close_old_connections()

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.done.set()
            with self.condition:
                self.condition.notify_all()
            self.publisher.join(2)
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        self.publisher.join(2)
        self.controller.join(2)
        if kind is None:
            self.check()
            if self.publisher.is_alive() or self.controller.is_alive():
                raise ChannelUnavailable()
