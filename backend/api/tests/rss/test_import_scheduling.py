"""Regression contracts for shared admission; execution deferred by user request."""
from unittest.mock import patch

import pytest
from django.utils import timezone

from api.models import ChannelSubscription
from api.rss.import_models import RssImportBatch, RssImportItem
from api.rss.models import FeedOperation
from api.rss.opml import process_imports, parse_opml
from api.rss.subscriptions import unsubscribe
from api.tests.rss.registration_fixtures import connect_pending
from api.tests.rss.test_control_worker import lab, setup_binding  # noqa: F401
from api.tests.rss.test_opml_import import XML, client, confirmation, people, preview  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def confirm_batch(user):
    result = preview(user)
    assert result.status_code == 201
    response = client(user).post('/api/me/rss-imports/confirm/', confirmation(result), format='json')
    assert response.status_code == 202
    return result.data['id']


def test_duplicate_file_entries_recorded_and_groups_merged():
    rows = parse_opml(XML)
    assert len(rows) == 2
    one = next(row for row in rows if row['feed_url'] == 'https://example.com/feed')
    assert one['duplicate_count'] == 1
    assert one['groups'] == ['Reading', 'Tech']


def test_two_owners_follow_one_physical_registration_and_cancel_independently(people):
    first, second = people
    a, b = confirm_batch(first), confirm_batch(second)
    process_imports()
    a_items = list(RssImportItem.objects.filter(batch_id=a).select_related('operation'))
    b_items = list(RssImportItem.objects.filter(batch_id=b).select_related('operation'))
    assert {item.operation.shared_operation_id for item in a_items} == {item.operation.shared_operation_id for item in b_items}
    assert all(item.operation.actor_id == first.pk for item in a_items)
    response = client(first).patch(f'/api/me/rss-imports/{a}/', {'action': 'cancel'}, format='json')
    assert response.status_code == 200
    connect_pending()
    assert not ChannelSubscription.objects.filter(user=first).exists()
    assert ChannelSubscription.objects.filter(user=second).count() == 2


def test_existing_subscription_skips_admission_and_preserves_provenance(people):
    user, _ = people
    confirm_batch(user)
    process_imports()
    connect_pending()
    ids = set(ChannelSubscription.objects.filter(user=user).values_list('pk', flat=True))
    response = preview(user)
    assert all(item['outcome'] == 'already_subscribed' for item in response.data['items'])
    identity = client(user).post('/api/me/rss-imports/confirm/', confirmation(response), format='json').data['id']
    with patch('api.rss.additions.check_addition_limit', side_effect=AssertionError('duplicate must not use admission')):
        process_imports()
    assert not RssImportItem.objects.filter(batch_id=identity, created_subscription=True).exists()
    assert client(user).delete(f'/api/me/rss-imports/{identity}/').status_code == 200
    assert set(ChannelSubscription.objects.filter(user=user).values_list('pk', flat=True)) == ids


def test_cancelled_subscription_can_be_imported_again(people):
    user, _ = people
    confirm_batch(user)
    process_imports()
    connect_pending()
    for identity in list(ChannelSubscription.objects.filter(user=user).values_list('pk', flat=True)):
        unsubscribe(user, identity)
    confirm_batch(user)
    process_imports()
    connect_pending()
    assert ChannelSubscription.objects.filter(user=user).count() == 2


def test_pause_resume_survives_requery_and_owner_cannot_control_other_batch(people):
    user, other = people
    identity = confirm_batch(user)
    path = f'/api/me/rss-imports/{identity}/'
    assert client(other).patch(path, {'action': 'pause'}, format='json').status_code == 404
    assert client(user).patch(path, {'action': 'pause'}, format='json').status_code == 200
    process_imports()
    assert not RssImportItem.objects.filter(batch_id=identity, operation__isnull=False).exists()
    assert RssImportBatch.objects.get(pk=identity).paused
    assert client(user).patch(path, {'action': 'resume'}, format='json').status_code == 200
    process_imports()
    assert RssImportItem.objects.filter(batch_id=identity, operation__isnull=False).count() == 2


def test_old_batch_cooldown_does_not_block_free_slots(people):
    identity = confirm_batch(people[0])
    batch = RssImportBatch.objects.get(pk=identity)
    batch.options['import_retry_after'] = timezone.now().timestamp() + 3600
    batch.save(update_fields=['options'])
    assert process_imports() == 2
    assert RssImportItem.objects.filter(batch=batch, status='queued').count() == 2


def test_waiter_never_claimed_for_physical_network_work(people):
    from api.rss.control_worker import ControlWorker
    from api.rss.engine import EngineConfig
    confirm_batch(people[0])
    process_imports()
    operation = FeedOperation.objects.filter(actor=people[0]).first()
    binding = operation.binding
    worker = ControlWorker(EngineConfig(str(binding.engine_instance_uuid), binding.account_id,
        'http://127.0.0.1:1', 'synthetic'))
    try:
        claim = worker.claim_next()
        assert claim is not None
        assert FeedOperation.objects.get(pk=claim.operation_id).shared_operation_id is None
        assert claim.operation_id != operation.pk
    finally:
        worker.close()


def test_failed_reconciliation_read_keeps_unknown_create_fence(lab):
    from api.rss.engine import EngineError
    from api.rss.operations import enqueue_operation
    worker, remote = lab
    actor, binding, _ = setup_binding()
    remote.lose_create, remote.create_missing = True, True
    operation = enqueue_operation('register', actor=actor, binding=binding, dedupe_key='sticky-create')
    assert worker.run_once()
    FeedOperation.objects.filter(pk=operation.pk).update(next_attempt=timezone.now())
    with patch.object(remote, 'list_feeds', side_effect=EngineError('network', retryable=True)):
        assert worker.run_once()
    operation.refresh_from_db()
    assert operation.state == 'unknown' and operation.safe_result['outcome_unknown']
    FeedOperation.objects.filter(pk=operation.pk).update(next_attempt=timezone.now())
    assert worker.run_once()
    assert remote.create_calls == 1


def test_cancelled_personal_follower_is_not_admin_physical_history(people):
    from api.rss.admin_verification import operations
    a, b = confirm_batch(people[0]), confirm_batch(people[1])
    process_imports()
    item = RssImportItem.objects.filter(batch_id=a).select_related('operation__binding').first()
    assert client(people[0]).patch(f'/api/me/rss-imports/{a}/', {'action': 'cancel'}, format='json').status_code == 200
    assert not operations(item.operation.binding).filter(shared_operation__isnull=False).exists()
    assert RssImportItem.objects.filter(batch_id=b, operation__state='pending').count() == 2


def test_bulk_addition_record_cannot_retry_outside_its_batch(people):
    from api.rss.additions import addition_data, addition_action
    from api.rss.http import RssConflict
    identity = confirm_batch(people[0])
    process_imports()
    item = RssImportItem.objects.filter(batch_id=identity).select_related('operation__shared_operation', 'operation__binding').first()
    root = item.operation.shared_operation
    FeedOperation.objects.filter(pk=root.pk).update(state='failed', execution_phase='final_response')
    op = FeedOperation.objects.select_related('binding', 'shared_operation').get(pk=item.operation_id)
    assert 'retry' not in addition_data(op)['actions']
    with pytest.raises(RssConflict):
        addition_action(people[0], op.pk, action='retry', expected_version=op.user_intent_version, key='outside-batch')


def mark_roots_confirmed():
    """Synthetic positive engine/policy facts; no network or engine readiness claim."""
    from django.db.models import F
    from api.rss.models import FeedBinding
    for feed_id, binding in enumerate(FeedBinding.objects.order_by('created_at'), 1):
        FeedBinding.objects.filter(pk=binding.pk).update(engine_feed_id=feed_id, desired_enabled=True,
            connection_state='ready', applied_policy_version=F('policy_version'))
    FeedOperation.objects.filter(actor__isnull=True).update(state='succeeded', safe_result={'connected': True})


def test_manual_blocked_item_can_finish_after_positive_reconciliation(people):
    from api.rss.subscription_work import settle_subscription_work
    identity = confirm_batch(people[0])
    process_imports()
    items = RssImportItem.objects.filter(batch_id=identity)
    FeedOperation.objects.filter(pk__in=items.values('operation_id')).update(state='manual_blocked')
    items.update(status='failed', error_code='create_outcome_unproven')
    mark_roots_confirmed()
    settle_subscription_work()
    assert ChannelSubscription.objects.filter(user=people[0]).count() == 2
    assert items.filter(status='succeeded', error_code='').count() == 2


def test_paused_roots_do_not_consume_settlement_window(people):
    from api.rss.subscription_work import settle_subscription_work
    user = people[0]
    raw = ('<opml><body>' + ''.join(f'<outline type="rss" xmlUrl="https://site{i}.example/feed"/>'
        for i in range(20)) + '</body></opml>').encode()
    first = preview(user, raw)
    identity = client(user).post('/api/me/rss-imports/confirm/', confirmation(first), format='json').data['id']
    process_imports(limit=100)
    RssImportBatch.objects.filter(pk=identity).update(paused=True)
    later = confirm_batch(user)
    process_imports(limit=100)
    mark_roots_confirmed()
    settle_subscription_work(limit=1)
    assert RssImportItem.objects.filter(batch_id=later, status='succeeded').exists()
    assert not RssImportItem.objects.filter(batch_id=identity, status='succeeded').exists()
