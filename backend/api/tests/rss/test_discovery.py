from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from api.rss.discovery import normalize_input, resolve_candidate_token, TOKEN_SALT
from api.rss.models import FeedOperation, FeedBinding
from api.models import ChannelSubscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def users(settings):
    settings.PUBLIC_SITE_MODE = 'full'
    return get_user_model().objects.create_user('discover-a'), get_user_model().objects.create_user('discover-b')


def client(user):
    result = APIClient()
    result.force_authenticate(user)
    return result


def resolve(user, value):
    return client(user).post('/api/rss/discovery/resolve/', {'input': value}, format='json')


def test_domain_and_url_preserve_business_query_and_path():
    assert normalize_input('Example.COM/Feed?tag=ai&x=1&x=2') == 'https://example.com/Feed?tag=ai&x=1&x=2'
    assert normalize_input('https://example.com/feed?tag=Rust') == 'https://example.com/feed?tag=Rust'


@pytest.mark.parametrize('value', ['https://user:password@example.com/rss', 'http://example.com/',
    'https://127.0.0.1/rss', 'https://[::1]/', 'https://service.internal/rss',
    'https://example.com/rss?access_token=secret', 'https://example.com/?api_key=secret',
    'https://example.com/\n', 'file:///tmp/feed', '', None, ['example.com']])
def test_unsafe_input_rejected_without_network_or_operations(users, value):
    # Whitespace around an input is allowed; embedded controls are not.
    if value == 'https://example.com/\n':
        value = 'https://example.com/a\nb'
    response = resolve(users[0], value)
    assert response.status_code == 400
    assert FeedOperation.objects.count() == 0


def test_pending_discovery_deduplicates_per_user_and_never_subscribes(users):
    a, b = users
    with patch('api.rss.engine.EngineAdapter.discover', side_effect=AssertionError('request must not fetch')):
        first = resolve(a, 'example.com')
        again = resolve(a, 'https://example.com')
        other = resolve(b, 'example.com')
    assert first.status_code == again.status_code == other.status_code == 202
    assert first.data['operation_id'] == again.data['operation_id']
    assert other.data['operation_id'] != first.data['operation_id']
    assert FeedOperation.objects.count() == 2
    assert FeedBinding.objects.count() == ChannelSubscription.objects.count() == 0


@pytest.mark.parametrize('candidates', [[], [{'url': 'https://example.com/rss', 'title': 'Feed'}],
    [{'url': 'https://example.com/rss', 'title': 'Feed'}, {'url': 'https://example.com/Atom?tag=AI', 'title': 'AI'}]])
def test_cached_zero_one_and_multiple_candidates_have_actor_bound_tokens(users, candidates):
    a, b = users
    operation_id = resolve(a, 'example.com').data['operation_id']
    FeedOperation.objects.filter(pk=operation_id).update(state='succeeded', safe_result={'candidates': candidates})
    response = resolve(a, 'example.com')
    assert response.status_code == 200
    assert len(response.data['candidates']) == len(candidates)
    for row in response.data['candidates']:
        assert row['cached_articles'] == []
        assert resolve_candidate_token(a, row['candidate_token']) == row['url']
        with pytest.raises(ValidationError):
            resolve_candidate_token(b, row['candidate_token'])
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 901):
            with pytest.raises(ValidationError):
                resolve_candidate_token(a, row['candidate_token'])
    assert FeedOperation.objects.count() == 1


def test_token_requires_a_current_successful_candidate(users):
    a, _ = users
    operation_id = resolve(a, 'example.com').data['operation_id']
    token = signing.dumps({'user_id': a.pk, 'operation_id': operation_id, 'url': 'https://example.com/rss'}, salt=TOKEN_SALT)
    with pytest.raises(ValidationError):
        resolve_candidate_token(a, token)
    FeedOperation.objects.filter(pk=operation_id).update(state='succeeded', safe_result={'candidates': []})
    with pytest.raises(ValidationError):
        resolve_candidate_token(a, token)


def test_quota_does_not_block_existing_pending_result(users, settings):
    settings.RSS_DISCOVERY_HOURLY_LIMIT = 1
    a, _ = users
    assert resolve(a, 'example.com').status_code == 202
    assert resolve(a, 'example.com').status_code == 202
    response = resolve(a, 'other.example.com')
    assert response.status_code == 429 and response.data['error']['retryable']
    assert FeedOperation.objects.count() == 1


def test_expired_cache_creates_new_operation_and_failed_result_is_not_success(users):
    a, _ = users
    operation_id = resolve(a, 'example.com').data['operation_id']
    FeedOperation.objects.filter(pk=operation_id).update(state='succeeded', safe_result={'candidates': []}, updated_at=timezone.now()-timedelta(minutes=16))
    response = resolve(a, 'example.com')
    assert response.status_code == 202 and response.data['operation_id'] != operation_id
    FeedOperation.objects.filter(pk=response.data['operation_id']).update(state='failed', safe_result={'code': 'timeout'})
    response = resolve(a, 'example.com')
    assert response.status_code == 202
