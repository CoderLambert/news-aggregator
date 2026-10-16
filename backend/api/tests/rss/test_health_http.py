import json
import time
import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from api.rss.health_http import current_runtime


@pytest.mark.parametrize('state', [[], {}, {'timestamp': 0}, 'invalid', {'timestamp': None}])
def test_invalid_heartbeat_is_unknown(tmp_path, monkeypatch, state):
    monkeypatch.setenv('RSS_RUNTIME_DIR', str(tmp_path))
    (tmp_path / 'heartbeat.json').write_text(json.dumps(state))
    assert current_runtime(uuid.uuid4(), 7) is None


@pytest.mark.django_db
def test_health_requires_admin_and_current_matching_heartbeat(tmp_path, monkeypatch, settings):
    settings.PUBLIC_SITE_MODE = 'full'
    instance = str(uuid.uuid4())
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', instance)
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '7')
    monkeypatch.setenv('RSS_RUNTIME_DIR', str(tmp_path))
    user = get_user_model().objects.create_user('health-admin', is_staff=True)
    client = APIClient()
    assert client.get('/api/admin/rss/health/').status_code == 401
    client.force_authenticate(user)
    state = dict(engine_instance_uuid=instance, account_id=7, mode='sync_worker',
                 timestamp=time.time(), engine_ready=True, error_class=None)
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        response = client.get('/api/admin/rss/health/')
        assert response.status_code == 200 and response.data['engine_ready'] is False
        assert response.data['initial_sync'] is True and response.data['lag'] is None
        assert response['Cache-Control'] == 'private, no-store'
        path = tmp_path / 'heartbeat.json'
        path.write_text(json.dumps(state))
        assert client.get('/api/admin/rss/health/').data['engine_ready'] is True
        for changed in [dict(account_id=8), dict(timestamp=time.time()-61), dict(mode='orm_shell')]:
            path.write_text(json.dumps({**state, **changed}))
            assert client.get('/api/admin/rss/health/').data['engine_ready'] is False
    user.is_staff = False
    user.save()
    assert client.get('/api/admin/rss/health/').status_code == 403


@pytest.mark.django_db
def test_list_and_detail_report_engine_inferred_time_without_loading_body(settings):
    from django.contrib.auth.models import AnonymousUser
    from django.utils import timezone
    from rest_framework.test import APIRequestFactory
    from api.models import Category, News, Source, SourcePublication
    from api.rss.access import annotate_article_access
    from api.serializers import NewsListSerializer

    settings.PUBLIC_SITE_MODE = 'full'
    source = Source.objects.create(name='Inferred feed')
    SourcePublication.objects.create(source=source, publication='public', owner='miniflux', reading_policy='standard')
    news = News.objects.create(source=source, category=Category.objects.create(name='Inferred', slug='inferred'),
        title='Stored title', content='Stored summary', url='https://example.com/inferred', publish_time=timezone.now(),
        full_content_provenance={'_sync_metadata': {'publish_time_inferred': True}})
    request = APIRequestFactory().get('/api/news/')
    request.user = AnonymousUser()
    row = annotate_article_access(request.user, News.objects.all()).defer('full_content_provenance').get(pk=news.pk)
    assert 'full_content_provenance' in row.get_deferred_fields()
    serializer = NewsListSerializer(context={'request': request})
    assert serializer.get_publish_time_inferred(row) is True
    assert 'full_content_provenance' in row.get_deferred_fields()
    assert serializer.get_publish_time_inferred(news) is True
