from api.tests.rss.legacy_fixtures import legacy_news, public_legacy
from api.tests.rss.reader_fixtures import public_legacy_article
from django.http import Http404
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from django.contrib.auth.models import User, Permission, Group, AnonymousUser
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import Category, News, Source
from api.serializers import NewsDetailSerializer, NewsListSerializer
from api.services.body_access import can_view_article_body, body_fetch_scope
from api.services.full_content_status import fetch_eligibility, enqueue_fetch, claim_fetch
from api.services.source_policy import POLICIES, html_candidate_contract_allows

@pytest.fixture
def story(db):
    p = POLICIES['energy_storage_news']
    source = Source.objects.update_or_create(name=p.name, defaults={'url':'https://'+p.domains[0]})[0]
    category = Category.objects.create(name='Body access test', slug='body-access-test')
    return public_legacy_article(legacy_news(title='Body access article', content='Public summary', source=source, category=category,
        url='https://'+p.domains[0]+'/body-access-story/', publish_time=timezone.now(), content_kind='article',
        full_content='Existing real body', full_content_zh='Existing translated body', full_content_state='complete'))

def data(story, user, cls=NewsDetailSerializer):
    return cls(story, context={'request':SimpleNamespace(user=user)}).data

def test_superuser_reads_existing_body(story):
    user=User.objects.create(username='admin',is_superuser=True)
    d=data(story,user)
    assert d['reading_policy']=='standard'
    assert d['body_access_granted'] and d['can_fetch_full_content'] and d['has_full_content']
    assert d['full_content']=='Existing real body' and d['full_content_zh']=='Existing translated body'
    assert data(story,user,NewsListSerializer)['has_full_content']

@pytest.mark.parametrize('kind',['anonymous','ordinary','staff','inactive'])
def test_restricted_body_remains_hidden(story,kind):
    user=AnonymousUser() if kind=='anonymous' else User.objects.create(username=kind,is_staff=kind=='staff',is_superuser=kind=='inactive',is_active=kind!='inactive')
    if kind == 'inactive':
        with pytest.raises(Http404):
            data(story, user)
        return
    d=data(story,user)
    assert not d['body_access_granted'] and not d['has_full_content'] and not d['can_fetch_full_content']
    assert d['full_content']==d['full_content_zh']==''

@pytest.mark.parametrize('group',[False,True])
def test_grant_permission_to_other_users(story,group):
    user=User.objects.create(username='granted')
    permission=Permission.objects.get(content_type__app_label='api',codename='view_article_body')
    if group:
        g=Group.objects.create(name='Body readers');g.permissions.add(permission);user.groups.add(g)
    else:user.user_permissions.add(permission)
    assert can_view_article_body(user) and data(story,user)['full_content']=='Existing real body'

def test_cached_fetch_does_not_enqueue(story):
    user=User.objects.create(username='cached',is_superuser=True)
    client=APIClient();client.force_authenticate(user)
    with patch('api.views.request_full_content') as enqueue:
        response=client.post(f'/api/news/{story.pk}/fetch-full/',{},format='json')
    assert response.status_code==200 and response.data['full_content']=='Existing real body'
    enqueue.assert_not_called()

def test_queue_checks_revoked_permission_and_is_idempotent(story):
    user=User.objects.create(username='queue',is_superuser=True)
    story.full_content='';story.full_content_state='missing';story.full_content_fetch_status='unsupported';story.full_content_requested_by=user;story.save()
    assert fetch_eligibility(story,privileged=False)=='unsupported' and fetch_eligibility(story)==''
    assert enqueue_fetch(story)=='queued' and enqueue_fetch(story)=='reused'
    user.is_superuser=False;user.save();story=News.objects.get(pk=story.pk)
    assert fetch_eligibility(story)=='permission_revoked' and claim_fetch(story) is None

def test_source_and_identity_limits_remain(story):
    for url,kind in [('https://www.reuters.com/world/story/','article'),('https://example.org/unknown/story/','article'),(story.url,'abstract'),('http://localhost/private','article')]:
        story.url=url;story.content_kind=kind
        assert fetch_eligibility(story,privileged=True)

def test_contract_override_is_scoped_and_rejects_mismatch(story):
    story.full_content_requested_by=User.objects.create(username='contract',is_superuser=True)
    c=SimpleNamespace(target_url=story.url,retrieved_from_url=story.url,content_kind='article',source_key='energy_storage_news',body_field='article_html',content_format='html')
    assert not html_candidate_contract_allows(c)
    with body_fetch_scope(story):
        assert html_candidate_contract_allows(c)
        c.retrieved_from_url='https://evil.example/different'
        assert not html_candidate_contract_allows(c)
    c.retrieved_from_url=story.url
    assert not html_candidate_contract_allows(c)

def test_ordinary_cannot_forge_access_or_reuse_admin_fetch_intent(story):
    admin=User.objects.create(username='owner',is_superuser=True)
    ordinary=User.objects.create(username='intruder')
    story.full_content_requested_by=admin;story.save()
    client=APIClient();client.force_authenticate(ordinary)
    with patch('api.views.request_full_content') as enqueue:
        response=client.post(f'/api/news/{story.pk}/fetch-full/',{'body_access_granted':True,'full_content_requested_by':admin.pk},format='json')
    assert response.status_code==403
    story.refresh_from_db()
    assert story.full_content_requested_by_id == admin.pk
    enqueue.assert_not_called()

def test_missing_body_request_records_actor_and_can_queue(story):
    admin=User.objects.create(username='requester',is_superuser=True)
    story.full_content='';story.full_content_state='missing';story.full_content_fetch_status='unsupported';story.save()
    client=APIClient();client.force_authenticate(admin)
    with patch('api.services.article_content.worker_health',return_value=True):
        response=client.post(f'/api/news/{story.pk}/fetch-full/',{},format='json')
    assert response.status_code==202
    story.refresh_from_db()
    assert story.full_content_requested_by_id==admin.pk and story.full_content_fetch_status=='queued'
    with patch('api.services.article_content.worker_health',return_value=True):
        again=client.post(f'/api/news/{story.pk}/fetch-full/',{},format='json')
    assert again.status_code==202 and story.full_content_retry_count==0

def test_full_content_filter_and_badge_follow_reader_permission(story):
    client=APIClient()
    ordinary=User.objects.create(username='filter-reader')
    admin=User.objects.create(username='filter-admin',is_superuser=True)
    for user,visible in [(ordinary,False),(admin,True)]:
        client.force_authenticate(user)
        response=client.get('/api/news/',{'full_content':'true','search':'Body access article','mode':'keyword'})
        assert response.status_code==200
        ids=[row['id'] for row in response.data['results']]
        assert (story.pk in ids)==visible
        if visible:
            assert next(row for row in response.data['results'] if row['id']==story.pk)['has_full_content']
