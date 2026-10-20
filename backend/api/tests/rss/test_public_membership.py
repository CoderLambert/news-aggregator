"""A new public link never publishes the whole shared personal feed history."""
import uuid
from datetime import timedelta
import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.utils import timezone
from api.models import Category, News, Source, ChannelSubscription
from api.rss.models import FeedBinding, SourcePublication, SourceFeedLink, EngineEntryMap
from api.rss.review_models import PublicFeedCandidate, PublicFeedEntry
from api.rss.access import authorized_news, get_stored_article, article_sources, with_authorized_source_counts, prepare_article_previews
from api.tests.rss.test_subscriptions import people

pytestmark=pytest.mark.django_db(transaction=True)

@pytest.fixture
def shared(people):
    a,b=people
    from api.rss.subscriptions import engine_identity
    instance,account=engine_identity()
    binding=FeedBinding.objects.create(engine_instance_uuid=instance,account_id=account,engine_feed_id=7,canonical_feed_url='https://example.com/feed',connection_state='ready',desired_enabled=True,applied_policy_version=1)
    private=Source.objects.create(name='Private',url='https://example.com/')
    public=Source.objects.create(name='Public',url='https://example.com/')
    SourcePublication.objects.create(source=private,publication='personal',owner='miniflux',reading_policy='standard')
    SourcePublication.objects.create(source=public,publication='public',owner='miniflux',reading_policy='standard',requires_public_membership=True)
    SourceFeedLink.objects.create(source=private,binding=binding,enabled=True)
    SourceFeedLink.objects.create(source=public,binding=binding,enabled=True,editorial_pin=True)
    ChannelSubscription.objects.create(user=a,source=private)
    category=Category.objects.create(name='Members',slug='members')
    candidate=PublicFeedCandidate.objects.create(binding=binding,name='Public',category=category,public_source=public,state='published',scope_since=timezone.now()-timedelta(days=7))
    news=News.objects.create(source=private,category=category,title='Private history',content='Safe summary',full_content='Private stored body',full_content_state='available',url='https://example.com/article',publish_time=timezone.now(),body_owner_binding=binding,full_content_provenance={'owner':'miniflux','binding_id':str(binding.pk),'source_id':private.pk,'engine_instance_uuid':str(instance),'account_id':account,'engine_feed_id':7,'engine_entry_id':8})
    entry=EngineEntryMap.objects.create(binding=binding,engine_entry_id=8,news=news,source_url=news.url,disposition='linked')
    return a,b,private,public,candidate,news,entry

def test_public_link_does_not_grant_unlisted_history(shared):
    a,b,private,public,candidate,news,entry=shared
    assert authorized_news(a).filter(pk=news.pk).exists()
    for viewer in [b,AnonymousUser()]:
        assert not authorized_news(viewer).filter(pk=news.pk).exists()
        with pytest.raises(Http404): get_stored_article(viewer,news.pk)
        assert with_authorized_source_counts(viewer,Source.objects.filter(pk=public.pk)).get().rss_news_count==0
    # A public primary source also cannot bypass the explicit member requirement.
    News.objects.filter(pk=news.pk).update(source=public)
    assert not authorized_news(b).filter(pk=news.pk).exists()

def test_public_member_keeps_private_body_and_ai_history_private(shared):
    a,b,private,public,candidate,news,entry=shared
    PublicFeedEntry.objects.create(source=public,entry=entry,approval_version=1,evidence={'verified':True})
    assert get_stored_article(a,news.pk).scope=='full'
    assert get_stored_article(b,news.pk).scope=='summary'
    assert get_stored_article(b,news.pk).markdown=='Safe summary'
    assert list(article_sources(b,news).values_list('pk',flat=True))==[public.pk]
    assert with_authorized_source_counts(b,Source.objects.filter(pk=public.pk)).get().rss_news_count==1
    PublicFeedEntry.objects.all().delete()
    with pytest.raises(Http404): get_stored_article(b,news.pk)

def test_unknown_date_and_before_bound_never_become_public(shared):
    from api.rss.public_membership import record_public_entry
    a,b,private,public,candidate,news,entry=shared
    for evidence in [{},{'published_at':(timezone.now()-timedelta(days=10)).isoformat(),'verified':True},{'published_at':timezone.now().isoformat(),'verified':False}]:
        assert not record_public_entry(candidate.pk,entry.pk,expected_version=1,evidence=evidence)
    assert not PublicFeedEntry.objects.exists()

def test_member_version_and_preview_context_cannot_drift(shared):
    a,b,private,public,candidate,news,entry=shared
    PublicFeedEntry.objects.create(source=public,entry=entry,approval_version=1)
    snapshot=prepare_article_previews(b,[news])[news.pk]
    assert snapshot[0].source_ids==(public.pk,)
    PublicFeedCandidate.objects.filter(pk=candidate.pk).update(version=2)
    assert not authorized_news(b).filter(pk=news.pk).exists()

def test_public_editorial_evidence_excludes_unlisted_articles(shared):
    from api.services.channel_topics import channel_articles
    a,b,private,public,candidate,news,entry=shared
    News.objects.filter(pk=news.pk).update(source=public)
    assert not channel_articles(public).filter(pk=news.pk).exists()
    PublicFeedEntry.objects.create(source=public,entry=entry,approval_version=1)
    assert channel_articles(public).filter(pk=news.pk).exists()

def test_empty_current_summary_never_publishes_retained_private_text(shared):
    from api.rss.engine import EntryDTO
    from api.rss.sync import prepare_page, commit_entry
    a,b,private,public,candidate,news,entry=shared
    dto=EntryDTO(str(candidate.binding.engine_instance_uuid),candidate.binding.account_id,7,8,'Fresh',news.url,None,'','',timezone.now().isoformat(),timezone.now().isoformat())
    fence=prepare_page([dto],instance_uuid=candidate.binding.engine_instance_uuid,account_id=candidate.binding.account_id)[8]
    commit_entry(dto,fence,reserve=lambda:None)
    news.refresh_from_db()
    assert news.content=='Safe summary'
    assert not authorized_news(AnonymousUser()).filter(pk=news.pk).exists()

def test_public_category_applies_without_rewriting_private_category(shared):
    from api.services.channel_articles import category_filter
    a,b,private,public,candidate,news,entry=shared
    category=Category.objects.create(name='Reviewed category',slug='reviewed-category')
    PublicFeedCandidate.objects.filter(pk=candidate.pk).update(category=category)
    PublicFeedEntry.objects.create(source=public,entry=entry,approval_version=1)
    assert category_filter(authorized_news(b),[category.pk],actor=b).filter(pk=news.pk).exists()
    news.refresh_from_db(); assert news.category_id!=category.pk

def test_tightened_policy_denies_initial_member_without_crashing(shared):
    from unittest.mock import patch
    from api.rss.public_membership import prepare_public_member,finish_public_member
    from api.rss.operations import OperationError
    from api.rss.engine import EntryDTO
    a,b,private,public,candidate,news,entry=shared
    token=prepare_public_member()
    dto=EntryDTO(str(candidate.binding.engine_instance_uuid),candidate.binding.account_id,7,8,'Current',news.url,None,'','<p>Safe summary</p>',timezone.now().isoformat(),timezone.now().isoformat())
    with patch('api.rss.public_membership.assert_binding_policy',side_effect=OperationError('feed_policy_unapproved')):
        finish_public_member(token,dto,reserve=lambda:None)
    assert not PublicFeedEntry.objects.exists()
    candidate.refresh_from_db(); assert candidate.member_cursor==8

def test_initial_fill_rotates_between_candidates(shared):
    from api.rss.public_membership import prepare_public_member
    a,b,private,public,candidate,news,entry=shared
    other_binding=FeedBinding.objects.create(engine_instance_uuid=candidate.binding.engine_instance_uuid,account_id=candidate.binding.account_id,engine_feed_id=9,canonical_feed_url='https://example.com/other',connection_state='ready')
    other=PublicFeedCandidate.objects.create(binding=other_binding,name='Other',category=candidate.category,state='published',scope_since=candidate.scope_since)
    EngineEntryMap.objects.create(binding=other_binding,engine_entry_id=10,news=news,source_url=news.url,disposition='linked')
    PublicFeedCandidate.objects.filter(pk=candidate.pk).update(updated_at=timezone.now()-timedelta(days=1))
    assert prepare_public_member()['candidate_id']==str(candidate.pk)
    assert prepare_public_member()['candidate_id']==str(other.pk)
