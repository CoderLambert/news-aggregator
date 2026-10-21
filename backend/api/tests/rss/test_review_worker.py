"""Publication requires both current approval and a fenced verified connection."""
from dataclasses import asdict
from datetime import timedelta
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from api.models import Category, Source, News
from api.rss.models import FeedOperation, FeedBinding, SourcePublication, SourceFeedLink, EngineEntryMap
from api.rss.review_models import PublicFeedCandidate
from api.rss.operations import effective_references, OperationError
from api.rss.engine import EngineConfig, EntryDTO
from api.rss.control_worker import ControlWorker
from api.tests.rss.test_admin_recovery import admin, Engine, run, INSTANCE
from api.tests.rss.test_subscriptions import client

pytestmark=pytest.mark.django_db(transaction=True)

def register(user,key='new'):
    category,_=Category.objects.get_or_create(name='Publish',defaults={'slug':'publish'})
    result=client(user).post('/api/admin/rss/sources/',{'feed_url':'https://example.com/new/feed','name':'New','category_id':category.pk,'language':'en'},format='json',HTTP_IDEMPOTENCY_KEY=key)
    assert result.status_code==202
    return PublicFeedCandidate.objects.get(pk=result.data['candidate_id'])

def test_both_orders_of_approval_and_connection_publish_once(admin):
    from api.rss.public_membership import process_approved_candidates
    user,_=admin
    candidate=register(user)
    assert effective_references(candidate.binding_id)
    process_approved_candidates()
    candidate.refresh_from_db(); assert candidate.public_source_id is None
    engine=Engine(); run(engine)
    process_approved_candidates(); process_approved_candidates()
    candidate.refresh_from_db()
    assert engine.creates==1 and candidate.state=='published'
    assert Source.objects.filter(publication__requires_public_membership=True).count()==1
    assert candidate.public_source.publication.requires_public_membership

def test_revoked_regranted_authority_cannot_commit_old_response(admin):
    from api.rss.review_permissions import change_reviewer, review_authority
    user,_=admin
    candidate=register(user)
    reviewer=get_user_model().objects.create_user('delegated')
    change_reviewer(user,reviewer.username,True,None,'grant')
    authority=asdict(review_authority(reviewer))
    candidate.decision.actor=reviewer; candidate.decision.authority=authority; candidate.decision.save()
    op=FeedOperation.objects.get(binding=candidate.binding,actor=user)
    inputs=op.safe_input; inputs['review_target']['authority']=authority
    FeedOperation.objects.filter(pk=op.pk).update(actor=reviewer,safe_input=inputs)
    worker=ControlWorker(EngineConfig(INSTANCE,3,'http://127.0.0.1:1','synthetic'),adapter_factory=Engine)
    try:
        request=worker.prepare(worker.claim_next())
        assert request.claim.operation_id == op.pk
        change_reviewer(user,reviewer.username,False,1,'revoke')
        change_reviewer(user,reviewer.username,True,2,'regrant')
        with pytest.raises(OperationError): worker._dispatch(request)
    finally: worker.close()
    candidate.refresh_from_db(); assert candidate.public_source_id is None

def test_unapproved_candidate_is_not_a_collection_reference(admin):
    user,_=admin
    candidate=register(user)
    PublicFeedCandidate.objects.filter(pk=candidate.pk).update(state='pending',decision=None)
    assert not effective_references(candidate.binding_id)

def test_bounded_initial_members_read_uses_engine_storage_only(admin):
    from api.rss.public_membership import process_approved_candidates, prepare_public_member, finish_public_member
    from api.rss.access import authorized_news
    from django.contrib.auth.models import AnonymousUser
    user,_=admin; candidate=register(user); run(Engine()); process_approved_candidates(); candidate.refresh_from_db()
    private=Source.objects.create(name='Private',url='https://example.com/')
    SourcePublication.objects.create(source=private,publication='personal',owner='miniflux',reading_policy='standard')
    SourceFeedLink.objects.create(source=private,binding=candidate.binding,enabled=True)
    news=News.objects.create(source=private,category=candidate.category,title='Article',content='Public feed summary',url='https://example.com/article',publish_time=timezone.now())
    mapping=EngineEntryMap.objects.create(binding=candidate.binding,engine_entry_id=99,news=news,source_url=news.url,disposition='linked')
    token=prepare_public_member()
    assert token['entry_id']==99
    dto=EntryDTO(INSTANCE,3,77,99,'Article',news.url,None,'','<p>Public feed summary</p>',timezone.now().isoformat(),timezone.now().isoformat())
    finish_public_member(token,dto,reserve=lambda:None)
    assert authorized_news(AnonymousUser()).filter(pk=news.pk).exists()
    assert candidate.binding.published_since==FeedBinding.objects.get(pk=candidate.binding_id).published_since

def test_blocked_oldest_approval_cannot_starve_ready_candidate(admin):
    from api.rss.public_membership import process_approved_candidates
    user,_=admin
    blocked=register(user,'blocked'); run(Engine())
    PublicFeedCandidate.objects.filter(pk=blocked.pk).update(updated_at=timezone.now()-timedelta(days=1))
    FeedBinding.objects.filter(pk=blocked.binding_id).update(connection_state='paused')
    category=blocked.category
    ready=client(user).post('/api/admin/rss/sources/',{'feed_url':'https://example.com/ready/feed','name':'Ready','category_id':category.pk,'language':'en'},format='json',HTTP_IDEMPOTENCY_KEY='ready')
    assert ready.status_code==202
    candidate=PublicFeedCandidate.objects.get(pk=ready.data['candidate_id'])
    # A distinct confirmed feed, with its control request conclusively finished.
    FeedOperation.objects.filter(binding=candidate.binding).update(state='succeeded')
    FeedBinding.objects.filter(pk=candidate.binding_id).update(engine_feed_id=78,connection_state='ready',applied_policy_version=candidate.binding.policy_version)
    for _ in range(3): process_approved_candidates(limit=1)
    candidate.refresh_from_db(); assert candidate.state=='published'

def test_initial_fill_skips_known_old_history_and_rotates_candidates(admin):
    from api.rss.public_membership import process_approved_candidates,prepare_public_member
    user,_=admin; candidate=register(user); run(Engine()); process_approved_candidates(); candidate.refresh_from_db()
    private=Source.objects.create(name='Stored history',url='https://example.com/')
    for n in range(1,31):
        news=News.objects.create(source=private,category=candidate.category,title='Old',content='Old',url=f'https://example.com/old/{n}',publish_time=timezone.now()-timedelta(days=30))
        EngineEntryMap.objects.create(binding=candidate.binding,engine_entry_id=n,news=news,source_url=news.url,disposition='linked')
    recent=News.objects.create(source=private,category=candidate.category,title='Recent',content='Recent',url='https://example.com/recent',publish_time=timezone.now())
    EngineEntryMap.objects.create(binding=candidate.binding,engine_entry_id=99,news=recent,source_url=recent.url,disposition='linked')
    assert prepare_public_member()['entry_id']==99


def test_system_convergence_rechecks_revoked_review_reference_before_dispatch(admin):
    from api.rss.review_permissions import change_reviewer, review_authority
    user,_=admin
    candidate=register(user)
    reviewer=get_user_model().objects.create_user('system-delegated')
    change_reviewer(user,reviewer.username,True,None,'grant-system')
    candidate.decision.actor=reviewer
    candidate.decision.authority=asdict(review_authority(reviewer))
    candidate.decision.save()
    # Only the system convergence task remains; the independent approved
    # candidate still holds a valid collection reference at preparation time.
    FeedOperation.objects.filter(binding=candidate.binding,actor=user).update(state='cancelled')
    worker=ControlWorker(EngineConfig(INSTANCE,3,'http://127.0.0.1:1','synthetic'),adapter_factory=Engine)
    try:
        request=worker.prepare(worker.claim_next())
        operation=FeedOperation.objects.get(pk=request.claim.operation_id)
        assert operation.actor_id is None and effective_references(candidate.binding_id)
        change_reviewer(user,reviewer.username,False,1,'revoke-system')
        change_reviewer(user,reviewer.username,True,2,'regrant-system')
        assert not effective_references(candidate.binding_id)
        with pytest.raises(OperationError):
            worker._dispatch(request)
        operation.refresh_from_db()
        assert operation.execution_phase == 'not_sent' and operation.dispatched_at is None
    finally:
        worker.close()
