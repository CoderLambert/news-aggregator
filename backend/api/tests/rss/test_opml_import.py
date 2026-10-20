import uuid
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ChannelGroup, ChannelSubscription
from api.rss.import_models import RssImportBatch, RssImportItem
from api.rss.models import FeedBinding, FeedOperation
from api.rss.opml import MAX_BYTES, process_imports, parse_opml

pytestmark = pytest.mark.django_db(transaction=True)
XML = b'''<?xml version="1.0"?><opml version="2.0"><body><outline text="Tech"><outline type="rss" text="One" xmlUrl="https://example.com/feed"/></outline><outline text="Reading"><outline type="rss" text="One again" xmlUrl="https://EXAMPLE.com:443/feed#same"/><outline type="rss" text="Two" xmlUrl="https://example.org/rss"/></outline></body></opml>'''


@pytest.fixture
def people(settings, monkeypatch):
    settings.PUBLIC_SITE_MODE = 'full'
    monkeypatch.setenv('RSS_ENGINE_INSTANCE_UUID', str(uuid.uuid4()))
    monkeypatch.setenv('RSS_ENGINE_ACCOUNT_ID', '7')
    return get_user_model().objects.create_user('opml-a'), get_user_model().objects.create_user('opml-b')


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def preview(user, raw=XML):
    return client(user).post('/api/me/rss-imports/preview/', {'file': SimpleUploadedFile('feeds.opml', raw)}, format='multipart')


def confirmation(response, **overrides):
    return {'preview_token': response.data['preview_token'], 'selected_ids': [item['id'] for item in response.data['items']],
            'group_map': {}, **overrides}


def test_preview_bytes_no_network_dedup_union_and_no_subscriptions(people):
    with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
        result = preview(people[0])
    assert result.status_code == 201, result.data
    assert len(result.data['items']) == 2
    item = next(item for item in result.data['items'] if item['feed_url'] == 'https://example.com/feed')
    assert item['groups'] == ['Reading', 'Tech']
    assert not FeedBinding.objects.exists() and not ChannelSubscription.objects.exists()
    assert result['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('raw', [b'http://example.com/feed', b'<!DOCTYPE opml [<!ENTITY x SYSTEM "file:///etc/passwd">]><opml><body>&x;</body></opml>',
    b'<opml>' + b'<outline>' * 18 + b'</outline>' * 18 + b'</opml>', b'x' * (MAX_BYTES + 1)],
    ids=['not-xml', 'external-entity', 'excessive-depth', 'oversized'])
def test_malicious_or_oversized_file_rejected(people, raw):
    assert preview(people[0], raw).status_code in (400, 413)
    assert not RssImportBatch.objects.exists()


def test_credential_url_redacted(people):
    result = preview(people[0], b'<opml><body><outline type="rss" text="secret" xmlUrl="https://example.com/feed?token=hidden"/></body></opml>')
    assert result.status_code == 201
    assert result.data['items'][0]['status'] == 'invalid'
    assert 'hidden' not in str(result.data) and 'secret' not in str(result.data)


def test_confirm_groups_replay_and_owner_binding(people):
    a, b = people
    result = preview(a)
    group = ChannelGroup.objects.create(user=a, name='Existing')
    data = confirmation(result, group_map={'Tech': group.pk, 'Reading': {'create': 'New'}})
    assert client(b).post('/api/me/rss-imports/confirm/', data, format='json').status_code == 404
    first = client(a).post('/api/me/rss-imports/confirm/', data, format='json')
    assert first.status_code == 202, first.data
    assert client(a).post('/api/me/rss-imports/confirm/', data, format='json').status_code == 202
    changed = {**data, 'selected_ids': data['selected_ids'][:1]}
    assert client(a).post('/api/me/rss-imports/confirm/', changed, format='json').status_code == 409
    assert process_imports() == 2 and process_imports() == 0
    from api.tests.rss.registration_fixtures import connect_pending
    assert not ChannelSubscription.objects.exists()
    connect_pending()
    assert ChannelSubscription.objects.count() == 2
    assert sorted(ChannelSubscription.objects.get(source__feed_links__binding__canonical_feed_url='https://example.com/feed').groups.values_list('name', flat=True)) == ['Existing', 'New']
    assert client(b).get(f"/api/me/rss-imports/{result.data['id']}/").status_code == 404
    assert client(a).get(f"/api/me/rss-imports/{result.data['id']}/").status_code == 200


def test_foreign_groups_and_expired_token_rejected_without_writes(people):
    a, b = people
    result = preview(a)
    group = ChannelGroup.objects.create(user=b, name='Private')
    data = confirmation(result, group_map={'Tech': group.pk})
    assert client(a).post('/api/me/rss-imports/confirm/', data, format='json').status_code == 404
    RssImportBatch.objects.update(expires_at=timezone.now())
    assert client(a).post('/api/me/rss-imports/confirm/', confirmation(result), format='json').status_code == 400
    assert not ChannelSubscription.objects.exists()


def test_partial_failure_retries_only_failed_item_and_never_unknown(people):
    a, _ = people
    result = preview(a)
    client(a).post('/api/me/rss-imports/confirm/', confirmation(result), format='json')
    process_imports()
    items = list(RssImportItem.objects.select_related('operation'))
    FeedOperation.objects.filter(pk=items[0].operation_id).update(state='succeeded')
    FeedOperation.objects.filter(pk=items[1].operation_id).update(state='manual_blocked')
    url = f"/api/me/rss-imports/{result.data['id']}/"
    request = {'selected_ids': [str(items[1].pk)]}
    assert client(a).post(url, request, format='json').status_code == 409
    FeedOperation.objects.filter(pk=items[1].operation_id).update(state='failed')
    assert client(a).post(url, request, format='json').status_code == 202
    assert client(a).post(url, request, format='json').status_code == 202
    assert process_imports() == 1
    # Remote operation labels alone do not grant a subscription before completion.
    assert ChannelSubscription.objects.count() == 0
    items[0].refresh_from_db()
    items[1].refresh_from_db()
    assert items[0].operation.state == 'succeeded'
    assert items[1].operation.state == 'pending'


def test_personal_multigroup_export_roundtrip_preserves_relations(people):
    a, b = people
    result = preview(a)
    data = confirmation(result, group_map={'Tech': {'create': 'Tech'}, 'Reading': {'create': 'Reading'}})
    client(a).post('/api/me/rss-imports/confirm/', data, format='json')
    process_imports()
    from api.tests.rss.registration_fixtures import connect_pending
    connect_pending()
    exported = client(a).get('/api/me/rss-subscriptions/export/')
    assert exported.status_code == 200
    assert len(ET.fromstring(exported.content).find('body')) == 2
    assert len(parse_opml(exported.content)) == 2
    assert b'example.com' not in client(b).get('/api/me/rss-subscriptions/export/').content
    roundtrip = preview(a, exported.content)
    client(a).post('/api/me/rss-imports/confirm/', confirmation(roundtrip), format='json')
    process_imports()
    assert ChannelSubscription.objects.count() == 2 and FeedBinding.objects.count() == 2


def test_old_channel_unsubscribe_reconciles_last_reference(people):
    a, _ = people
    result = client(a).post('/api/me/rss-subscriptions/', {'feed_url': 'https://example.com/feed'}, format='json', HTTP_IDEMPOTENCY_KEY='old-api')
    from api.tests.rss.registration_fixtures import connect_pending
    connect_pending()
    response = client(a).post('/api/me/channel-subscriptions/', {'action': 'unsubscribe', 'source_ids': [result.data['source_id']]}, format='json')
    assert response.status_code == 200
    assert not FeedBinding.objects.get().desired_enabled
