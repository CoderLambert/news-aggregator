"""NH-16: applications remain inert, owner-scoped and free of stored credentials."""
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from api.models import Source, ChannelSubscription
from api.smart_channel_models import ChannelIntakeRequest
from api.services.channel_intake import normalize_intake_url, review_intake, IntakeConflict
from rest_framework.exceptions import ValidationError


@pytest.fixture(autouse=True)
def intake_settings(settings):
    settings.PUBLIC_SITE_MODE = 'full'
    cache.clear()


@pytest.fixture
def actors(db):
    User = get_user_model()
    owner = User.objects.create_user('intake-owner')
    other = User.objects.create_user('intake-other')
    admin = User.objects.create_user('intake-admin', is_superuser=True, is_staff=True)
    return owner, other, admin


@pytest.mark.parametrize('url', [
    'https://publisher.example/feed?apiKey=synthetic',
    'https://publisher.example/feed?%74oken=synthetic',
    'https://publisher.example/feed?x-amz-signature=synthetic',
    'https://publisher.example/feed?redirect=https%3A%2F%2Fother.example%2F%3Ftoken%3Dsynthetic',
    'https://publisher.example/feed?format=%2574oken%253Dsynthetic',
    'https://user:synthetic@publisher.example/feed',
    'http://127.0.0.1/feed', 'https://metadata.google.internal/feed',
])
def test_intake_rejects_credentials_before_echo_or_storage(actors, url):
    owner, _, _ = actors
    client = APIClient(); client.force_authenticate(owner)
    before = ChannelIntakeRequest.objects.count()
    for endpoint in ('/api/smart-channels/resolve/', '/api/me/smart-channels/intake/'):
        response = client.post(endpoint, {'url': url}, format='json')
        assert response.status_code == 400
        assert 'synthetic' not in str(response.data)
    assert ChannelIntakeRequest.objects.count() == before


def test_application_review_is_idempotent_and_does_not_enable_crawling(actors):
    owner, other, admin = actors
    client = APIClient(); client.force_authenticate(owner)
    sources, subscriptions = Source.objects.count(), ChannelSubscription.objects.count()
    created = client.post('/api/me/smart-channels/intake/', {'url': 'https://publisher.example/rss'}, format='json')
    assert created.status_code == 201
    pk = created.data['id']
    endpoint = f'/api/admin/smart-channels/intake/{pk}/'
    assert client.post(endpoint, {'decision': 'approved', 'reason': 'review'}, format='json').status_code == 403
    client.force_authenticate(other)
    history = client.get('/api/me/smart-channels/intake/history/')
    assert history.status_code == 200 and history.data['count'] == 0
    assert client.get('/api/admin/smart-channels/intake/').status_code == 403
    client.force_authenticate(admin)
    response = client.post(endpoint, {'decision': 'approved', 'reason': '需要单独核验来源许可'}, format='json')
    assert response.status_code == 200 and response.data['activation_status'] == 'not_enabled'
    stamp = ChannelIntakeRequest.objects.get(pk=pk).reviewed_at
    assert client.post(endpoint, {'decision': 'approved', 'reason': '需要单独核验来源许可'}, format='json').status_code == 200
    assert ChannelIntakeRequest.objects.get(pk=pk).reviewed_at == stamp
    assert client.post(endpoint, {'decision': 'rejected', 'reason': 'conflict'}, format='json').status_code == 409
    client.force_authenticate(owner)
    row = client.get('/api/me/smart-channels/intake/history/').data['results'][0]
    assert row['status'] == 'approved' and row['review_reason'] == '需要单独核验来源许可'
    assert Source.objects.count() == sources and ChannelSubscription.objects.count() == subscriptions


def test_legacy_sensitive_application_is_not_exposed_to_owner_or_admin(actors):
    owner, _, admin = actors
    row = ChannelIntakeRequest.objects.create(user=owner, url='https://publisher.example/rss?token=synthetic-private')
    client = APIClient()
    for user, endpoint in ((owner, '/api/me/smart-channels/intake/history/'), (admin, '/api/admin/smart-channels/intake/')):
        client.force_authenticate(user)
        data = client.get(endpoint).data
        assert 'synthetic-private' not in str(data)
        assert data['results'][0]['url_safe'] is False
    with pytest.raises(ValidationError):
        review_intake(admin, row.pk, 'approved', 'cannot accept a private URL')
    reviewed = review_intake(admin, row.pk, 'rejected', '请提交无凭据的公开地址')
    assert reviewed.status == 'rejected'


def test_review_rejects_empty_reason_and_read_only_mode(actors):
    owner, _, admin = actors
    row = ChannelIntakeRequest.objects.create(user=owner, url='https://publisher.example/rss')
    client = APIClient(); client.force_authenticate(admin)
    endpoint = f'/api/admin/smart-channels/intake/{row.pk}/'
    assert client.post(endpoint, {'decision': 'approved', 'reason': ''}, format='json').status_code == 400
    with override_settings(PUBLIC_SITE_MODE='read_only'):
        assert client.post(endpoint, {'decision': 'approved', 'reason': 'review'}, format='json').status_code == 403
    row.refresh_from_db(); assert row.status == 'pending'


def test_canonical_public_filter_and_duplicate_submission(actors):
    owner, _, _ = actors
    client = APIClient(); client.force_authenticate(owner)
    url = 'https://publisher.example/rss?format=rss&lang=en'
    first = client.post('/api/me/smart-channels/intake/', {'url': url}, format='json')
    second = client.post('/api/me/smart-channels/intake/', {'url': url}, format='json')
    assert first.status_code == 201 and second.status_code == 200
    assert first.data['id'] == second.data['id']
    assert normalize_intake_url(url)[3] == 'format=rss&lang=en'
