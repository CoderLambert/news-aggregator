import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Category, ChannelGroup, ChannelGroupMember, ChannelSubscription, News, Source, SourcePublication
from api.rss.models import FeedBinding, FeedOperation, SourceFeedLink
from api.rss.reading_models import NewsReadState
from api.services.channel_catalog import subscription_status

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(settings, monkeypatch):
    settings.PUBLIC_SITE_MODE = 'full'
    settings.RSS_FULL_CONTENT_ENABLED = True  # Positive controls; explicit opt-out cases live in test_feed_policy.
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(uuid.uuid4()))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '7')
    return get_user_model().objects.create_user('sub-a'), get_user_model().objects.create_user('sub-b')


def client(user):
    result = APIClient()
    result.force_authenticate(user)
    return result


def subscribe(user, key='one', **data):
    return client(user).post('/api/me/rss-subscriptions/', data or {'feed_url': 'https://example.com/RSS?tag=AI'},
                             format='json', HTTP_IDEMPOTENCY_KEY=key)


def test_shared_feed_and_source_have_personal_subscriptions_and_actor_operation_views(people):
    a, b = people
    first, other = subscribe(a), subscribe(b)
    assert first.status_code == other.status_code == 202
    assert FeedBinding.objects.count() == SourceFeedLink.objects.count() == 1
    assert ChannelSubscription.objects.count() == 2
    assert first.data['operation_id'] != other.data['operation_id']
    source = Source.objects.get(pk=first.data['subscription']['source_id'])
    assert source.publication.publication == 'personal'
    assert source.publication.owner == 'miniflux'
    assert source.publication.reading_policy == 'standard'
    assert client(b).get(f"/api/me/rss-operations/{first.data['operation_id']}/").status_code == 404
    assert client(a).get(f"/api/me/rss-operations/{first.data['operation_id']}/").status_code == 200
    assert subscription_status(source) == ('inactive', 'connecting')
    FeedBinding.objects.update(connection_state='ready', applied_policy_version=2)
    assert subscription_status(source) == ('active', '')


def test_idempotency_and_group_union_with_cross_user_groups_rejected(people):
    a, b = people
    ga = ChannelGroup.objects.create(user=a, name='A')
    gb = ChannelGroup.objects.create(user=b, name='B')
    body = {'feed_url': 'https://example.com/feed', 'group_ids': [ga.pk]}
    first = subscribe(a, **body)
    again = subscribe(a, **body)
    assert first.status_code == 202 and again.status_code == 200
    assert again.data['operation_id'] == first.data['operation_id']
    assert ChannelGroupMember.objects.count() == 1
    response = subscribe(a, group_ids=[], feed_url=body['feed_url'])
    assert response.status_code == 409
    assert subscribe(a, key='wrong-group', feed_url=body['feed_url'], group_ids=[gb.pk]).status_code == 404
    assert not ChannelGroupMember.objects.filter(group=gb).exists()
    ga.delete()
    assert ChannelSubscription.objects.count() == 1


def test_unsubscribe_during_registration_retains_other_reference_and_history(people):
    a, b = people
    first, other = subscribe(a), subscribe(b)
    source = Source.objects.get(pk=first.data['subscription']['source_id'])
    news = News.objects.create(source=source, category=Category.objects.create(name='Fixture', slug='fixture'),
        title='Keep', content='Summary', url='https://example.com/story', publish_time=timezone.now())
    NewsReadState.objects.create(user=a, news=news, is_read=True)
    first_id, other_id = first.data['subscription']['id'], other.data['subscription']['id']
    assert client(b).delete(f'/api/me/rss-subscriptions/{first_id}/').status_code == 404
    assert client(a).delete(f'/api/me/rss-subscriptions/{first_id}/').status_code == 204
    binding = FeedBinding.objects.get()
    assert binding.desired_enabled
    assert FeedOperation.objects.get(pk=first.data['operation_id']).state == 'cancelled'
    assert client(a).delete(f'/api/me/rss-subscriptions/{first_id}/').status_code == 204
    assert subscribe(a).data['subscription'] is None  # Replay does not resurrect a relation.
    assert client(b).delete(f'/api/me/rss-subscriptions/{other_id}/').status_code == 204
    binding.refresh_from_db()
    assert not binding.desired_enabled
    assert News.objects.filter(pk=news.pk).exists()
    assert NewsReadState.objects.get(user=a, news=news).is_read
    assert SourcePublication.objects.get(source=source).publication == 'personal'


def test_new_user_can_subscribe_registered_feed_without_policy_override(people):
    a, b = people
    first = subscribe(a)
    binding = FeedBinding.objects.get()
    binding.engine_feed_id = 12
    binding.connection_state = 'ready'
    binding.applied_policy_version = binding.policy_version
    binding.desired_mode = 'full_content'
    binding.save()
    second = subscribe(b)
    assert second.status_code == 201
    assert second.data['subscription']['feeds'][0]['desired_mode'] == 'full_content'
    assert second.data['subscription']['source_id'] == first.data['subscription']['source_id']


def test_missing_configuration_and_credential_url_leave_no_relations(people, monkeypatch):
    a, _ = people
    response = subscribe(a, feed_url='https://example.com/rss?token=SECRET')
    assert response.status_code == 400
    monkeypatch.delenv('RSS_ENGINE_ACCOUNT_ID')
    assert subscribe(a).status_code == 503
    assert FeedBinding.objects.count() == ChannelSubscription.objects.count() == 0


def test_operation_discovery_poll_mints_only_actor_tokens(people):
    a, b = people
    operation = FeedOperation.objects.create(actor=a, kind='discover', dedupe_key='fixture', request_hash='a'*64,
        state='succeeded', safe_result={'candidates': [{'url': 'https://example.com/rss', 'title': 'A'}]})
    url = f'/api/me/rss-operations/{operation.pk}/'
    assert client(b).get(url).status_code == 404
    result = client(a).get(url)
    token = result.data['result']['candidates'][0]['candidate_token']
    assert subscribe(a, candidate_token=token).status_code == 202
    assert subscribe(b, candidate_token=token).status_code == 400


def test_subscription_limit_allows_replay_and_existing_relation(people, settings):
    a, _ = people
    settings.RSS_SUBSCRIPTION_LIMIT = 1
    assert subscribe(a).status_code == 202
    assert subscribe(a).status_code == 200
    assert subscribe(a, key='new-idempotency').status_code == 202
    assert subscribe(a, key='over-limit', feed_url='https://example.com/other').status_code == 429
    assert FeedBinding.objects.count() == 1


def test_explicit_controls_require_current_article_binding_and_actor(people):
    from api.rss.models import EngineEntryMap
    a, b = people
    result = subscribe(a)
    source = Source.objects.get(pk=result.data['subscription']['source_id'])
    binding = FeedBinding.objects.get()
    binding.engine_feed_id = 9
    binding.desired_mode = 'full_content'
    binding.applied_policy_version = binding.policy_version
    binding.connection_state = 'ready'
    binding.save()
    news = News.objects.create(source=source, category=Category.objects.create(name='Controls', slug='controls'),
        title='Stored', content='Summary', url='https://example.com/repair', publish_time=timezone.now(),
        body_owner_binding=binding)
    EngineEntryMap.objects.create(binding=binding, engine_entry_id=19, news=news, source_url=news.url, disposition='linked')
    path = f'/api/news/{news.pk}/rss-refetch/'
    assert client(b).post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='r').status_code == 404
    first = client(a).post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='r')
    assert first.status_code == 202
    assert client(a).post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='new-click').data['operation_id'] == first.data['operation_id']
    operation = FeedOperation.objects.get(pk=first.data['operation_id'])
    assert operation.safe_input['fence']['news_id'] == news.pk
    SourcePublication.objects.filter(source=source).update(reading_policy='summary_only', policy_version=2)
    assert client(a).post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='blocked').status_code == 404
    assert FeedOperation.objects.filter(kind='refetch_entry').count() == 1
    refresh = f'/api/rss/feeds/{binding.pk}/refresh/'
    assert client(a).post(refresh, {}, format='json', HTTP_IDEMPOTENCY_KEY='refresh').status_code == 202
    assert client(a).post(refresh, {}, format='json', HTTP_IDEMPOTENCY_KEY='refresh').status_code == 202
    assert client(a).post(refresh, {}, format='json', HTTP_IDEMPOTENCY_KEY='refresh-new').status_code == 429
    assert client(b).post(refresh, {}, format='json', HTTP_IDEMPOTENCY_KEY='refresh').status_code == 404
    policy = f'/api/admin/rss/feeds/{binding.pk}/policy/'
    assert client(a).patch(policy, {'desired_mode': 'feed', 'expected_policy_version': binding.policy_version}, format='json').status_code == 403
    a.is_staff = True
    a.save(update_fields=['is_staff'])
    assert client(a).patch(policy, {'desired_mode': 'feed', 'expected_policy_version': binding.policy_version}, format='json').status_code == 202
    binding.refresh_from_db()
    assert binding.desired_mode == 'feed' and binding.connection_state == 'paused'


@pytest.mark.django_db(transaction=True)
def test_twenty_concurrent_subscription_replays_keep_one_relation_and_view(people):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connections
    from api.rss.subscriptions import subscribe as subscribe_service
    a, _ = people
    group = ChannelGroup.objects.create(user=a, name='Concurrent')
    barrier = Barrier(20)
    def call(_):
        try:
            barrier.wait(timeout=10)
            return subscribe_service(a, {'feed_url': 'https://example.com/concurrent', 'group_ids': [group.pk]}, 'same')[1]['operation_id']
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=20) as pool:
        ids = list(pool.map(call, range(20)))
    assert len(set(ids)) == 1
    assert FeedBinding.objects.count() == SourceFeedLink.objects.count() == ChannelSubscription.objects.count() == ChannelGroupMember.objects.count() == 1
    assert FeedOperation.objects.filter(actor=a, kind='register').count() == 1
