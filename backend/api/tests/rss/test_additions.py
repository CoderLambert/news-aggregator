"""Personal pending intents remain visible without granting article access."""
import pytest
from datetime import timedelta
from django.utils import timezone
from api.models import ChannelSubscription
from api.rss.models import FeedOperation, FeedBinding
from api.tests.rss.test_subscriptions import people, client, subscribe
from api.tests.rss.registration_fixtures import connect_pending

pytestmark = pytest.mark.django_db(transaction=True)

def act(user, operation, action, version=1, key='action'):
    return client(user).post(f'/api/me/rss-additions/{operation}/actions/', {'action':action,'expected_version':version}, format='json',HTTP_IDEMPOTENCY_KEY=key)

def test_pending_addition_survives_without_subscription(people):
    a,b=people
    result=subscribe(a)
    rows=client(a).get('/api/me/rss-additions/').data
    assert rows['count']==1 and rows['results'][0]['operation_id']==result.data['operation_id']
    assert ChannelSubscription.objects.count()==0
    assert client(b).get('/api/me/rss-additions/').data['count']==0
    assert act(b,result.data['operation_id'],'cancel').status_code==404

def test_cancel_then_late_success_does_not_subscribe(people):
    a,b=people
    first=subscribe(a); subscribe(b)
    op=FeedOperation.objects.get(pk=first.data['operation_id'])
    assert act(a,op.pk,'cancel').status_code==200
    connect_pending()
    assert not ChannelSubscription.objects.filter(user=a).exists()
    assert ChannelSubscription.objects.filter(user=b).count()==1
    assert FeedBinding.objects.get().desired_enabled
    assert act(a,op.pk,'cancel',version=1,key='stale').status_code==409

def test_unknown_only_reconciles_without_create(people):
    a,_=people
    first=subscribe(a); op=FeedOperation.objects.get(pk=first.data['operation_id'])
    FeedOperation.objects.filter(pk=op.pk).update(state='manual_blocked',execution_phase='possibly_sent',safe_result={'outcome_unknown':True})
    assert act(a,op.pk,'retry').status_code==409
    response=act(a,op.pk,'reconcile',key='reconcile')
    assert response.status_code==200
    op.refresh_from_db()
    assert op.safe_input['subscription_request']
    assert op.state=='unknown' and op.execution_phase=='possibly_sent'

def test_subscription_intent_survives_recovery(people):
    a,_=people
    first=subscribe(a); op=FeedOperation.objects.get(pk=first.data['operation_id'])
    FeedOperation.objects.filter(pk=op.pk).update(state='failed',execution_phase='final_response',created_at=timezone.now()-timedelta(seconds=61),safe_result={'code':'feed_parse_failed'})
    response=act(a,op.pk,'retry')
    assert response.status_code==200
    new=FeedOperation.objects.get(pk=response.data['operation_id'])
    assert new.pk!=op.pk and new.recovery_of_id==op.pk
    assert new.safe_input['subscription_request']['source_id']==first.data['source_id']
    op.refresh_from_db(); assert op.state=='failed' and op.safe_result['code']=='feed_parse_failed'

def test_addition_limits_and_idempotent_replay(people):
    a,_=people
    for i in range(5): assert subscribe(a,key=f'k{i}',feed_url=f'https://example.com/{i}/feed').status_code==202
    assert subscribe(a,key='k0',feed_url='https://example.com/0/feed').status_code==200
    assert subscribe(a,key='k5',feed_url='https://example.com/5/feed').status_code==429

def test_cancel_unknown_preserves_original_failure_audit(people):
    a,_=people
    first=subscribe(a); op=FeedOperation.objects.get(pk=first.data['operation_id'])
    FeedOperation.objects.filter(pk=op.pk).update(state='unknown',execution_phase='possibly_sent',safe_result={'code':'create_unknown','outcome_unknown':True})
    assert act(a,op.pk,'cancel').status_code==200
    op.refresh_from_db()
    assert op.safe_result['code']=='create_unknown' and op.execution_phase=='possibly_sent'

def test_hourly_addition_limit_counts_finished_targets(people):
    a,_=people
    for i in range(20):
        result=subscribe(a,key=f'hour-{i}',feed_url=f'https://example.com/hour/{i}/feed')
        assert result.status_code==202
        FeedOperation.objects.filter(pk=result.data['operation_id']).update(state='failed',execution_phase='final_response')
    assert subscribe(a,key='hour-21',feed_url='https://example.com/hour/21/feed').status_code==429

def test_connected_addition_reports_owner_scoped_article_readiness(people):
    from api.models import News,Category,Source
    a,b=people
    result=subscribe(a); connect_pending()
    row=client(a).get('/api/me/rss-additions/').data['results'][0]
    assert row['article_count']==0 and row['article_state']=='waiting'
    category=Category.objects.first()
    if category is None: category=Category.objects.create(name='Ready',slug='ready')
    News.objects.create(source_id=result.data['source_id'],category=category,title='Ready',content='Summary',url='https://example.com/ready-article',publish_time=timezone.now())
    row=client(a).get('/api/me/rss-additions/').data['results'][0]
    assert row['article_count']==1 and row['article_state']=='ready'
    assert client(b).get('/api/me/rss-additions/').data['count']==0
