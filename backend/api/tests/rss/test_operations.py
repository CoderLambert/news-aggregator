"""Fixed operation contracts on isolated synthetic SQLite, no publisher requests."""
import uuid

import pytest
from django.contrib.auth import get_user_model

from api.rss.models import FeedOperation
from api.rss.operations import (OperationError, canonicalize_feed_url, change_policy,
    enqueue_operation, get_operation_for_actor, get_or_create_binding)

pytestmark = pytest.mark.django_db(transaction=True)
INSTANCE = 'be22a55a-11c1-4ae4-9038-c919ec75aa42'


def test_canonical_url_preserves_business_path_query_and_rejects_credentials():
    assert canonicalize_feed_url('https://EXAMPLE.test:443/Feed/?tag=AI%20News#part') == 'https://example.test/Feed/?tag=AI%20News'
    assert canonicalize_feed_url('https://EXAMPLE.test:8443/Feed') == 'https://example.test:8443/Feed'
    assert canonicalize_feed_url('https://例子.测试./Feed') == 'https://xn--fsqu00a.xn--0zwm56d/Feed'
    for value in ['https://example.test/feed?api%5fkey=private', 'https://u:p@example.test/feed',
                  'http://example.test/feed', 'https://127.0.0.1/feed']:
        with pytest.raises(OperationError):
            canonicalize_feed_url(value)


def test_per_actor_dedupe_conflict_and_private_operation_view():
    first = get_user_model().objects.create_user('first')
    second = get_user_model().objects.create_user('second')
    operation = enqueue_operation('discover', actor=first, dedupe_key='same', url='https://example.test/')
    assert enqueue_operation('discover', actor=first, dedupe_key='same', url='https://example.test/').pk == operation.pk
    other = enqueue_operation('discover', actor=second, dedupe_key='same', url='https://example.test/')
    assert other.pk != operation.pk
    with pytest.raises(OperationError, match='idempotency_conflict'):
        enqueue_operation('discover', actor=first, dedupe_key='same', url='https://other.test/')
    with pytest.raises(OperationError, match='not_found'):
        get_operation_for_actor(second, operation.pk)
    assert get_operation_for_actor(first, operation.pk)['result'] == {}
    assert FeedOperation.objects.count() == 2


def test_policy_change_is_atomic_and_idempotent():
    binding = get_or_create_binding(INSTANCE, 3, 'https://example.test/Feed')
    operation = change_policy(binding.pk, expected_policy_version=1, desired_mode='full_content', dedupe_key='mode')
    assert change_policy(binding.pk, expected_policy_version=1, desired_mode='full_content', dedupe_key='mode').pk == operation.pk
    with pytest.raises(OperationError, match='idempotency_conflict'):
        change_policy(binding.pk, expected_policy_version=1, desired_mode='feed', dedupe_key='mode')
    binding.refresh_from_db()
    assert (binding.policy_version, binding.connection_state, binding.desired_mode) == (2, 'paused', 'full_content')
    assert operation.safe_input == {'requested_policy': {'desired_mode': 'full_content', 'expected_policy_version': 1}}
