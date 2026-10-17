from email.message import Message
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from api.models import Category, CrawlRun, CrawlerTarget, SourceConfig
from api.services.article_fetcher.safe_http import CachedResponse


RSS = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Official</title>
<item><guid>notice-1</guid><title>Official health notice</title>
<link>https://official.example.cn/notices/1</link><description>Public summary.</description>
<pubDate>Wed, 14 Oct 2026 08:00:00 +0800</pubDate></item></channel></rss>'''


def payload(category_id, source_key='official_health'):
    return {
        'source_key': source_key,
        'publisher_name': '官方机构',
        'channel_name': '官方健康动态',
        'category': category_id,
        'region': 'domestic',
        'language': 'zh',
        'content_kind': 'article',
        'reading_policy': 'summary_only',
        'summary_allowed': True,
        'feed_full_content_allowed': False,
        'official_html_full_content_allowed': False,
        'endpoints': [{
            'kind': 'rss', 'url': 'https://official.example.cn/feed.xml',
            'allowed_domains': ['official.example.cn'], 'priority': 10,
            'parser_config': {}, 'conditional_requests': True,
            'request_interval_seconds': 600, 'max_response_bytes': 2097152,
            'max_pages': 1, 'max_items': 50, 'enabled': True,
        }],
    }


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user('source-admin', is_superuser=True, is_staff=True)
    client = APIClient()
    client.force_login(user)
    return client, user


@pytest.fixture
def medical_category(db):
    return Category.objects.get_or_create(name='医疗健康', defaults={'slug': 'medical-health'})[0]


@pytest.mark.django_db
def test_source_api_is_superuser_only_and_lists_code_sources(medical_category):
    ordinary = User.objects.create_user('source-ordinary')
    client = APIClient(); client.force_login(ordinary)
    assert client.get('/api/admin/crawler/sources/').status_code == 403
    admin = User.objects.create_user('source-super', is_superuser=True, is_staff=True)
    client.force_login(admin)
    response = client.get('/api/admin/crawler/sources/')
    assert response.status_code == 200
    assert any(row['source_key'] == 'bbc' and row['maintenance'] == 'code' and row['read_only'] for row in response.data)


@pytest.mark.django_db
def test_create_probe_approve_run_and_enable_are_explicit(admin_client, medical_category):
    client, user = admin_client
    created = client.post('/api/admin/crawler/sources/', payload(medical_category.pk), format='json')
    assert created.status_code == 201, created.data
    assert created.data['status'] == 'draft'
    target = CrawlerTarget.objects.get(pk='official_health')
    assert target.enabled is False
    assert client.post('/api/admin/crawler/sources/official_health/approve/', {}, format='json').status_code == 409

    headers = Message()
    headers['Content-Type'] = 'application/rss+xml; charset=utf-8'
    response = CachedResponse('https://official.example.cn/feed.xml', 200, headers, RSS)
    with patch('api.services.source_probe.safe_urlopen', return_value=response):
        probed = client.post('/api/admin/crawler/sources/official_health/probe/', {}, format='json')
    assert probed.status_code == 200, probed.data
    assert probed.data['status'] == 'probed'
    assert probed.data['probe_summary']['sample_articles'][0]['identity'] == 'notice-1'

    approved = client.post('/api/admin/crawler/sources/official_health/approve/', {}, format='json')
    assert approved.status_code == 200
    assert approved.data['approval_is_current'] and approved.data['can_enable']
    assert CrawlerTarget.objects.get(pk='official_health').enabled is False

    trial = client.post('/api/admin/crawler/sources/official_health/run/', {}, format='json')
    assert trial.status_code == 201, trial.data
    trial_run = CrawlRun.objects.get(target_id='official_health')
    assert trial_run.requested_by_id == user.id
    assert trial_run.config_snapshot['source_key'] == 'official_health'
    assert trial_run.config_snapshot['config_version'] == 1
    assert CrawlerTarget.objects.get(pk='official_health').enabled is False

    enabled = client.post('/api/admin/crawler/sources/official_health/enable/', {'enabled': True}, format='json')
    assert enabled.status_code == 200
    assert enabled.data['status'] == 'enabled'
    assert CrawlerTarget.objects.get(pk='official_health').enabled is True


@pytest.mark.django_db
def test_probe_enforces_endpoint_byte_cap_before_parsing(admin_client, medical_category):
    client, _ = admin_client
    created = client.post('/api/admin/crawler/sources/', payload(medical_category.pk), format='json')
    assert created.status_code == 201
    config = SourceConfig.objects.get(pk='official_health')
    endpoint = config.endpoints.first()
    # Direct DB fixture models an older approved endpoint limit, rather than
    # relying on API validation or contacting any real publisher.
    endpoint.max_response_bytes = len(RSS) - 1
    endpoint.save(update_fields=['max_response_bytes'])
    sizes = []

    class TrackingResponse(CachedResponse):
        def read(self, amount=None):
            sizes.append(amount)
            return super().read(amount)

    headers = Message()
    headers['Content-Type'] = 'application/rss+xml'
    response = TrackingResponse('https://official.example.cn/feed.xml', 200, headers, RSS)
    with patch('api.services.source_probe.safe_urlopen', return_value=response):
        result = client.post('/api/admin/crawler/sources/official_health/probe/', {}, format='json')
    assert result.status_code == 200
    assert sizes == [len(RSS)]
    assert result.data['status'] == 'unsupported'
    assert result.data['probe_summary']['error_code'] == 'response_too_large'
    assert CrawlerTarget.objects.get(pk='official_health').enabled is False


@pytest.mark.django_db
def test_patch_invalidates_probe_approval_and_disables_target(admin_client, medical_category):
    client, user = admin_client
    client.post('/api/admin/crawler/sources/', payload(medical_category.pk), format='json')
    config = SourceConfig.objects.get(pk='official_health')
    config.status = 'enabled'; config.probed_at = config.approved_at = config.updated_at
    config.probed_config_version = config.approved_config_version = 1
    config.approved_by = user
    config.save()
    CrawlerTarget.objects.filter(pk=config.pk).update(enabled=True)

    changed = client.patch(
        '/api/admin/crawler/sources/official_health/',
        {'channel_name': '官方健康发布'}, format='json',
    )
    assert changed.status_code == 200, changed.data
    assert changed.data['config_version'] == 2
    assert changed.data['status'] == 'draft'
    assert not changed.data['probe_is_current'] and not changed.data['approval_is_current']
    assert CrawlerTarget.objects.get(pk=config.pk).enabled is False


@pytest.mark.django_db
def test_reprobe_revokes_approval_and_disables_scheduling(admin_client, medical_category):
    client, user = admin_client
    client.post('/api/admin/crawler/sources/', payload(medical_category.pk), format='json')
    config = SourceConfig.objects.get(pk='official_health')
    config.status = 'enabled'; config.probed_at = config.approved_at = config.updated_at
    config.probed_config_version = config.approved_config_version = 1
    config.approved_by = user
    config.save()
    CrawlerTarget.objects.filter(pk=config.pk).update(enabled=True)
    headers = Message(); headers['Content-Type'] = 'application/rss+xml'
    with patch('api.services.source_probe.safe_urlopen', return_value=CachedResponse(
        'https://official.example.cn/feed.xml', 200, headers, RSS,
    )):
        response = client.post('/api/admin/crawler/sources/official_health/probe/', {}, format='json')
    assert response.status_code == 200
    assert response.data['status'] == 'probed'
    assert not response.data['approval_is_current']
    assert CrawlerTarget.objects.get(pk=config.pk).enabled is False


@pytest.mark.django_db
def test_source_validation_rejects_code_collision_scripts_and_unsafe_domains(admin_client, medical_category):
    client, _ = admin_client
    collision = client.post('/api/admin/crawler/sources/', payload(medical_category.pk, 'bbc'), format='json')
    assert collision.status_code == 400
    unsafe = payload(medical_category.pk, 'unsafe_health')
    unsafe['endpoints'][0]['allowed_domains'] = ['different.example.cn']
    assert client.post('/api/admin/crawler/sources/', unsafe, format='json').status_code == 400
    html = payload(medical_category.pk, 'html_health')
    html['endpoints'][0].update({
        'kind': 'html',
        'parser_config': {
            'list_item': 'li', 'title': 'a', 'link': 'a', 'date': 'time',
            'custom_script': 'return document.cookie',
        },
    })
    assert client.post('/api/admin/crawler/sources/', html, format='json').status_code == 400


@pytest.mark.django_db
def test_admin_source_mutations_require_csrf(admin_client, medical_category):
    user = admin_client[1]
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user)
    assert client.post('/api/admin/crawler/sources/', payload(medical_category.pk), format='json').status_code == 403
    token_response = client.get('/api/auth/csrf/')
    token = token_response.cookies['csrftoken'].value
    created = client.post(
        '/api/admin/crawler/sources/', payload(medical_category.pk), format='json',
        HTTP_X_CSRFTOKEN=token,
    )
    assert created.status_code == 201


@pytest.mark.django_db
def test_regulatory_data_partial_patch_cannot_cross_reading_policy(admin_client, medical_category):
    client, _ = admin_client
    data = payload(medical_category.pk, 'regulatory_feed')
    data.update(content_kind='regulatory_data', reading_policy='regulatory_data')
    assert client.post('/api/admin/crawler/sources/', data, format='json').status_code == 201
    response = client.patch(
        '/api/admin/crawler/sources/regulatory_feed/', {'reading_policy': 'summary_only'}, format='json',
    )
    assert response.status_code == 400
    assert SourceConfig.objects.get(pk='regulatory_feed').reading_policy == 'regulatory_data'


@pytest.mark.django_db
def test_code_maintained_source_is_read_only_and_draft_delete_is_guarded(admin_client, medical_category):
    client, _ = admin_client
    assert client.patch('/api/admin/crawler/sources/bbc/', {'channel_name': 'changed'}, format='json').status_code == 409
    assert client.post('/api/admin/crawler/sources/', payload(medical_category.pk), format='json').status_code == 201
    assert client.delete('/api/admin/crawler/sources/official_health/').status_code == 204
    assert not SourceConfig.objects.filter(pk='official_health').exists()
