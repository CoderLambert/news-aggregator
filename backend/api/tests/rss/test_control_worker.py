"""T08 concurrency and mutation fences; fake engine is explicitly not live proof."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from api.models import Category, ChannelSubscription, News, Source
from api.rss.control_worker import ControlWorker, Outcome
from api.rss.engine import EngineConfig, EngineError, EntryDTO, FeedDTO, PolicyReceipt
from api.rss.models import EngineEntryMap, FeedBinding, FeedOperation, SourceFeedLink, SourcePublication
from api.rss.operations import (OperationError, cancel_operation, change_policy, enqueue_operation,
    acknowledge_refetch, get_operation_for_actor, get_or_create_binding, reconcile_binding,
    refetch_handoffs, sqlite_retry)

pytestmark = pytest.mark.django_db(transaction=True)
INSTANCE = 'be22a55a-11c1-4ae4-9038-c919ec75aa42'
URL = 'https://publisher.example/Feed?tag=AI'
CONFIG = EngineConfig(INSTANCE, 3, 'http://127.0.0.1:8080', 'synthetic-token', read_attempts=1)


class FakeEngine:
    def __init__(self):
        self.feeds = {}
        self.create_calls = self.policy_calls = self.refresh_calls = self.refetch_calls = self.discover_calls = 0
        self.create_hook = self.refetch_hook = None
        self.lose_create = self.create_missing = False
        self.discovery = []
        self.discovery_error = None
        self.entry = None

    def close(self):
        pass

    def list_feeds(self):
        assert not connection.in_atomic_block
        return list(self.feeds.values())

    def create_feed(self, url, *, desired_mode, disabled):
        assert not connection.in_atomic_block
        self.create_calls += 1
        feed = FeedDTO(INSTANCE, 3, 7, url, 'Feed', desired_mode == 'full_content', disabled)
        if not self.create_missing:
            self.feeds[7] = feed
        if self.create_hook:
            self.create_hook()
        if self.lose_create:
            raise EngineError('create_unknown', unknown_result=True)
        return feed

    def update_feed_policy(self, binding, expected_policy_version):
        assert not connection.in_atomic_block
        self.policy_calls += 1
        feed = replace(self.feeds[binding.engine_feed_id], crawler=binding.desired_mode == 'full_content',
                       disabled=not binding.desired_enabled)
        self.feeds[feed.id] = feed
        return PolicyReceipt(feed, expected_policy_version)

    def get_feed(self, feed_id):
        return self.feeds[feed_id]

    def refresh_feed(self, feed_id):
        assert not connection.in_atomic_block
        self.refresh_calls += 1

    def refetch_entry(self, entry_id):
        assert not connection.in_atomic_block
        self.refetch_calls += 1
        if self.refetch_hook:
            self.refetch_hook()
        return self.entry

    def get_entry(self, entry_id):
        self.get_entry_calls = getattr(self, 'get_entry_calls', 0) + 1
        return self.entry

    def discover(self, url):
        assert not connection.in_atomic_block
        self.discover_calls += 1
        if self.discovery_error:
            raise self.discovery_error
        return self.discovery


@pytest.fixture
def lab():
    remote = FakeEngine()
    worker = ControlWorker(CONFIG, adapter_factory=lambda: remote)
    yield worker, remote
    worker.close()


def setup_binding(*, ready=False, full=False):
    actor = get_user_model().objects.create_user('actor-' + uuid.uuid4().hex[:12])
    binding = FeedBinding.objects.create(engine_instance_uuid=INSTANCE, account_id=3,
        canonical_feed_url=URL, desired_mode='full_content' if full else 'feed', desired_enabled=True,
        engine_feed_id=7 if ready else None, applied_policy_version=1 if ready else 0,
        connection_state='ready' if ready else 'pending')
    source = Source.objects.create(name='source-' + uuid.uuid4().hex, url='https://publisher.example/')
    SourcePublication.objects.create(source=source, owner='miniflux', reading_policy='standard')
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
    ChannelSubscription.objects.create(user=actor, source=source)
    return actor, binding, source


def setup_article(remote):
    actor, binding, source = setup_binding(ready=True, full=True)
    remote.feeds[7] = FeedDTO(INSTANCE, 3, 7, URL, 'Feed', True, False)
    category = Category.objects.create(name='Test', slug='test')
    news = News.objects.create(title='Title', content='summary', source=source, category=category,
        url='https://publisher.example/article', publish_time=timezone.now(), full_content='old body',
        body_owner_binding=binding, body_owner_version=1)
    entry = EngineEntryMap.objects.create(binding=binding, engine_entry_id=21, news=news, source_url=news.url)
    remote.entry = EntryDTO(INSTANCE, 3, 7, 21, 'Title', news.url, None, '', '<p>new body</p>', None, None)
    return actor, binding, source, news, entry


def drain(worker, count=100):
    for _ in range(count):
        if not worker.run_once():
            return
    raise AssertionError('unexpected unbounded runnable operations')


def test_twenty_concurrent_actor_intents_share_one_binding_and_one_physical_create(lab):
    worker, remote = lab
    actors = [get_user_model().objects.create_user(f'user-{i}') for i in range(20)]
    barrier = Barrier(20)

    @sqlite_retry
    def register(actor):
        binding = get_or_create_binding(INSTANCE, 3, URL)
        with transaction.atomic():
            source = Source.objects.create(name=f'rss-user-{actor.pk}', url='https://publisher.example/')
            SourcePublication.objects.create(source=source, owner='miniflux', reading_policy='standard')
            SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
            ChannelSubscription.objects.create(user=actor, source=source)
            reconcile_binding(binding.pk)
            return enqueue_operation('register', actor=actor, binding=binding, dedupe_key='same-key').pk

    def concurrent(actor):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return register(actor)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=20) as pool:
        ids = list(pool.map(concurrent, actors))
    assert len(set(ids)) == 20 and FeedBinding.objects.count() == 1
    drain(worker)
    assert remote.create_calls == 1
    assert FeedOperation.objects.filter(actor__isnull=False, state='succeeded').count() == 20
    with pytest.raises(OperationError, match='not_found'):
        get_operation_for_actor(actors[0], ids[1])


@pytest.mark.parametrize('committed', [True, False])
def test_unknown_create_only_reconciles_and_never_reissues(lab, committed):
    worker, remote = lab
    actor, binding, _ = setup_binding()
    remote.lose_create, remote.create_missing = True, not committed
    operation = enqueue_operation('register', actor=actor, binding=binding, dedupe_key='create')
    assert worker.run_once()
    operation.refresh_from_db()
    assert operation.state == 'unknown'
    for _ in range(5):
        FeedOperation.objects.filter(pk=operation.pk).update(next_attempt=timezone.now())
        worker.run_once()
    operation.refresh_from_db()
    assert remote.create_calls == 1
    assert operation.state == ('succeeded' if committed else 'manual_blocked')


def test_cancel_before_execution_and_last_reference_do_not_create_feed(lab):
    worker, remote = lab
    actor, binding, source = setup_binding()
    operation = enqueue_operation('register', actor=actor, binding=binding, dedupe_key='register')
    cancel_operation(actor, operation.pk)
    ChannelSubscription.objects.filter(user=actor, source=source).delete()
    reconcile_binding(binding.pk)
    drain(worker)
    assert remote.create_calls == 0
    binding.refresh_from_db()
    assert not binding.desired_enabled and binding.connection_state == 'paused'
    assert get_operation_for_actor(actor, operation.pk)['state'] == 'cancelled'


@pytest.mark.parametrize('owner', ['legacy', 'paused', 'miniflux'])
@pytest.mark.parametrize('enabled', [True, False])
def test_editorial_pin_only_collects_after_miniflux_ownership(lab, owner, enabled):
    worker, remote = lab
    _, binding, source = setup_binding()
    ChannelSubscription.objects.filter(source=source).delete()
    SourceFeedLink.objects.filter(binding=binding).update(editorial_pin=True, enabled=enabled)
    SourcePublication.objects.filter(source=source).update(owner=owner, publication='public')
    reconcile_binding(binding.pk)
    drain(worker)
    binding.refresh_from_db()
    assert binding.desired_enabled is (owner == 'miniflux')
    assert remote.create_calls == (1 if owner == 'miniflux' else 0)


@pytest.mark.parametrize('kind', ['set_enabled', 'update_feed_policy'])
def test_unknown_configuration_matching_dto_flags_cannot_prove_missing_rules(lab, monkeypatch, kind):
    worker, remote = lab
    actor, binding, _ = setup_binding(ready=True, full=True)
    remote.feeds[7] = FeedDTO(INSTANCE, 3, 7, URL, 'Feed', False, True)
    FeedBinding.objects.filter(pk=binding.pk).update(connection_state='paused', applied_policy_version=0)
    operation = enqueue_operation(kind, actor=actor, binding=binding, dedupe_key='lost-policy')
    apply = remote.update_feed_policy
    reads = []

    def lost_response(policy, version):
        apply(policy, version)
        raise EngineError('policy_unknown', unknown_result=True)

    monkeypatch.setattr(remote, 'update_feed_policy', lost_response)
    monkeypatch.setattr(remote, 'get_feed', lambda feed_id: (reads.append(feed_id), remote.feeds[feed_id])[1])
    assert worker.run_once()
    for _ in range(4):
        FeedOperation.objects.filter(pk=operation.pk).update(next_attempt=timezone.now())
        assert worker.run_once()
    operation.refresh_from_db(); binding.refresh_from_db()
    matching = remote.feeds[7]
    assert matching.crawler and not matching.disabled
    assert not hasattr(matching, 'blocklist_rules') and not hasattr(matching, 'keeplist_rules')
    assert reads == [7] * 4 and remote.policy_calls == 1
    assert operation.state == 'manual_blocked'
    assert operation.safe_result['code'] == 'policy_outcome_unproven'
    assert binding.applied_policy_version == 0 and binding.connection_state == 'paused'


@pytest.mark.parametrize('keep_other_reference', [True, False])
def test_cancel_inflight_registration_converges_after_remote_commit(lab, keep_other_reference):
    worker, remote = lab
    actor, binding, source = setup_binding()
    if keep_other_reference:
        other = get_user_model().objects.create_user('other')
        ChannelSubscription.objects.create(user=other, source=source)
    entered, release = Event(), Event()
    remote.create_hook = lambda: (entered.set(), release.wait(10))
    operation = enqueue_operation('register', actor=actor, binding=binding, dedupe_key='register')
    worker.tick()
    assert entered.wait(5)
    cancel_operation(actor, operation.pk)
    ChannelSubscription.objects.filter(user=actor, source=source).delete()
    reconcile_binding(binding.pk)
    release.set()
    deadline = time.monotonic() + 5
    while worker.status()['control_busy'] and time.monotonic() < deadline:
        worker.tick()
        time.sleep(0.01)
    drain(worker)
    assert remote.create_calls == 1
    assert remote.feeds[7].disabled is not keep_other_reference
    binding.refresh_from_db()
    assert binding.engine_feed_id == 7 and binding.desired_enabled is keep_other_reference
    assert get_operation_for_actor(actor, operation.pk)['state'] == 'cancelled'


def test_expired_old_lease_cannot_commit(lab):
    worker, _ = lab
    actor, binding, _ = setup_binding()
    operation = enqueue_operation('register', actor=actor, binding=binding, dedupe_key='register')
    first = worker.claim_next()
    request = worker.prepare(first)
    FeedOperation.objects.filter(pk=operation.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    second = worker.claim_next()
    assert second.epoch > first.epoch and second.token != first.token and second.reconcile
    assert not worker.complete(request, Outcome({'connected': True}))
    operation.refresh_from_db()
    assert operation.state == 'running' and operation.lease_token == second.token
    binding.refresh_from_db()
    assert binding.engine_feed_id is None and binding.applied_policy_version == 0


def test_policy_tightening_cancels_pending_and_discards_inflight_refetch(lab):
    worker, remote = lab
    actor, binding, source, news, entry = setup_article(remote)
    old = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
                            source_id=source.pk, dedupe_key='old')
    pending = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
                                source_id=source.pk, dedupe_key='pending')
    remote.refetch_hook = lambda: change_policy(binding.pk, expected_policy_version=1, desired_mode='feed')
    worker.run_once()
    old.refresh_from_db(); pending.refresh_from_db(); news.refresh_from_db()
    assert old.state == pending.state == 'cancelled'
    assert news.full_content == 'old body' and not list(refetch_handoffs())
    drain(worker)
    binding.refresh_from_db()
    assert binding.applied_policy_version == binding.policy_version == 2
    assert binding.connection_state == 'ready' and not remote.feeds[7].crawler
    assert remote.refetch_calls == 1


@pytest.mark.parametrize('field,value', [('epoch', 2), ('policy_version', 2), ('reading_policy', 'unrecognized')])
def test_current_source_fence_rejects_old_or_unknown_policy_before_network(lab, field, value):
    worker, remote = lab
    actor, binding, source, _, entry = setup_article(remote)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='refetch')
    SourcePublication.objects.filter(source=source).update(**{field: value})
    worker.run_once()
    operation.refresh_from_db()
    assert operation.state == 'cancelled' and remote.refetch_calls == 0


def test_refetch_handoff_is_durable_and_contains_no_html_or_news_write(lab):
    worker, remote = lab
    actor, binding, source, news, entry = setup_article(remote)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='refetch')
    worker.run_once()
    operation.refresh_from_db(); news.refresh_from_db()
    assert operation.safe_result == {'entry_id': '21', 'pending_sync': True}
    assert [row.pk for row in refetch_handoffs()] == [operation.pk]
    assert news.full_content == 'old body'


@pytest.mark.parametrize('status', ['accepted', 'unchanged', 'quarantined', 'stale', 'rejected', 'conflict'])
def test_fenced_sync_ack_keeps_explicit_body_result_for_polling(lab, status):
    worker, remote = lab
    actor, binding, source, _, entry = setup_article(remote)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='refetch')
    worker.run_once()
    assert not acknowledge_refetch(operation.pk, 'different-hash', sync_status=status)
    assert acknowledge_refetch(operation.pk, operation.request_hash, sync_status=status,
                               reason='body_' + status, revision=3)
    view = get_operation_for_actor(actor, operation.pk)
    assert view['result'] == {'entry_id': '21', 'pending_sync': False,
        'sync_status': status, 'code': 'body_' + status, 'revision': '3'}
    assert not list(refetch_handoffs())


def test_operation_view_drops_unrecognized_json_html_and_secret_fields():
    actor = get_user_model().objects.create_user('view')
    operation = enqueue_operation('discover', actor=actor, dedupe_key='discover', url='https://publisher.example/')
    FeedOperation.objects.filter(pk=operation.pk).update(safe_result={
        'password': 'must-not-appear', 'html': '<p>private</p>', 'url': 'http://internal/',
        'candidates': [{'url': 'https://publisher.example/feed', 'title': '<script>bad</script>', 'token': 'private'}]})
    assert get_operation_for_actor(actor, operation.pk)['result'] == {
        'candidates': [{'url': 'https://publisher.example/feed', 'title': ''}]}


def test_public_source_refetch_does_not_require_subscription_but_rechecks_active_user(lab):
    worker, remote = lab
    actor, binding, source, _, entry = setup_article(remote)
    SourcePublication.objects.filter(source=source).update(publication='public')
    ChannelSubscription.objects.filter(user=actor).delete()
    SourceFeedLink.objects.filter(binding=binding).update(editorial_pin=True)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='public-refetch')
    get_user_model().objects.filter(pk=actor.pk).update(is_active=False)
    worker.run_once()
    operation.refresh_from_db()
    assert operation.state == 'cancelled' and remote.refetch_calls == 0


@pytest.mark.parametrize('field', ['body_owner_version', 'full_content_revision'])
def test_refetch_commit_rechecks_body_owner_and_revision(lab, field):
    worker, remote = lab
    actor, binding, source, news, entry = setup_article(remote)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='refetch')
    remote.refetch_hook = lambda: News.objects.filter(pk=news.pk).update(**{field: 2})
    worker.run_once()
    operation.refresh_from_db(); news.refresh_from_db()
    assert operation.state == 'cancelled' and news.full_content == 'old body'
    assert not list(refetch_handoffs())


def test_unknown_refetch_rechecks_stored_entry_without_repeating_fetch(lab):
    worker, remote = lab
    actor, binding, source, news, entry = setup_article(remote)
    operation = enqueue_operation('refetch_entry', actor=actor, binding=binding, entry=entry,
        source_id=source.pk, dedupe_key='refetch')
    def lost_response():
        raise EngineError('refetch_unknown', unknown_result=True)
    remote.refetch_hook = lost_response
    worker.run_once()
    for _ in range(5):
        FeedOperation.objects.filter(pk=operation.pk).update(next_attempt=timezone.now())
        worker.run_once()
    operation.refresh_from_db(); news.refresh_from_db()
    assert operation.state == 'manual_blocked' and remote.refetch_calls == 1
    assert remote.get_entry_calls >= 1 and news.full_content == 'old body'
    assert not list(refetch_handoffs())


@pytest.mark.parametrize('count', [0, 1, 3])
def test_discovery_zero_one_many_is_success_without_registration(lab, count):
    worker, remote = lab
    actor = get_user_model().objects.create_user('discovery')
    remote.discovery = [{'url': f'https://publisher.example/feed/{i}', 'title': 'Candidate'} for i in range(count)]
    operation = enqueue_operation('discover', actor=actor, dedupe_key='discover', url='https://publisher.example/')
    worker.run_once()
    view = get_operation_for_actor(actor, operation.pk)
    assert view['state'] == 'succeeded' and len(view['result']['candidates']) == count
    assert not FeedBinding.objects.exists() and remote.create_calls == 0


def test_retry_after_is_respected_and_timeout_is_bounded(lab):
    worker, remote = lab
    actor = get_user_model().objects.create_user('discovery')
    remote.discovery_error = EngineError('rate_limited', retryable=True, retry_after=90)
    operation = enqueue_operation('discover', actor=actor, dedupe_key='discover', url='https://publisher.example/')
    before = timezone.now()
    worker.run_once()
    operation.refresh_from_db()
    assert operation.next_attempt >= before + timedelta(seconds=90)
    assert not worker.run_once()
    remote.discovery_error = EngineError('network', retryable=True)
    for _ in range(5):
        FeedOperation.objects.filter(pk=operation.pk).update(next_attempt=timezone.now())
        worker.run_once()
    operation.refresh_from_db()
    assert operation.state == 'failed' and remote.discover_calls == 5


def test_discovery_404_is_zero_candidates_but_timeout_remains_error(lab):
    worker, remote = lab
    actor = get_user_model().objects.create_user('zero')
    remote.discovery_error = EngineError('not_found')
    operation = enqueue_operation('discover', actor=actor, dedupe_key='zero', url='https://publisher.example/')
    worker.run_once()
    assert get_operation_for_actor(actor, operation.pk)['result'] == {'candidates': []}


def test_network_does_not_hold_sqlite_writer_and_read_slot_remains_available(lab):
    worker, remote = lab
    actor, binding, source = setup_binding()
    enqueue_operation('register', actor=actor, binding=binding, dedupe_key='register')
    entered, release = Event(), Event()
    remote.create_hook = lambda: (entered.set(), release.wait(10))
    worker.tick()
    assert entered.wait(5)
    # This independent transaction commits while the control HTTP slot is blocked.
    with transaction.atomic():
        Source.objects.filter(pk=source.pk).update(description='write during network')
    future = worker.submit_short_read(lambda adapter: adapter.list_feeds())
    assert future.result(timeout=2)[0].id == 7
    # Lease expiry must not reclaim the still-running local future or add a third slot.
    worker._started = time.monotonic() - worker.lease_seconds - 1
    assert worker.tick()['control_stalled']
    assert remote.create_calls == 1
    release.set()


def test_worker_rejects_network_work_inside_callers_transaction(lab):
    worker, remote = lab
    with transaction.atomic(), pytest.raises(OperationError, match='worker_inside_transaction'):
        worker.run_once()
    assert remote.create_calls == 0


def test_reserved_read_slot_has_no_backlog(lab):
    worker, _ = lab
    entered, release = Event(), Event()
    def blocked(_):
        entered.set()
        release.wait(5)
    future = worker.submit_short_read(blocked)
    assert entered.wait(2)
    assert worker.submit_short_read(lambda _: None) is None
    release.set()
    future.result(timeout=2)


def test_stalled_control_causes_nonzero_process_exit_for_restart(tmp_path):
    token = tmp_path / 'synthetic-token'
    token.write_text('synthetic-token')
    root = Path(__file__).resolve().parents[4]
    env = {**os.environ, 'PYTHONPATH': str(root / 'backend'), 'DJANGO_ENV': 'production',
        'DJANGO_SETTINGS_MODULE': 'newsaggregator.settings', 'DJANGO_DEBUG': '0',
        'DJANGO_SECRET_KEY': 'synthetic-t08-abcdefghijklmnopqrstuvwxyz-0123456789-abcdef',
        'WAITRESS_TRUSTED_PROXY': '127.0.0.1', 'NEWSHUB_RUNTIME_ROLE': 'rss_sync',
        'DJANGO_DB_PATH': str(tmp_path / 'synthetic.sqlite3'), 'RSS_RUNTIME_DIR': str(tmp_path / 'runtime'),
        'RSS_ENGINE_INSTANCE_UUID': INSTANCE, 'RSS_ENGINE_ACCOUNT_ID': '3',
        'RSS_ENGINE_BASE_URL': 'http://127.0.0.1:8080', 'RSS_ENGINE_TOKEN_FILE': str(token)}
    script = '''
import django
django.setup()
from django.core.management import call_command
call_command('migrate', interactive=False, verbosity=0, skip_checks=True)
import api.rss.control_worker as module
class Stalled:
    def __init__(self, config): pass
    def tick(self): return {'control_age_seconds': 999, 'control_stalled': True}
    def close(self): pass
module.ControlWorker = Stalled
from api.rss.runtime import run
run(control=True)
'''
    result = subprocess.run([sys.executable, '-c', script], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 75 and 'rss-control-stalled' in result.stderr
