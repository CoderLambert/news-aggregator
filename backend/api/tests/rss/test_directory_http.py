import uuid
from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from api.models import Category, News
from api.rss.directory import import_pinned_seed
from api.rss.directory_models import FeedDirectoryEntry
from api.rss.models import FeedBinding, EngineEntryMap
from api.rss.subscriptions import subscribe

pytestmark = pytest.mark.django_db(transaction=True)


def test_directory_has_only_current_user_subscriptions_and_authorized_previews(settings, monkeypatch):
    settings.PUBLIC_SITE_MODE = 'full'
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(uuid.uuid4()))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '7')
    import_pinned_seed()
    entry = FeedDirectoryEntry.objects.filter(kind='feed').first()
    a, b = [get_user_model().objects.create_user(name) for name in ['dir-a', 'dir-b']]
    _, result = subscribe(a, {'directory_entry_id': str(entry.entry_id)}, 'directory')
    from api.tests.rss.registration_fixtures import connect_pending
    connect_pending()
    news = News.objects.create(title='Private headline', content='Private summary', source_id=result['source_id'],
        category=Category.objects.create(name='Private', slug='private-dir'), url='https://example.com/private', publish_time=timezone.now())
    EngineEntryMap.objects.create(binding=FeedBinding.objects.get(), engine_entry_id=1, news=news, source_url=news.url, disposition='linked')
    api = APIClient()
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        api.force_authenticate(b)
        result_b = api.get('/api/rss/directory/', {'q': entry.name})
        row_b = next(row for row in result_b.data['results'] if row['id'] == str(entry.entry_id))
        assert not row_b['subscribed'] and not row_b['cached_articles']
        api.force_authenticate(a)
        result_a = api.get('/api/rss/directory/', {'q': entry.name})
        row_a = next(row for row in result_a.data['results'] if row['id'] == str(entry.entry_id))
        assert row_a['subscribed'] and row_a['cached_articles'][0]['id'] == news.pk
        assert result_a['Cache-Control'] == 'private, no-store'
    api.force_authenticate(None)
    settings.PUBLIC_SITE_MODE = 'read_only'
    assert api.get('/api/rss/directory/').status_code == 200


def test_unconfigured_engine_does_not_offer_executable_templates(settings, monkeypatch):
    settings.PUBLIC_SITE_MODE = 'full'
    monkeypatch.delenv('RSS_ENGINE_INSTANCE_UUID', raising=False)
    import_pinned_seed()
    response = APIClient().get('/api/rss/directory/')
    assert response.status_code == 200
    assert not any(row['executable'] for row in response.data['results'])
    assert APIClient().get('/api/rss/directory/', {'cursor': 'forged'}).status_code == 400
