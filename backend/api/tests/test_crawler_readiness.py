"""NH-21 readiness must be read-only, role gated, and truthful about idle."""
from datetime import timedelta
import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import CrawlerSettings, CrawlerTarget, FeedState
from api.services.crawler_readiness import readiness_snapshot


@pytest.mark.django_db
def test_readiness_get_creates_no_settings_or_targets():
    user = User.objects.create_user(username='readiness-admin', is_superuser=True, is_staff=True)
    client = APIClient()
    assert client.get('/api/admin/crawler/readiness/').status_code == 403
    client.force_login(user)
    result = client.get('/api/admin/crawler/readiness/')
    assert result.status_code == 200
    assert 'sources' in result.json()
    assert CrawlerSettings.objects.count() == 0
    assert CrawlerTarget.objects.count() == 0


@pytest.mark.django_db
def test_normal_staff_cannot_read_admin_worker_metadata():
    user = User.objects.create_user(username='readiness-staff', is_staff=True)
    client = APIClient()
    client.force_login(user)
    assert client.get('/api/admin/crawler/readiness/').status_code == 403


@pytest.mark.django_db
def test_scheduled_idle_and_worker_missing_are_not_reported_as_success():
    now = timezone.now()
    CrawlerSettings.objects.create(id=1, scheduler_enabled=True, worker_heartbeat_at=now)
    CrawlerTarget.objects.create(spider_name='bbc', display_name='BBC', enabled=True)
    FeedState.objects.create(source_key='bbc', feed_url='https://feeds.bbci.co.uk/news/rss.xml',
                             last_success_at=now, next_poll_at=now + timedelta(minutes=50))
    result = readiness_snapshot()
    state = next(x for x in result['sources'] if x['source_key'] == 'bbc')
    assert result['workers']['crawler']['online'] is True
    assert state['state'] == 'waiting_poll'
    CrawlerSettings.objects.filter(pk=1).update(worker_heartbeat_at=now - timedelta(minutes=10))
    result = readiness_snapshot()
    assert next(x for x in result['sources'] if x['source_key'] == 'bbc')['state'] == 'worker_offline'


@pytest.mark.django_db
def test_status_is_plain_codes_and_never_leaks_credentials():
    CrawlerTarget.objects.create(spider_name='bbc', display_name='BBC', last_safe_error='secret-should-not-escape')
    response = readiness_snapshot()
    assert 'secret-should-not-escape' not in repr(response)
    assert all('url' not in row for row in response['sources'])
