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
from api.services.source_policy import POLICIES
from api.serializers import NewsDetailSerializer, NewsListSerializer
from api.services.body_access import can_view_article_body

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
    assert d['body_access_granted'] and not d['can_fetch_full_content'] and d['has_full_content']
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
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')) as enqueue:
        response=client.post(f'/api/news/{story.pk}/fetch-full/',{},format='json')
    assert response.status_code==410
    assert client.get(f'/api/news/{story.pk}/').data['full_content']=='Existing real body'
    enqueue.assert_not_called()




def test_ordinary_cannot_forge_access_or_reuse_admin_fetch_intent(story):
    admin=User.objects.create(username='owner',is_superuser=True)
    ordinary=User.objects.create(username='intruder')
    story.full_content_requested_by=admin;story.save()
    client=APIClient();client.force_authenticate(ordinary)
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')) as enqueue:
        response=client.post(f'/api/news/{story.pk}/fetch-full/',{'body_access_granted':True,'full_content_requested_by':admin.pk},format='json')
    assert response.status_code==410
    story.refresh_from_db()
    assert story.full_content_requested_by_id == admin.pk
    enqueue.assert_not_called()

def test_missing_body_cannot_create_retired_actor_or_queue(story):
    admin=User.objects.create(username='requester',is_superuser=True)
    story.full_content='';story.full_content_state='missing';story.full_content_fetch_status='unsupported';story.save()
    client=APIClient();client.force_authenticate(admin)
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')):
        response=client.post(f'/api/news/{story.pk}/fetch-full/',{},format='json')
    assert response.status_code==410
    story.refresh_from_db()
    assert story.full_content_requested_by_id is None and story.full_content_fetch_status=='unsupported'
    with patch('socket.socket.connect', side_effect=AssertionError('publisher IO')):
        again=client.post(f'/api/news/{story.pk}/fetch-full/',{},format='json')
    assert again.status_code==410 and story.full_content_retry_count==0

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
