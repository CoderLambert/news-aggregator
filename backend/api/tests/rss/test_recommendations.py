"""Public recommendations never grant implicit personal or staff authority."""
import pytest
from django.contrib.auth import get_user_model
from api.models import Category
from api.rss.review_models import PublicFeedCandidate, PublicFeedSubmission
from api.rss.models import FeedBinding
from api.tests.rss.test_subscriptions import people, client, subscribe
from api.tests.rss.registration_fixtures import connect_pending

pytestmark=pytest.mark.django_db(transaction=True)

@pytest.fixture
def review_people(people):
    from api.rss.review_permissions import change_reviewer
    a,b=people
    admin=get_user_model().objects.create_superuser('admin',password='synthetic')
    reviewer=get_user_model().objects.create_user('reviewer')
    change_reviewer(admin,reviewer.username,True,None,'grant')
    category=Category.objects.create(name='Review',slug='review')
    return a,b,admin,reviewer,category

def recommend(user,source,category,key='recommend'):
    return client(user).post('/api/me/rss-recommendations/',{'source_id':source,'name':'Example feed','category_id':category.pk,'language':'en','note':'Useful feed','confirm_public_scope':True},format='json',HTTP_IDEMPOTENCY_KEY=key)

def decision(user,candidate,version=1,key='decision',action='approve',reason=''):
    return client(user).post(f'/api/admin/rss/recommendations/{candidate}/decisions/',{'action':action,'expected_version':version,'reason':reason},format='json',HTTP_IDEMPOTENCY_KEY=key)

def test_shared_candidate_with_one_withdrawn_submission(review_people):
    a,b,admin,reviewer,category=review_people
    first=subscribe(a); subscribe(b); connect_pending()
    r1=recommend(a,first.data['source_id'],category); r2=recommend(b,first.data['source_id'],category)
    assert r1.status_code==r2.status_code==202
    assert r1.data['candidate_id']==r2.data['candidate_id']
    assert PublicFeedCandidate.objects.count()==1
    withdrawal=client(a).post(f"/api/me/rss-recommendations/{r1.data['submission_id']}/actions/",{'action':'withdraw','expected_version':1},format='json',HTTP_IDEMPOTENCY_KEY='withdraw')
    assert withdrawal.status_code==200
    assert PublicFeedSubmission.objects.filter(withdrawn_at__isnull=True).count()==1
    assert 'user_id' not in str(client(b).get('/api/me/rss-recommendations/').data)
    assert decision(reviewer,r2.data['candidate_id']).status_code==200

def test_reviewer_cannot_review_any_candidate_they_submitted(review_people):
    a,b,admin,reviewer,category=review_people
    first=subscribe(reviewer); connect_pending()
    response=recommend(reviewer,first.data['source_id'],category)
    assert response.status_code==202
    assert decision(reviewer,response.data['candidate_id']).status_code==403
    assert decision(admin,response.data['candidate_id']).status_code==200

def test_approval_is_versioned_and_rejection_requires_reason(review_people):
    a,b,admin,reviewer,category=review_people
    first=subscribe(a); connect_pending()
    r=recommend(a,first.data['source_id'],category)
    assert decision(reviewer,r.data['candidate_id'],version=2).status_code==409
    assert decision(reviewer,r.data['candidate_id'],action='reject').status_code==400
    assert decision(reviewer,r.data['candidate_id'],action='reject',reason='Duplicate').status_code==200
    assert decision(reviewer,r.data['candidate_id'],action='approve').status_code==409

def test_registration_replay_reuses_candidate_or_existing_public_source(review_people):
    a,b,admin,reviewer,category=review_people
    data={'feed_url':'https://example.com/new/feed','name':'New public','category_id':category.pk,'language':'en'}
    first=client(admin).post('/api/admin/rss/sources/',data,format='json',HTTP_IDEMPOTENCY_KEY='create')
    assert first.status_code==202
    again=client(admin).post('/api/admin/rss/sources/',data,format='json',HTTP_IDEMPOTENCY_KEY='create')
    assert again.status_code==202 and again.data['candidate_id']==first.data['candidate_id']
    assert FeedBinding.objects.count()==1
    assert client(reviewer).post('/api/admin/rss/sources/',data,format='json',HTTP_IDEMPOTENCY_KEY='deny').status_code==403
    assert PublicFeedCandidate.objects.get().state=='approved'

def test_restricted_source_and_token_feed_are_rejected(review_people):
    a,b,admin,reviewer,category=review_people
    for url in ['https://example.com/feed?token=secret','http://127.0.0.1/feed','https://www.leiphone.com/feed']:
        response=client(admin).post('/api/admin/rss/sources/',{'feed_url':url,'name':'Unsafe','category_id':category.pk,'language':'en'},format='json',HTTP_IDEMPOTENCY_KEY=url)
        assert response.status_code in {400,403}
    assert FeedBinding.objects.count()==0

def test_review_permission_csrf_and_read_only(review_people,settings):
    from rest_framework.test import APIClient
    a,b,admin,reviewer,category=review_people
    assert client(a).get('/api/admin/rss/recommendations/').status_code==403
    assert client(reviewer).get('/api/admin/rss/recommendations/').status_code==200
    assert client(reviewer).get('/api/admin/rss/reviewers/').status_code==403
    csrf=APIClient(enforce_csrf_checks=True); csrf.force_login(admin)
    assert csrf.post('/api/admin/rss/reviewers/',{},format='json').status_code==403
    settings.PUBLIC_SITE_MODE='read_only'
    assert client(admin).post('/api/admin/rss/reviewers/',{},format='json').status_code==403

def test_candidate_technical_verification_keeps_self_review_and_versions(review_people):
    a,b,admin,reviewer,category=review_people
    first=subscribe(a); connect_pending()
    r=recommend(a,first.data['source_id'],category)
    path=f"/api/admin/rss/recommendations/{r.data['candidate_id']}/verification/"
    assert client(a).post(path,{'expected_version':1},format='json',HTTP_IDEMPOTENCY_KEY='no').status_code==403
    assert client(reviewer).post(path,{'expected_version':99},format='json',HTTP_IDEMPOTENCY_KEY='stale').status_code==409
    assert client(reviewer).post(path,{'expected_version':1},format='json',HTTP_IDEMPOTENCY_KEY='verify').status_code in {202,429}

def test_rejected_recommendation_can_be_corrected_and_resubmitted(review_people):
    a,b,admin,reviewer,category=review_people
    first=subscribe(a); connect_pending()
    r=recommend(a,first.data['source_id'],category)
    assert r.data['personal_source_id']==first.data['source_id']
    rejection=decision(reviewer,r.data['candidate_id'],action='reject',reason='Please clarify')
    assert rejection.status_code==200
    data={'action':'resubmit','expected_version':rejection.data['version'],'source_id':first.data['source_id'],'name':'Corrected','category_id':category.pk,'language':'en','note':'Clarified','confirm_public_scope':True}
    response=client(a).post(f"/api/me/rss-recommendations/{r.data['submission_id']}/actions/",data,format='json',HTTP_IDEMPOTENCY_KEY='resubmit')
    assert response.status_code==200 and response.data['state']=='pending' and response.data['version']>1
    candidate=PublicFeedCandidate.objects.get(pk=r.data['candidate_id'])
    assert candidate.decision_id is None and candidate.name=='Corrected'

def test_first_decision_invalidates_other_reviewer_version(review_people):
    a,b,admin,reviewer,category=review_people
    first=subscribe(a); connect_pending()
    r=recommend(a,first.data['source_id'],category)
    accepted=decision(reviewer,r.data['candidate_id'])
    assert accepted.status_code==200
    assert decision(admin,r.data['candidate_id'],action='reject',reason='Stale review',key='other').status_code==409
