"""Real coordinator/leases with gated synthetic network calls, no live engine."""
from collections import Counter
from queue import Queue
from threading import Event, Lock

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from api.rss.control_worker import ControlWorker, Outcome
from api.rss.engine import EngineConfig, EngineError
from api.rss.models import FeedBinding, FeedOperation
from api.rss.opml import process_imports
from api.tests.rss.test_opml_import import client, confirmation, people, preview  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def queued_import(user, urls):
    raw = ('<opml><body>' + ''.join(f'<outline type="rss" xmlUrl="{url}"/>' for url in urls) + '</body></opml>').encode()
    response = preview(user, raw)
    assert response.status_code == 201
    assert client(user).post('/api/me/rss-imports/confirm/', confirmation(response), format='json').status_code == 202
    process_imports(limit=100)


@pytest.fixture
def gated_workers():
    workers = []

    def make():
        binding = FeedBinding.objects.first()
        worker = ControlWorker(EngineConfig(str(binding.engine_instance_uuid), binding.account_id,
            'http://127.0.0.1:1', 'synthetic'))
        entered, gates, lock = Queue(), {}, Lock()

        def network(request):
            assert not connection.in_atomic_block
            gate = Event()
            with lock:
                gates[request.claim.operation_id] = gate
            entered.put(request.claim.operation_id)
            if not gate.wait(10):
                raise AssertionError('synthetic network gate was not released')
            return Outcome(error=EngineError('network', retryable=True))

        worker.network = network
        workers.append((worker, gates, lock))
        return worker, entered, gates

    yield make
    for worker, gates, lock in workers:
        with lock:
            for gate in gates.values():
                gate.set()
        worker.close()
        worker._control.shutdown(wait=True)


def test_configured_four_slots_refill_without_waiting_for_other_requests(people, gated_workers, settings):
    settings.RSS_IMPORT_BURST_CONCURRENCY = 4
    queued_import(people[0], [f'https://site{i}.example/feed' for i in range(6)])
    worker, entered, gates = gated_workers()
    # A past user without queued work must not prevent this sole owner borrowing.
    worker._served[people[1].pk] = 1
    worker.tick()
    first = [entered.get(timeout=3) for _ in range(4)]
    assert len(worker._inflight) == 4
    assert len(set(first)) == 4
    finished = first[0]
    gates[finished].set()
    worker._inflight[finished][0].result(timeout=3)
    worker.tick()
    replacement = entered.get(timeout=3)
    assert replacement not in first
    assert len(worker._inflight) == 4
    assert all(not worker._inflight[identity][0].done() for identity in first[1:])


def test_configured_base_slots_preserve_two_per_user(people, gated_workers, settings):
    settings.RSS_IMPORT_BURST_CONCURRENCY = 4
    for index, user in enumerate(people):
        queued_import(user, [f'https://user{index}-site{i}.example/feed' for i in range(5)])
    worker, entered, _ = gated_workers()
    worker.tick()
    for _ in range(4):
        entered.get(timeout=3)
    assert Counter(job[3] for job in worker._inflight.values()) == {people[0].pk: 2, people[1].pk: 2}


def test_ordinary_imports_share_idle_burst_capacity_fairly(people, gated_workers):
    for index, user in enumerate(people):
        queued_import(user, [f'https://burst-user{index}-site{i}.example/feed' for i in range(6)])
    worker, entered, _ = gated_workers()
    worker.tick()
    for _ in range(12):
        entered.get(timeout=3)
    assert len(worker._inflight) == 12
    assert Counter(job[3] for job in worker._inflight.values()) == {
        people[0].pk: 6,
        people[1].pk: 6,
    }


def test_superuser_import_gets_extra_slots_without_reducing_ordinary_share(people, gated_workers):
    ordinary = people[0]
    admin = get_user_model().objects.create_superuser('opml-admin', password='synthetic')
    queued_import(ordinary, [f'https://ordinary-{index}.example/feed' for index in range(5)])
    queued_import(admin, [f'https://admin-{index}.example/feed' for index in range(12)])
    worker, entered, _ = gated_workers()
    worker.tick()
    for _ in range(12):
        entered.get(timeout=3)
    assert len(worker._inflight) == 12
    assert Counter(job[3] for job in worker._inflight.values()) == {admin.pk: 10, ordinary.pk: 2}


def test_superuser_import_can_progress_past_regular_uncertainty_limit(people, gated_workers):
    ordinary = people[0]
    admin = get_user_model().objects.create_superuser('opml-fast-admin', password='synthetic')
    queued_import(ordinary, [f'https://uncertain-{index}.example/feed' for index in range(4)])
    FeedOperation.objects.filter(
        subscription_waiters__actor=ordinary,
        shared_operation__isnull=True,
    ).update(state='unknown', safe_result={'outcome_unknown': True})
    queued_import(admin, ['https://admin-ready.example/feed'])
    worker, _, _ = gated_workers()
    claim = worker.claim_next(recovery=False)
    assert claim is not None
    assert FeedOperation.objects.get(pk=claim.operation_id).subscription_waiters.filter(actor=admin).exists()


def test_superuser_fast_lane_is_revoked_immediately_after_demotion(people, gated_workers):
    ordinary = people[0]
    admin = get_user_model().objects.create_superuser('opml-demoted-admin', password='synthetic')
    queued_import(ordinary, [f'https://demotion-uncertain-{index}.example/feed' for index in range(4)])
    FeedOperation.objects.filter(
        subscription_waiters__actor=ordinary,
        shared_operation__isnull=True,
    ).update(state='unknown', safe_result={'outcome_unknown': True})
    queued_import(admin, ['https://demoted-admin.example/feed'])
    admin.is_superuser = False
    admin.save(update_fields=['is_superuser'])
    worker, _, _ = gated_workers()
    assert worker.claim_next(recovery=False) is None


def test_ordinary_import_stays_blocked_at_regular_uncertainty_limit(people, gated_workers):
    first, second = people
    queued_import(first, [f'https://ordinary-uncertain-{index}.example/feed' for index in range(4)])
    FeedOperation.objects.filter(
        subscription_waiters__actor=first,
        shared_operation__isnull=True,
    ).update(state='unknown', safe_result={'outcome_unknown': True})
    queued_import(second, ['https://ordinary-ready.example/feed'])
    worker, _, _ = gated_workers()
    assert worker.claim_next(recovery=False) is None


def test_busy_site_does_not_hide_later_work_for_other_sites(people, gated_workers):
    queued_import(people[0], [f'https://same.example/feed{i}' for i in range(3)] + ['https://other.example/feed'])
    worker, entered, _ = gated_workers()
    worker.tick()
    for _ in range(2):
        entered.get(timeout=3)
    assert len(worker._inflight) == 2
    assert {job[1].url.split('/')[2] for job in worker._inflight.values()} == {'same.example', 'other.example'}


def test_reconciliation_has_a_reserved_slot_when_all_four_registration_slots_are_busy(people, gated_workers):
    queued_import(people[0], [f'https://site{i}.example/feed' for i in range(5)])
    root = FeedOperation.objects.filter(actor__isnull=True).order_by('created_at').first()
    FeedOperation.objects.filter(pk=root.pk).update(state='unknown', safe_result={'outcome_unknown': True})
    worker, entered, _ = gated_workers()
    worker.tick()
    for _ in range(5):
        entered.get(timeout=3)
    assert len(worker._inflight) == 5
    assert Counter(job[4] for job in worker._inflight.values()) == {False: 4, True: 1}
    assert worker._inflight[root.pk][1].claim.reconcile


def test_idle_capacity_accelerates_safe_unknown_reconciliation(people, gated_workers):
    queued_import(people[0], [f'https://reconcile-{index}.example/feed' for index in range(12)])
    FeedOperation.objects.filter(actor__isnull=True).update(
        state='unknown', safe_result={'outcome_unknown': True})
    worker, entered, _ = gated_workers()
    worker.tick()
    for _ in range(12):
        entered.get(timeout=3)
    assert len(worker._inflight) == 12
    assert Counter(job[4] for job in worker._inflight.values()) == {False: 4, True: 1, 'burst': 7}
    assert all(job[1].claim.reconcile for job in worker._inflight.values())


def test_import_admission_runs_before_control_even_without_article_sync(monkeypatch, tmp_path):
    from api.rss import runtime
    from api.rss import control_worker, engine, opml
    order, handlers = [], {}

    class Control:
        closed = False
        def tick(self):
            order.append('tick')
            if order.count('tick') == 2:
                handlers[runtime.signal.SIGTERM](None, None)
            return {'control_age_seconds': 0}
        def close(self):
            self.closed = True

    control = Control()
    monkeypatch.setenv('NEWSHUB_RUNTIME_ROLE', 'rss_sync')
    monkeypatch.setenv('RSS_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(runtime, 'probe', lambda: {'role': 'rss_sync'})
    monkeypatch.setattr(runtime.signal, 'signal', lambda number, handler: handlers.setdefault(number, handler))
    monkeypatch.setattr(engine.EngineConfig, 'from_environment', lambda: object())
    monkeypatch.setattr(control_worker, 'ControlWorker', lambda _: control)
    monkeypatch.setattr(opml, 'process_imports', lambda limit: order.append('admit'))
    runtime.run(control=True, sync=False)
    assert order == ['admit', 'tick', 'tick']
    assert control.closed


def test_one_shot_falls_back_to_other_sites_when_due_recovery_is_rate_limited(people, gated_workers):
    from datetime import timedelta
    from django.utils import timezone
    queued_import(people[0], ['https://blocked.example/one', 'https://blocked.example/two', 'https://other.example/feed'])
    roots = FeedOperation.objects.filter(actor__isnull=True)
    FeedOperation.objects.filter(pk=roots.get(binding__canonical_feed_url='https://blocked.example/one').pk).update(
        state='unknown', next_attempt=timezone.now(), safe_result={'outcome_unknown': True})
    FeedOperation.objects.filter(pk=roots.get(binding__canonical_feed_url='https://blocked.example/two').pk).update(
        state='retry_wait', next_attempt=timezone.now() + timedelta(minutes=5), safe_result={'code': 'rate_limited'})
    worker, _, _ = gated_workers()
    claim = worker.claim_next()
    assert claim is not None
    assert FeedOperation.objects.get(pk=claim.operation_id).binding.canonical_feed_url == 'https://other.example/feed'


def test_fair_turn_survives_an_empty_recovery_lane_between_ticks(people, gated_workers, settings):
    settings.RSS_IMPORT_BURST_CONCURRENCY = 4
    from django.contrib.auth import get_user_model
    third = get_user_model().objects.create_user('opml-c')
    owners = [*people, third]
    for index, user in enumerate(owners):
        queued_import(user, [f'https://owner{index}-site{i}.example/feed' for i in range(5)])
    worker, entered, gates = gated_workers()
    worker.tick()
    for _ in range(4):
        entered.get(timeout=3)
    counts = Counter(job[3] for job in worker._inflight.values())
    assert counts == {owners[0].pk: 2, owners[1].pk: 1, owners[2].pk: 1}
    finished = next(identity for identity, job in worker._inflight.items() if job[3] == owners[0].pk)
    gates[finished].set()
    worker._inflight[finished][0].result(timeout=3)
    worker.tick()
    replacement = entered.get(timeout=3)
    assert worker._inflight[replacement][3] == owners[1].pk


@pytest.mark.parametrize('recovery', [False, True])
def test_cooling_site_cannot_fill_the_candidate_window_and_hide_other_sites(people, gated_workers, recovery):
    from datetime import timedelta
    from django.utils import timezone
    queued_import(people[0], [f'https://cooling.example/feed{i}' for i in range(64)]
        + ['https://cooling.example/backoff', 'https://available.example/feed'])
    roots = FeedOperation.objects.filter(actor__isnull=True)
    assert roots.count() == 66
    if recovery:
        roots.update(state='unknown', safe_result={'outcome_unknown': True})
    roots.filter(binding__canonical_feed_url='https://cooling.example/backoff').update(
        state='retry_wait', next_attempt=timezone.now() + timedelta(minutes=5),
        safe_result={'code': 'rate_limited'})
    worker, _, _ = gated_workers()
    claim = worker.claim_next(recovery=recovery)
    assert claim is not None
    selected = FeedOperation.objects.select_related('binding').get(pk=claim.operation_id)
    assert selected.binding.canonical_feed_url == 'https://available.example/feed'
    assert claim.reconcile is recovery
    assert roots.filter(binding__canonical_feed_url__startswith='https://cooling.example/',
        state='running').count() == 0
