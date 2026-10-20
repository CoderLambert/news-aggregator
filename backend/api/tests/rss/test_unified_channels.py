"""The channel catalog must never grant subscriptions to unbound sources."""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from api.models import ChannelSubscription, Source
from api.rss.models import FeedBinding, SourceFeedLink, SourcePublication

pytestmark = pytest.mark.django_db(transaction=True)


def test_ready_label_without_remote_feed_identity_cannot_create_subscription(settings):
    settings.PUBLIC_SITE_MODE = 'full'
    user = get_user_model().objects.create_user('catalog-reader')
    source = Source.objects.create(name='Unverified channel', url='https://example.com')
    SourcePublication.objects.create(source=source, publication='public', owner='miniflux')
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=1,
        canonical_feed_url='https://example.com/feed', connection_state='ready',
        desired_enabled=True, applied_policy_version=1)
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
    client = APIClient()
    client.force_authenticate(user)
    response = client.post('/api/me/channel-subscriptions/', {'source_ids': [source.pk]}, format='json')
    assert response.status_code == 400
    assert not ChannelSubscription.objects.filter(user=user).exists()


def test_pending_feed_grants_no_acl_until_engine_confirmation_and_cancel_leaves_no_relation(settings, monkeypatch):
    from api.rss.operations import cancel_operation
    from api.rss.subscriptions import subscribe
    from api.rss.models import FeedOperation
    from api.tests.rss.registration_fixtures import connect_pending
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(uuid.uuid4()))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '3')
    settings.RSS_FULL_CONTENT_ENABLED = True
    user = get_user_model().objects.create_user('pending-reader')
    _, first = subscribe(user, {'feed_url': 'https://publisher.example/feed'}, 'pending')
    assert first['subscription'] is None
    assert not ChannelSubscription.objects.filter(user=user).exists()
    cancel_operation(user, first['operation_id'])
    connect_pending()
    assert not ChannelSubscription.objects.filter(user=user).exists()
    binding = FeedBinding.objects.get()
    assert not binding.desired_enabled
    assert FeedOperation.objects.get(pk=first['operation_id']).state == 'cancelled'


def test_source_purposes_keep_history_and_public_candidates_without_exposing_personal_sources(settings, monkeypatch):
    settings.PUBLIC_SITE_MODE = 'full'
    user = get_user_model().objects.create_user('purpose-reader')
    old = Source.objects.create(name='Historical channel', url='https://old.example')
    SourcePublication.objects.create(source=old, publication='public', owner='legacy')
    instance = str(uuid.uuid4())
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', instance)
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '3')
    candidate = Source.objects.create(name='Pending default', url='https://candidate.example')
    SourcePublication.objects.create(source=candidate, publication='public', owner='miniflux')
    binding = FeedBinding.objects.create(engine_instance_uuid=instance, account_id=3,
        canonical_feed_url='https://candidate.example/feed')
    SourceFeedLink.objects.create(source=candidate, binding=binding, enabled=True, editorial_pin=True)
    private = Source.objects.create(name='Personal feed', url='https://personal.example')
    SourcePublication.objects.create(source=private, publication='personal', owner='miniflux')
    client = APIClient()
    client.force_authenticate(user)
    history = client.get('/api/sources/').data
    history_ids = {item['id'] for item in history}
    assert {old.pk, candidate.pk} <= history_ids and private.pk not in history_ids
    catalog = client.get('/api/sources/?purpose=subscribe').data
    assert len(catalog) == 1 and catalog[0]['id'] == candidate.pk
    assert catalog[0]['can_subscribe'] is False and catalog[0]['rss_status'] == 'pending'
    assert client.get('/api/sources/?purpose=invalid').status_code == 400


def test_batch_subscription_rechecks_revoked_source_policy(settings):
    from api.models import Category, SourceConfig
    settings.PUBLIC_SITE_MODE = 'full'
    settings.RSS_FULL_CONTENT_ENABLED = True
    user = get_user_model().objects.create_user('revoked-catalog-reader')
    source = Source.objects.create(name='Revoked publisher', url='https://revoked.example')
    SourcePublication.objects.create(source=source, publication='public', owner='miniflux', reading_policy='standard')
    binding = FeedBinding.objects.create(engine_instance_uuid=uuid.uuid4(), account_id=3,
        engine_feed_id=1, canonical_feed_url='https://revoked.example/feed', connection_state='ready',
        desired_enabled=True, applied_policy_version=1)
    SourceFeedLink.objects.create(source=source, binding=binding, enabled=True)
    category = Category.objects.create(name='Revoked policy fixture', slug='revoked-policy')
    SourceConfig.objects.create(source_key='revoked_fixture', source=source, publisher_name='Revoked',
        channel_name='Revoked', category=category, status='blocked', reading_policy='summary_only')
    client = APIClient()
    client.force_authenticate(user)
    response = client.post('/api/me/channel-subscriptions/', {'source_ids': [source.pk]}, format='json')
    assert response.status_code == 400
    assert not ChannelSubscription.objects.filter(user=user).exists()
