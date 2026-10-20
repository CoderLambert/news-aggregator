"""A reader's channel category never changes another reader's shared articles."""
import pytest
from django.utils import timezone
from api.models import Category,News,ChannelSubscription
from api.services.channel_articles import category_filter
from api.rss.access import authorized_news
from api.tests.rss.test_subscriptions import people,subscribe,client
from api.tests.rss.registration_fixtures import connect_pending

pytestmark=pytest.mark.django_db(transaction=True)

def test_new_category_is_durable_and_owner_scoped_for_existing_articles(people):
    a,b=people
    ai=Category.objects.create(name='Own AI',slug='own-ai')
    original=Category.objects.create(name='Original',slug='original')
    first=subscribe(a,feed_url='https://example.com/category-feed',category_id=ai.pk)
    assert first.status_code==202
    assert subscribe(b,feed_url='https://example.com/category-feed').status_code==202
    connect_pending()
    source=first.data['source_id']
    news=News.objects.create(source_id=source,category=original,title='Shared',content='Summary',url='https://example.com/category-story',publish_time=timezone.now())
    assert ChannelSubscription.objects.get(user=a,source_id=source).category_id==ai.pk
    assert ChannelSubscription.objects.get(user=b,source_id=source).category_id is None
    assert category_filter(authorized_news(a),[ai.pk],actor=a).filter(pk=news.pk).exists()
    assert not category_filter(authorized_news(b),[ai.pk],actor=b).filter(pk=news.pk).exists()
    news.refresh_from_db();assert news.category_id==original.pk

def test_existing_subscription_can_change_category_and_replay_cannot_overwrite(people):
    a,b=people; first=subscribe(a); connect_pending()
    category=Category.objects.create(name='Changed',slug='changed')
    payload={'action':'set_category','source_ids':[first.data['source_id']],'category_id':category.pk,'expected_version':0}
    assert client(b).post('/api/me/channel-subscriptions/',payload,format='json').status_code==404
    assert client(a).post('/api/me/channel-subscriptions/',payload,format='json').status_code==200
    row=client(a).get('/api/me/channel-subscriptions/').data[0]
    assert row['category_id']==category.pk
    assert subscribe(a).status_code==200
    assert ChannelSubscription.objects.get(user=a).category_id==category.pk
    assert client(a).post('/api/me/channel-subscriptions/',{**payload,'category_id':None,'expected_version':1},format='json').status_code==200
    assert ChannelSubscription.objects.get(user=a).category_id is None

def test_category_is_in_idempotency_hash_and_bad_values_have_no_effect(people):
    a,_=people; category=Category.objects.create(name='Hash',slug='hash')
    first=subscribe(a,feed_url='https://example.com/hashed-feed',category_id=category.pk)
    assert first.status_code==202
    assert subscribe(a,feed_url='https://example.com/hashed-feed').status_code==409
    assert subscribe(a,key='bad',feed_url='https://example.com/bad-category',category_id=True).status_code==400
