import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from api.models import CrawlerTarget, Source, ChannelSubscription
from api.smart_channel_models import ChannelIntakeRequest
from api.services.channel_intake import normalize_intake_url, intake_data


@pytest.mark.parametrize('key', ['token', 'apiKey', 'auth', 'signature', 'X-Amz-Credential',
                                 'ACCESS_TOKEN', 'api_key', '%2574oken', 'redirect', 'unknown_secret'])
def test_private_query_keys_are_rejected_without_echoing_credentials(key):
    with pytest.raises(ValidationError) as exc:
        normalize_intake_url('https://example.com/feed?' + key + '=DO_NOT_STORE')
    assert 'DO_NOT_STORE' not in str(exc.value)


@pytest.mark.parametrize('url', ['https://user:pass@example.com/feed', 'http://127.0.0.1/feed',
                                'http://metadata.google.internal/feed', 'https://example.com/token/secret',
                                'https://example.com/feed#secret', 'https://example.com/%0dfeed'])
def test_private_or_malformed_address_is_not_admitted(url):
    with pytest.raises(ValidationError):
        normalize_intake_url(url)


def test_public_query_normalization_is_deterministic():
    assert normalize_intake_url('https://EXAMPLE.com/?lang=en&feed=rss2')[0] == 'https://example.com/?feed=rss2&lang=en'


@pytest.fixture
def people(db):
    User = get_user_model()
    return (User.objects.create_user('intake-reader'), User.objects.create_user('other-intake-reader'),
            User.objects.create_superuser('intake-admin', 'admin@example.com', 'fake-password'))


@override_settings(PUBLIC_SITE_MODE='full')
def test_submit_review_replay_and_owner_receipt_without_enabling_crawlers(people):
    user, other, admin = people
    client = APIClient()
    client.force_authenticate(user)
    initial = CrawlerTarget.objects.count(), Source.objects.count(), ChannelSubscription.objects.count()
    created = client.post('/api/me/smart-channels/intake/', {'url': 'https://example.com/feed'}, format='json')
    assert created.status_code == 201
    pk = created.data['id']
    client.force_authenticate(other)
    assert client.get('/api/me/smart-channels/intake/').data == []
    assert client.patch(f'/api/admin/smart-channels/intake/{pk}/', {}, format='json').status_code == 403
    client.force_authenticate(admin)
    payload = {'status': 'approved', 'reason': '允许接入，采集须单独配置', 'review_revision': 0}
    reviewed = client.patch(f'/api/admin/smart-channels/intake/{pk}/', payload, format='json')
    assert reviewed.status_code == 200 and reviewed.data['review_revision'] == 1
    assert client.patch(f'/api/admin/smart-channels/intake/{pk}/', payload, format='json').data == reviewed.data
    conflict = client.patch(f'/api/admin/smart-channels/intake/{pk}/', {**payload, 'status': 'rejected'}, format='json')
    assert conflict.status_code == 409
    client.force_authenticate(user)
    receipt = client.get('/api/me/smart-channels/intake/').data[0]
    assert receipt['status'] == 'approved' and receipt['reason'] == payload['reason']
    assert receipt['collection_enabled'] is False
    assert initial == (CrawlerTarget.objects.count(), Source.objects.count(), ChannelSubscription.objects.count())


@override_settings(PUBLIC_SITE_MODE='full')
def test_private_url_never_persists_and_legacy_url_never_leaks(people):
    user, _, admin = people
    client = APIClient()
    client.force_authenticate(user)
    url = 'https://example.com/feed?apiKey=DO_NOT_RETURN'
    response = client.post('/api/me/smart-channels/intake/', {'url': url}, format='json')
    assert response.status_code == 400 and ChannelIntakeRequest.objects.count() == 0
    legacy = ChannelIntakeRequest.objects.create(user=user, url=url)
    assert intake_data(legacy)['url'] == ''
    assert 'DO_NOT_RETURN' not in str(client.get('/api/me/smart-channels/intake/').data)
    client.force_authenticate(admin)
    assert 'DO_NOT_RETURN' not in str(client.get('/api/admin/smart-channels/').data)


@override_settings(PUBLIC_SITE_MODE='read_only')
def test_read_only_mode_does_not_create_intake(people):
    client = APIClient()
    client.force_authenticate(people[2])
    assert client.post('/api/me/smart-channels/intake/', {'url': 'https://example.com/feed'}, format='json').status_code == 403
    assert ChannelIntakeRequest.objects.count() == 0
