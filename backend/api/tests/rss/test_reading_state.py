import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Category, News, Source, SourcePublication, ChannelSubscription
from api.rss.reading_models import NewsReadState
from api.smart_channel_models import ReadingDay

pytestmark = pytest.mark.django_db


@pytest.fixture
def story(settings):
    settings.PUBLIC_SITE_MODE = 'full'
    source = Source.objects.create(name='Read state fixture', url='https://example.test/')
    SourcePublication.objects.create(source=source, publication='personal', owner='paused')
    news = News.objects.create(source=source, category=Category.objects.create(name='Reading', slug='reading'),
        title='Stored story', content='Summary', url='https://example.test/story', publish_time=timezone.now())
    a = get_user_model().objects.create_user('reader-a', password='test-password')
    b = get_user_model().objects.create_user('reader-b')
    ChannelSubscription.objects.create(user=a, source=source)
    ChannelSubscription.objects.create(user=b, source=source)
    return news, a, b


def client(user):
    result = APIClient()
    result.force_authenticate(user)
    return result


def path(news):
    return f'/api/me/news/{news.pk}/read-state/'


def test_personal_state_and_reading_analytics_are_independent(story):
    news, a, b = story
    ReadingDay.objects.create(user=a, news=news, day=timezone.localdate())
    before = list(ReadingDay.objects.values())
    ca, cb = client(a), client(b)
    assert ca.get(path(news)).data == {'is_read': False, 'version': 0}
    assert NewsReadState.objects.count() == 0  # GET never creates a row.
    response = ca.patch(path(news), {'is_read': True, 'expected_version': 0}, format='json')
    assert response.status_code == 200
    assert response.data == {'is_read': True, 'version': 1}
    assert response['Cache-Control'] == 'private, no-store'
    assert cb.get(path(news)).data == {'is_read': False, 'version': 0}
    assert list(ReadingDay.objects.values()) == before
    news.full_content = 'Changed body'
    news.save(update_fields=['full_content'])
    assert ca.get(path(news)).data == {'is_read': True, 'version': 1}
    subscription = ChannelSubscription.objects.get(user=a, source=news.source)
    subscription.delete()
    assert ca.get(path(news)).status_code == 404
    assert ca.patch(path(news), {'is_read': False}, format='json').status_code == 404
    assert NewsReadState.objects.get(user=a, news=news).is_read
    ChannelSubscription.objects.create(user=a, source=news.source)
    assert ca.get(path(news)).data == {'is_read': True, 'version': 1}


def test_version_conflicts_and_idempotent_desired_state(story):
    news, a, _ = story
    ca = client(a)
    assert ca.patch(path(news), {'is_read': True}, format='json').data['version'] == 1
    assert ca.patch(path(news), {'is_read': True, 'expected_version': 1}, format='json').data['version'] == 1
    response = ca.patch(path(news), {'is_read': False, 'expected_version': 0}, format='json')
    assert response.status_code == 409 and response.data['error']['code'] == 'stale'
    assert response.data['request_id']
    assert ca.patch(path(news), {'is_read': False, 'expected_version': 1}, format='json').data == {'is_read': False, 'version': 2}


@pytest.mark.parametrize('data', [{'is_read': 'true'}, {'is_read': True, 'expected_version': True},
    {'is_read': True, 'expected_version': -1}, {'is_read': True, 'user_id': 999}, [], {}])
def test_strict_input(story, data):
    news, a, _ = story
    response = client(a).patch(path(news), data, format='json')
    assert response.status_code == 400 and isinstance(response.data['error'], dict)
    assert NewsReadState.objects.count() == 0


def test_session_csrf_anonymous_and_read_only(story, settings):
    news, a, _ = story
    response = APIClient().get(path(news))
    assert response.status_code == 401 and response.data['error']['code'] == 'not_authenticated'
    csrf_client = APIClient(enforce_csrf_checks=True)
    csrf_client.force_login(a)
    assert csrf_client.patch(path(news), {'is_read': True}, format='json').status_code == 403
    csrf_client.get('/api/auth/csrf/')
    token = csrf_client.cookies['csrftoken'].value
    assert csrf_client.patch(path(news), {'is_read': True}, format='json', HTTP_X_CSRFTOKEN=token).status_code == 200
    settings.PUBLIC_SITE_MODE = 'read_only'
    response = csrf_client.patch(path(news), {'is_read': False}, format='json', HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'public_read_only'
    assert response['Cache-Control'] == 'private, no-store'
