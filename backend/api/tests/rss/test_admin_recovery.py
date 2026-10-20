"""Administrative recovery regression: no live publisher, isolated DB."""
from dataclasses import replace
from datetime import timedelta
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.rss.control_worker import ControlWorker
from api.rss.engine import EngineConfig, EngineError, FeedDTO, PolicyReceipt
from api.rss.models import FeedBinding, FeedOperation, SourceFeedLink, SourcePublication
from api.models import Source
from api.rss.operations import enqueue_operation

pytestmark = pytest.mark.django_db(transaction=True)
INSTANCE = 'be22a55a-11c1-4ae4-9038-c919ec75aa42'

@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', INSTANCE)
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '3')
    user = get_user_model().objects.create_superuser('admin', password='synthetic')
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def channel(name='待恢复频道', **fields):
    binding = FeedBinding.objects.create(engine_instance_uuid=INSTANCE, account_id=3,
        canonical_feed_url='https://publisher.example/' + uuid.uuid4().hex[:8] + '/feed',
        desired_enabled=True, **fields)
    source = Source.objects.create(name=name, url='https://publisher.example/')
    SourcePublication.objects.create(source=source, publication='public', owner='miniflux', reading_policy='standard')
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True, editorial_pin=True)
    return source, binding


class Engine:
    def __init__(self):
        self.feeds = []
        self.creates = 0
        self.timeout = False
    def close(self): pass
    def list_feeds(self): return self.feeds
    def discover(self, url): return []
    def create_feed(self, url, **kwargs):
        self.creates += 1
        if self.timeout:
            raise EngineError('create_unknown', unknown_result=True)
        feed = FeedDTO(INSTANCE, 3, 77, url, 'Synthetic', False, False)
        self.feeds.append(feed)
        return feed
    def update_feed_policy(self, policy, expected_policy_version):
        feed = next(f for f in self.feeds if f.id == policy.engine_feed_id)
        return PolicyReceipt(replace(feed, crawler=policy.desired_mode == 'full_content', disabled=not policy.desired_enabled), expected_policy_version)


def verify(client, source, binding, key='request'):
    return client.post(f'/api/admin/rss/sources/{source.pk}/verification/',
        {'action': 'verify_and_recover', 'expected_versions': {str(binding.pk): binding.policy_version}},
        format='json', HTTP_IDEMPOTENCY_KEY=key)


def run(engine):
    worker = ControlWorker(EngineConfig(INSTANCE, 3, 'http://127.0.0.1:1', 'synthetic'), adapter_factory=lambda: engine, max_attempts=2)
    try: worker.run_once()
    finally: worker.close()


def test_safe_missing_feed_really_connects_and_becomes_subscribable(admin):
    user, client = admin
    source, binding = channel()
    old = enqueue_operation('register', actor=user, binding=binding, dedupe_key='failed')
    FeedOperation.objects.filter(pk=old.pk).update(state='failed', execution_phase='final_response', safe_result={'code': 'upstream_rejected'})
    response = verify(client, source, binding)
    assert response.status_code == 202
    engine = Engine()
    run(engine)
    binding.refresh_from_db()
    assert engine.creates == 1 and binding.connection_state == 'ready'
    assert client.get(f'/api/admin/rss/sources/{source.pk}/verification/').data['can_subscribe']
    old.refresh_from_db()
    assert old.state == 'failed' and old.safe_result == {'code': 'upstream_rejected'}


def test_legacy_missing_phase_never_creates_but_unique_feed_can_resolve_unknown(admin):
    user, client = admin
    source, binding = channel(connection_state='paused', last_error='create_unknown')
    old = FeedOperation.objects.create(kind='register', actor=user, binding=binding, dedupe_key='old', request_hash='a'*64,
        state='manual_blocked', safe_result={'outcome_unknown': True, 'code': 'create_unknown'}, attempts=5)
    assert verify(client, source, binding).status_code == 202
    engine = Engine()
    run(engine)
    assert engine.creates == 0
    # Reconciliation finds an existing remote create; never resets the old audit.
    engine.feeds = [FeedDTO(INSTANCE, 3, 77, binding.canonical_feed_url, 'Synthetic', False, False)]
    FeedOperation.objects.exclude(pk=old.pk).update(next_attempt=timezone.now() - timedelta(seconds=1))
    run(engine)
    binding.refresh_from_db(); old.refresh_from_db()
    assert binding.connection_state == 'ready' and old.resolved_at is not None
    assert old.attempts == 5 and old.state == 'manual_blocked' and old.safe_result['code'] == 'create_unknown'


def test_recovery_timeout_does_not_loop_create(admin):
    _, client = admin
    source, binding = channel()
    # Persisted admission records prove that the previous request never left.
    op = enqueue_operation('register', actor=admin[0], binding=binding, dedupe_key='not-sent')
    FeedOperation.objects.filter(pk=op.pk).update(state='failed')
    assert verify(client, source, binding).status_code == 202
    engine = Engine(); engine.timeout = True
    run(engine)
    FeedOperation.objects.filter(binding=binding).update(next_attempt=timezone.now()-timedelta(seconds=1))
    run(engine)
    assert engine.creates == 1


def test_list_filters_counts_search_and_private_cross_instance_isolation(admin):
    _, client = admin
    source, binding = channel('中文 News')
    private, _ = channel('Private')
    SourcePublication.objects.filter(source=private).update(publication='personal')
    other, other_binding = channel('Other instance')
    FeedBinding.objects.filter(pk=other_binding.pk).update(engine_instance_uuid=uuid.uuid4())
    response = client.get('/api/admin/rss/sources/', {'q': '中文', 'status': 'pending'})
    assert response.status_code == 200
    assert [row['source_id'] for row in response.data['results']] == [source.pk]
    assert response.data['counts']['pending'] == 1
    assert client.get('/api/admin/rss/sources/').data['count'] == 1
    assert client.get(f'/api/admin/rss/sources/{private.pk}/verification/').status_code == 404
    assert client.get(f'/api/admin/rss/sources/{other.pk}/verification/').status_code == 404
    assert client.get('/api/admin/rss/sources/', {'page_size': 500}).status_code == 400


def test_idempotent_batch_concurrent_admin_coalescing_and_stale_policy(admin):
    _, client = admin
    source, binding = channel()
    payload = {'action': 'verify_and_recover', 'targets': [{'source_id': source.pk, 'expected_versions': {str(binding.pk): 1}}]}
    response = client.post('/api/admin/rss/verification-batches/', payload, format='json', HTTP_IDEMPOTENCY_KEY='batch')
    assert response.status_code == 202
    assert client.post('/api/admin/rss/verification-batches/', payload, format='json', HTTP_IDEMPOTENCY_KEY='batch').data['id'] == response.data['id']
    other = get_user_model().objects.create_superuser('other', password='synthetic')
    client.force_authenticate(other)
    assert verify(client, source, binding, 'another-admin').status_code == 202
    assert FeedOperation.objects.filter(binding=binding).count() == 1
    FeedBinding.objects.filter(pk=binding.pk).update(policy_version=2)
    assert verify(client, source, binding, 'stale').status_code == 409


def test_legacy_empty_request_is_reconciliation_only_and_permissions_fail_closed(admin, settings):
    user, client = admin
    source, binding = channel()
    response = client.post(f'/api/admin/rss/sources/{source.pk}/verification/', {}, format='json', HTTP_IDEMPOTENCY_KEY='legacy')
    assert response.status_code == 202
    engine = Engine(); run(engine)
    assert engine.creates == 0
    user.is_superuser = False; user.save()
    assert client.get('/api/admin/rss/sources/').status_code == 403
    user.is_superuser = True; user.save()
    settings.PUBLIC_SITE_MODE = 'read_only'
    assert verify(client, source, binding).status_code == 403


def test_boundary_uses_last_possible_dispatch_not_creation_and_keeps_audit(admin):
    from api.rss.admin_verification import record_restart_boundary
    user, _ = admin
    _, binding = channel()
    old = FeedOperation.objects.create(kind='register', actor=user, binding=binding, dedupe_key='boundary', request_hash='b'*64,
        state='manual_blocked', attempts=9, safe_result={'code': 'create_unknown', 'outcome_unknown': True})
    stopped = timezone.now() + timedelta(seconds=1)
    evidence = {'worker_container': 'a'*64, 'engine_container': 'b'*64,
        'worker_stopped_at': stopped.isoformat(), 'engine_previous_start': (stopped-timedelta(hours=1)).isoformat(),
        'engine_started_at': (stopped+timedelta(seconds=1)).isoformat()}
    FeedOperation.objects.filter(pk=old.pk).update(dispatched_at=stopped+timedelta(seconds=2))
    assert record_restart_boundary(INSTANCE, 3, evidence) == 0
    old.refresh_from_db(); assert old.resolved_at is None
    FeedOperation.objects.filter(pk=old.pk).update(dispatched_at=stopped-timedelta(seconds=1))
    assert record_restart_boundary(INSTANCE, 3, evidence) == 1
    old.refresh_from_db()
    assert old.attempts == 9 and old.state == 'manual_blocked' and old.resolution['reason'] == 'engine_restart'


def test_dispatch_and_completion_recheck_publication_and_cancel_fences(admin):
    from api.rss.models import FeedVerificationItem
    from api.rss.operations import cancel_operation
    user, client = admin
    source, binding = channel()
    op = enqueue_operation('register', actor=user, binding=binding, dedupe_key='not-sent')
    FeedOperation.objects.filter(pk=op.pk).update(state='failed')
    verify(client, source, binding)
    worker = ControlWorker(EngineConfig(INSTANCE, 3, 'http://127.0.0.1:1', 'synthetic'), adapter_factory=Engine)
    try:
        claim = worker.claim_next(); request = worker.prepare(claim)
        request = worker._dispatch(request)
        operation = FeedVerificationItem.objects.get().operation
        operation.refresh_from_db(); assert operation.execution_phase == 'possibly_sent'
        outcome = worker.network(request)
        SourcePublication.objects.filter(source=source).update(owner='paused')
        worker.complete(request, outcome)
        binding.refresh_from_db()
        assert binding.engine_feed_id is None and binding.connection_state != 'ready'
        assert not client.get(f'/api/admin/rss/sources/{source.pk}/verification/').data['can_subscribe']
        cancel_operation(user, operation.pk)
        assert worker.complete(request, outcome) is False
    finally: worker.close()


def test_csrf_and_owner_scoped_batch_and_malformed_targets(admin):
    user, client = admin
    source, binding = channel()
    csrf = APIClient(enforce_csrf_checks=True); csrf.force_login(user)
    assert csrf.post(f'/api/admin/rss/sources/{source.pk}/verification/', {}, format='json', HTTP_IDEMPOTENCY_KEY='csrf').status_code == 403
    assert client.post('/api/admin/rss/verification-batches/', {'action': 'verify_and_recover', 'targets': [{}]*51}, format='json', HTTP_IDEMPOTENCY_KEY='large').status_code == 400
    result = verify(client, source, binding)
    other = get_user_model().objects.create_superuser('unrelated', password='synthetic')
    client.force_authenticate(other)
    assert client.get('/api/admin/rss/verification-batches/' + result.data['batch_id'] + '/').status_code == 404


def test_overview_is_aggregate_only_and_gets_never_dispatch(admin):
    from unittest.mock import patch
    _, client = admin
    channel()
    with patch('requests.sessions.Session.request', side_effect=AssertionError('GET must be local')):
        response = client.get('/api/admin/rss/health/')
        assert response.data['verification_counts']['pending'] == 1
        assert 'connections' not in response.data
        assert client.get('/api/admin/rss/sources/').status_code == 200
    assert FeedOperation.objects.count() == 0


def test_other_instance_ready_feed_cannot_grant_subscription(admin):
    from api.services.channel_catalog import subscription_status
    _, binding = channel(connection_state='ready', engine_feed_id=77, applied_policy_version=1)
    source = binding.source_links.get().source
    FeedBinding.objects.filter(pk=binding.pk).update(engine_instance_uuid=uuid.uuid4())
    assert subscription_status(source)[0] == 'inactive'


def test_terminal_admin_failure_does_not_enqueue_another_create(admin):
    _, client = admin
    source, binding = channel()
    op = enqueue_operation('register', actor=admin[0], binding=binding, dedupe_key='not-sent')
    FeedOperation.objects.filter(pk=op.pk).update(state='failed')
    verify(client, source, binding)
    class Rejected(Engine):
        def create_feed(self, url, **kwargs):
            raise EngineError('feed_parse_failed')
    run(Rejected())
    assert FeedOperation.objects.filter(binding=binding).count() == 2
    assert not FeedOperation.objects.filter(binding=binding, state__in=['pending', 'retry_wait']).exists()
    assert client.get('/api/admin/rss/sources/').data['results'][0]['status'] == 'failed'


def test_missing_operation_history_is_not_proof_of_no_request(admin):
    _, client = admin
    source, binding = channel(last_error='create_unknown')
    verify(client, source, binding)
    engine = Engine(); run(engine)
    assert engine.creates == 0


def test_multifeed_status_is_identical_in_filter_counts_and_row(admin):
    _, client = admin
    source, ready = channel(connection_state='ready', engine_feed_id=77, applied_policy_version=1)
    _, failed = channel('Failed companion', connection_state='error', last_error='feed_parse_failed')
    SourceFeedLink.objects.create(source=source, binding=failed, enabled=True, editorial_pin=True)
    detail = client.get(f'/api/admin/rss/sources/{source.pk}/verification/').data
    assert detail['status'] == 'failed'
    response = client.get('/api/admin/rss/sources/', {'status': 'failed'})
    assert source.pk in [s['source_id'] for s in response.data['results']]
    assert all(s['status'] == 'failed' for s in response.data['results'])
    assert client.get('/api/admin/rss/sources/', {'status': 'passed'}).data['count'] == 0


def test_read_failure_cannot_launder_missing_history_into_create_permission(admin):
    _, client = admin
    source, binding = channel(last_error='create_unknown')
    class Unauthenticated(Engine):
        def list_feeds(self): raise EngineError('authentication')
    verify(client, source, binding, 'read-fails')
    run(Unauthenticated())
    FeedOperation.objects.filter(binding=binding).update(created_at=timezone.now()-timedelta(seconds=61))
    assert verify(client, source, binding, 'read-again').status_code == 202
    engine = Engine(); run(engine)
    assert engine.creates == 0


def test_verification_unknown_revokes_subscribe_without_breaking_intentional_pause(admin):
    from api.services.channel_catalog import subscription_status
    _, client = admin
    source, binding = channel(connection_state='ready', engine_feed_id=77, applied_policy_version=1)
    assert subscription_status(source)[0] == 'active'
    verify(client, source, binding)
    run(Engine())
    assert subscription_status(source)[0] == 'inactive'


def test_counts_aggregate_multiple_channels_of_the_same_status(admin):
    _, client = admin
    for index in range(3): channel('Pending '+str(index))
    for index in range(7): channel('Ready '+str(index), connection_state='ready', engine_feed_id=100+index, applied_policy_version=1)
    response = client.get('/api/admin/rss/sources/')
    assert response.data['count'] == 3
    assert response.data['counts']['pending'] == 3
    assert response.data['counts']['passed'] == 7
    assert response.data['counts']['all'] == 10
    assert client.get('/api/admin/rss/health/').data['verification_counts']['all'] == 10


def test_pagination_and_rss_search_are_bounded_and_readonly(admin):
    _, client = admin
    for index in range(30): channel('Page '+str(index))
    first = client.get('/api/admin/rss/sources/')
    second = client.get('/api/admin/rss/sources/', {'page': 2})
    assert first.data['count'] == 30 and len(first.data['results']) == 25
    assert len(second.data['results']) == 5
    assert not ({s['source_id'] for s in first.data['results']} & {s['source_id'] for s in second.data['results']})
    assert len(client.get('/api/admin/rss/sources/', {'page_size': 50}).data['results']) == 30
    address = first.data['results'][0]['feeds'][0]['feed_url']
    assert client.get('/api/admin/rss/sources/', {'q': address}).data['count'] == 1
    assert FeedOperation.objects.count() == 0


def test_two_admin_threads_coalesce_the_same_binding(admin):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    from api.rss.admin_verification import submit
    first, _ = admin
    other = get_user_model().objects.create_superuser('parallel-admin', password='synthetic')
    source, binding = channel()
    gate = Barrier(2)
    def request(actor_id):
        close_old_connections()
        try:
            actor = get_user_model().objects.get(pk=actor_id)
            gate.wait(timeout=5)
            return str(submit([{'source_id': source.pk, 'expected_versions': {str(binding.pk): 1}}], actor, 'thread', True).pk)
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(request, [first.pk, other.pk]))) == 2
    assert FeedOperation.objects.filter(binding=binding).count() == 1


def test_same_origin_engine_discovery_reuses_redirected_feed_without_changing_anchor(admin):
    user, client = admin
    source, binding = channel(last_error='create_unknown')
    old = FeedOperation.objects.create(kind='register', actor=user, binding=binding, dedupe_key='redirect-old', request_hash='c'*64,
        state='manual_blocked', attempts=5, safe_result={'outcome_unknown': True, 'code': 'create_unknown'})
    target = 'https://publisher.example/canonical-feed.xml'
    engine = Engine()
    engine.feeds = [FeedDTO(INSTANCE,3,77,target,'Redirected',False,False)]
    engine.discover = lambda url: [{'url': target, 'title': 'Redirected'}]
    verify(client, source, binding)
    run(engine)
    binding.refresh_from_db(); old.refresh_from_db()
    assert binding.connection_state == 'ready' and binding.engine_feed_id == 77
    assert binding.effective_feed_url == target and binding.canonical_feed_url != target
    from api.rss.operations import get_or_create_binding
    assert get_or_create_binding(INSTANCE, 3, target).pk == binding.pk
    assert engine.creates == 0 and old.resolved_at is not None and old.attempts == 5
    assert client.get(f'/api/admin/rss/sources/{source.pk}/verification/').data['can_subscribe']


def test_cross_origin_discovery_is_not_binding_identity_evidence(admin):
    _, client = admin
    source, binding = channel(last_error='create_unknown')
    engine = Engine(); target = 'https://other.example/feed'
    engine.feeds = [FeedDTO(INSTANCE,3,77,target,'Unrelated',False,False),
        FeedDTO(INSTANCE,3,78,'https://publisher.example/another','Different channel',False,False)]
    engine.discover = lambda url: [{'url': target}]
    verify(client, source, binding)
    run(engine); binding.refresh_from_db()
    assert binding.engine_feed_id is None and engine.creates == 0
